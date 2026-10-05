import os
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.config import settings
from app.database import engine, Base, AsyncSessionLocal
from app.api import api_router
from app.core.websocket_manager import manager
from app.core.security import hash_device_token, decode_access_token
from app.models import Station, User, StationStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("redcode.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Redcode Hospital Server...")
    os.makedirs(settings.AUDIO_UPLOAD_DIR, exist_ok=True)
    
    # 1. Create DB tables if not present
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema synchronized.")

    # 2. Seed default data if database is fresh
    from app.seed import seed_database
    await seed_database()

    # 3. Start station heartbeat offline monitor
    await manager.start_monitor(settings.STATION_OFFLINE_THRESHOLD_SECONDS)
    logger.info(f"Station offline monitor active (timeout: {settings.STATION_OFFLINE_THRESHOLD_SECONDS}s).")

    yield

    # Shutdown
    logger.info("Shutting down Redcode Hospital Server...")
    await manager.stop_monitor()

app = FastAPI(
    title="Redcode Hospital System",
    description="Hệ thống cảnh báo y tế khẩn cấp nội bộ bệnh viện",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS if settings.ALLOWED_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount local audio directory for static LAN access
if not os.path.exists(settings.AUDIO_UPLOAD_DIR):
    os.makedirs(settings.AUDIO_UPLOAD_DIR, exist_ok=True)
app.mount("/assets/audio", StaticFiles(directory=settings.AUDIO_UPLOAD_DIR), name="audio")

# Mount API routers
app.include_router(api_router)

# WebSocket Realtime Gateway
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    client_type: str = Query("station", alias="type"),
    station_code: str = Query(None),
    token: str = Query(None)
):
    """
    Realtime WebSocket Gateway:
    - client_type = 'station': Kiosk / Receiver PC station
    - client_type = 'dashboard': Operator / Admin web monitoring
    """
    if client_type == "station":
        if not station_code or not token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Station credentials required")
            return

        # Validate station token against database
        expected_hash = hash_device_token(token)
        async with AsyncSessionLocal() as session:
            stmt = select(Station).where(Station.station_code == station_code)
            station = (await session.execute(stmt)).scalar_one_or_none()

            if not station or not station.enabled or station.device_token_hash != expected_hash:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid station credentials")
                return

        # Connect station
        await manager.connect_station(station_code, websocket)

        try:
            # Send initial ACK with station info
            await websocket.send_text(json.dumps({
                "type": "CONNECTION_ESTABLISHED",
                "station_code": station_code,
                "server_time": datetime.now(timezone.utc).isoformat()
            }))

            while True:
                data_text = await websocket.receive_text()
                try:
                    msg = json.loads(data_text)
                    msg_type = msg.get("type")

                    if msg_type == "HEARTBEAT":
                        audio_ready = bool(msg.get("audio_ready", False))
                        client_ready = bool(msg.get("client_ready", True))
                        await manager.update_heartbeat(station_code, audio_ready, client_ready)
                        await websocket.send_text(json.dumps({
                            "type": "HEARTBEAT_ACK",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }))

                    elif msg_type == "AUDIO_STATE_CHANGED":
                        audio_ready = bool(msg.get("audio_ready", False))
                        await manager.update_heartbeat(station_code, audio_ready=audio_ready)

                    elif msg_type == "PING":
                        await websocket.send_text(json.dumps({"type": "PONG"}))

                except json.JSONDecodeError:
                    pass

        except WebSocketDisconnect:
            await manager.disconnect_station(station_code)
        except Exception as e:
            logger.error(f"WebSocket station error ({station_code}): {e}")
            await manager.disconnect_station(station_code)

    elif client_type == "dashboard":
        # Dashboard client connection
        await manager.connect_dashboard(websocket)
        try:
            await websocket.send_text(json.dumps({
                "type": "CONNECTION_ESTABLISHED",
                "client_type": "dashboard",
                "server_time": datetime.now(timezone.utc).isoformat()
            }))

            while True:
                data_text = await websocket.receive_text()
                try:
                    msg = json.loads(data_text)
                    if msg.get("type") == "PING":
                        await websocket.send_text(json.dumps({"type": "PONG"}))
                except json.JSONDecodeError:
                    pass

        except WebSocketDisconnect:
            await manager.disconnect_dashboard(websocket)
        except Exception as e:
            logger.error(f"WebSocket dashboard error: {e}")
            await manager.disconnect_dashboard(websocket)

    else:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unknown client type")
