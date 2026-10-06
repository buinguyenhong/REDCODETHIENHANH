import os
import json
import asyncio
import logging
from typing import Optional
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update

from app.config import settings
from app.database import engine, Base, AsyncSessionLocal
from app.api import api_router
from app.core.websocket_manager import manager
from app.core.security import hash_device_token, decode_access_token
from app.models import (
    Station, User, StationStatus, AlarmEvent, UserRole,
    AlarmStationState, StationAlarmStateEnum
)
from app.core.n8n_outbox import outbox_worker

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

    # 4. Start durable n8n notification outbox background worker
    outbox_task = asyncio.create_task(outbox_worker.start())
    outbox_worker._task = outbox_task
    logger.info("Durable notification outbox worker active.")

    yield

    # Shutdown
    logger.info("Shutting down Redcode Hospital Server...")
    await outbox_worker.stop()
    await manager.stop_monitor()

app = FastAPI(
    title="Redcode Hospital System",
    description="Hệ thống cảnh báo y tế khẩn cấp nội bộ bệnh viện",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    type: Optional[str] = Query(None),
    client_type: Optional[str] = Query(None),
    station_code: Optional[str] = Query(None),
    token: Optional[str] = Query(None)
):
    """
    Realtime WebSocket Gateway:
    - type / client_type = 'station': Kiosk / Receiver PC station (authenticated by station token hash)
    - type / client_type = 'dashboard': Operator / Admin web monitoring (strictly authenticated by JWT)
    """
    actual_type = type or client_type or "station"
    if actual_type == "station":
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

                    elif msg_type == "STATION_EVENT":
                        event_type = msg.get("event_type")
                        alarm_id = msg.get("alarm_id")
                        metadata = msg.get("metadata", {})
                        if event_type and alarm_id:
                            now = datetime.now(timezone.utc)
                            async with AsyncSessionLocal() as session:
                                st = (await session.execute(
                                    select(Station.id).where(Station.station_code == station_code)
                                )).scalar_one_or_none()

                                # 1. Update alarm_station_states table
                                if st:
                                    if event_type in ["RECEIVED", "DISPLAYED"]:
                                        await session.execute(
                                            update(AlarmStationState)
                                            .where(AlarmStationState.alarm_id == alarm_id, AlarmStationState.station_id == st)
                                            .values(
                                                state=StationAlarmStateEnum.DISPLAYED.value,
                                                received_at=now,
                                                displayed_at=now,
                                                updated_at=now
                                            )
                                        )
                                    elif event_type == "AUDIO_STARTED":
                                        await session.execute(
                                            update(AlarmStationState)
                                            .where(AlarmStationState.alarm_id == alarm_id, AlarmStationState.station_id == st)
                                            .values(
                                                state=StationAlarmStateEnum.AUDIO_STARTED.value,
                                                audio_started_at=now,
                                                updated_at=now
                                            )
                                        )
                                    elif event_type == "AUDIO_COMPLETED":
                                        await session.execute(
                                            update(AlarmStationState)
                                            .where(AlarmStationState.alarm_id == alarm_id, AlarmStationState.station_id == st)
                                            .values(
                                                state=StationAlarmStateEnum.AUDIO_COMPLETED.value,
                                                audio_completed_at=now,
                                                updated_at=now
                                            )
                                        )
                                    elif event_type == "AUDIO_FAILED":
                                        await session.execute(
                                            update(AlarmStationState)
                                            .where(AlarmStationState.alarm_id == alarm_id, AlarmStationState.station_id == st)
                                            .values(
                                                state=StationAlarmStateEnum.FAILED.value,
                                                failed_at=now,
                                                error_message=str(metadata.get("error", "Audio playback error")),
                                                updated_at=now
                                            )
                                        )

                                # 2. Append audit trail event
                                ev = AlarmEvent(
                                    alarm_id=alarm_id,
                                    station_id=st,
                                    event_type=event_type,
                                    event_time=now,
                                    event_metadata=metadata,
                                    created_at=now
                                )
                                session.add(ev)
                                await session.commit()

                    elif msg_type == "PING":
                        await websocket.send_text(json.dumps({"type": "PONG"}))

                except json.JSONDecodeError:
                    pass

        except WebSocketDisconnect:
            await manager.disconnect_station(station_code, websocket)
        except Exception as e:
            logger.error(f"WebSocket station error ({station_code}): {e}")
            await manager.disconnect_station(station_code, websocket)

    elif actual_type == "dashboard":
        # Strictly authenticate dashboard token
        if not token or not token.strip():
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Dashboard token required")
            return

        payload = decode_access_token(token)
        if not payload or not payload.get("sub"):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired token")
            return

        username = payload.get("sub")
        async with AsyncSessionLocal() as session:
            stmt = select(User).where(User.username == username)
            user = (await session.execute(stmt)).scalar_one_or_none()
            if not user or not user.enabled or user.role not in [UserRole.ADMIN.value, UserRole.OPERATOR.value, UserRole.VIEWER.value]:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized or inactive user")
                return

        # Dashboard client authenticated successfully
        await manager.connect_dashboard(websocket)
        try:
            await websocket.send_text(json.dumps({
                "type": "CONNECTION_ESTABLISHED",
                "client_type": "dashboard",
                "user": user.username,
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
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unsupported client type")
