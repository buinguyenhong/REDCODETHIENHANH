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
    AlarmStationState, StationAlarmStateEnum, Alarm, AlarmStatus, SystemEvent
)
from app.core.n8n_outbox import outbox_worker
from app.core.station_lifecycle import acknowledge_station_event

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("redcode.main")


def create_all_allowed(environment: str, database_url: str) -> bool:
    """Có được tự tạo bảng từ metadata không.

    Chỉ trên SQLite, nơi schema là thứ dùng-một-lần cho dev. Trên PostgreSQL schema
    thuộc về Alembic: ``create_all`` ở đó sinh bảng nằm ngoài lịch sử migration, và
    lần ``alembic upgrade`` sau sẽ đụng độ với chúng. Chỉ dựa vào ``ENVIRONMENT`` là
    không đủ chặn vì biến này có thể bị đặt sai trong ``.env`` — đúng lỗi F-12, khi
    giá trị viết cứng trong docker-compose khiến ``.env`` không ghi đè được.

    Tách thành hàm riêng để kiểm thử được quyết định này mà không phải dựng cả
    vòng đời ứng dụng.
    """
    return environment in ('development', 'test') and database_url.startswith('sqlite')


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Redcode Hospital Server...")
    os.makedirs(settings.AUDIO_UPLOAD_DIR, exist_ok=True)

    # 1. Create DB tables if not present.
    if create_all_allowed(settings.ENVIRONMENT, settings.DATABASE_URL):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        previously_online = (await session.execute(select(Station).where(Station.websocket_connected == True))).scalars().all()
        for station in previously_online:
            session.add(SystemEvent(station_id=station.id, event_type='DEVICE_DISCONNECTED', severity='WARNING',
                message='Server startup reconciled previous connection', event_metadata={'reason': 'server_restart'}, created_at=datetime.now(timezone.utc)))
        await session.execute(update(Station).values(
            websocket_connected=False,
            status=StationStatus.OFFLINE.value,
            audio_ready=False,
            client_ready=False,
        ))
        await session.execute(update(User).where(User.role == 'VIEWER').values(enabled=False))
        await session.commit()
    logger.info("Database initialized; production schema is managed by Alembic.")

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

@app.middleware('http')
async def configuration_audit(request, call_next):
    response = await call_next(request)
    configuration = ('/api/users', '/api/departments', '/api/alarm-types', '/api/receiver-groups', '/api/audio', '/api/stations/register')
    if request.method in ('POST', 'PUT', 'DELETE') and response.status_code < 400 and request.url.path.startswith(configuration):
        authorization = request.headers.get('authorization', '')
        payload = decode_access_token(authorization[7:]) if authorization.startswith('Bearer ') else None
        try:
            async with AsyncSessionLocal() as session:
                session.add(SystemEvent(event_type='CONFIGURATION_CHANGED', severity='INFO', message='Configuration changed', event_metadata={'actor': payload.get('sub') if payload else None, 'method': request.method, 'path': request.url.path}, created_at=datetime.now(timezone.utc)))
                await session.commit()
        except Exception:
            logger.exception('Configuration audit persistence failed')
    return response

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

async def reject_websocket(websocket: WebSocket, reason: str) -> None:
    """Từ chối một WebSocket nhưng vẫn để client đọc được mã đóng.

    Gọi ``close()`` trước ``accept()`` khiến ASGI server trả về HTTP 403 cho
    gói nâng cấp, và trình duyệt quy về mã đóng 1006 (abnormal closure) không
    kèm lý do — credential bị từ chối trở nên không phân biệt được với mất
    mạng, nên client cứ thử lại mãi thay vì yêu cầu xác nhận lại thiết bị.
    Chấp nhận trước rồi đóng bằng 1008 sẽ gửi được close frame thật.
    """
    try:
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)
    except Exception:
        logger.debug("Không thể đóng sạch kết nối bị từ chối", exc_info=True)


async def station_has_unresolved_alarms(station_code: str) -> bool:
    """Trạm còn báo động ACTIVE chưa tắt tại chỗ hay không.

    Dùng để chủ động yêu cầu đồng bộ ngay khi trạm kết nối. Không lọc theo
    ``received_at``: một trạm đã ACK RECEIVED trước khi server khởi động lại vẫn
    phải được nhắc tải lại, nếu không việc phục hồi phụ thuộc hoàn toàn vào việc
    client tự giác gọi sync.
    """
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(AlarmStationState.id)
            .join(Station, Station.id == AlarmStationState.station_id)
            .join(Alarm, Alarm.id == AlarmStationState.alarm_id)
            .where(
                Station.station_code == station_code,
                Alarm.status == AlarmStatus.ACTIVE.value,
                AlarmStationState.state != StationAlarmStateEnum.DISMISSED.value,
            )
        )).scalars().first()
    return row is not None


# Nhịp tim chạy 5 giây một lần, nhưng phép kiểm tra "trạm còn báo động chưa ACK"
# không cần chạy mỗi nhịp. Nó chỉ bắt đúng một tình huống: khung broadcast bị mất
# trong khi socket vẫn sống. Mọi tình huống khác đã có đường khác phủ — trạm mất
# kết nối rồi nối lại thì connect kiểm tra đầy đủ, còn báo động mới phát thì chính
# khung broadcast là đường chính. Chạy mỗi 5 giây cho 100 trạm là khoảng 1.200 lượt
# JOIN ba bảng mỗi phút; giãn ra 30 giây còn khoảng 200 mà tình huống hiếm nói
# trên vẫn được phát hiện trong vòng nửa phút.
#
# Đã cân nhắc thay hẳn bằng cờ trong bộ nhớ (bật khi broadcast tới trạm, tắt khi
# trạm ACK). Cách đó bỏ được hẳn truy vấn, nhưng nếu cờ lệch một lần thì trạm thôi
# được nhắc đồng bộ trong im lặng — đúng loại hỏng khó thấy trong hệ báo động.
# Giãn nhịp giữ nguyên nguồn sự thật là database nên không có rủi ro đó.
PENDING_SYNC_CHECK_INTERVAL_SECONDS = 30
_last_pending_sync_check: dict[str, datetime] = {}


def _pending_sync_check_due(station_code: str) -> bool:
    """Đã tới hạn kiểm tra báo động chưa ACK của trạm này chưa.

    Ghi nhận luôn lượt kiểm tra hiện tại khi trả về True, nên hàm vừa hỏi vừa đặt
    hạn. Sổ chỉ có một mục cho mỗi mã trạm từng thấy (cỡ vài trăm), phù hợp với
    ràng buộc một API worker.
    """
    now = datetime.now(timezone.utc)
    previous = _last_pending_sync_check.get(station_code)
    if previous is not None and (now - previous).total_seconds() < PENDING_SYNC_CHECK_INTERVAL_SECONDS:
        return False
    _last_pending_sync_check[station_code] = now
    return True


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
            await reject_websocket(websocket, "Station credentials required")
            return

        # Validate station token against database
        expected_hash = hash_device_token(token)
        async with AsyncSessionLocal() as session:
            stmt = select(Station).where(Station.station_code == station_code)
            station = (await session.execute(stmt)).scalar_one_or_none()

            if not station or not station.enabled or station.device_token_hash != expected_hash:
                await reject_websocket(websocket, "Invalid station credentials")
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

            # Chủ động nhắc đồng bộ nếu trạm còn báo động chưa xử lý. Client kiosk
            # cũng tự gọi sync khi mở socket, nhưng để server làm chủ việc phục hồi
            # giúp thiết bị nhận theo giao thức (không tự sync) không im lặng mãi
            # sau khi server khởi động lại.
            #
            # Đây là lượt kiểm tra đầy đủ, nên nó cũng đặt lại hạn cho phép kiểm
            # tra định kỳ trong nhịp tim — vừa nối xong thì chưa cần hỏi lại.
            _last_pending_sync_check[station_code] = datetime.now(timezone.utc)
            if await station_has_unresolved_alarms(station_code):
                await websocket.send_text(json.dumps({"type": "SYNC_REQUIRED"}))

            while True:
                data_text = await websocket.receive_text()
                try:
                    msg = json.loads(data_text)
                    if not isinstance(msg, dict):
                        continue
                    if manager.active_stations.get(station_code) is not websocket:
                        await websocket.close(code=4001, reason="Station session superseded")
                        return
                    msg_type = msg.get("type")

                    if msg_type == "HEARTBEAT":
                        audio_ready = bool(msg.get("audio_ready", False))
                        client_ready = bool(msg.get("client_ready", True))
                        await manager.update_heartbeat(station_code, audio_ready, client_ready)
                        await websocket.send_text(json.dumps({
                            "type": "HEARTBEAT_ACK",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }))
                        if _pending_sync_check_due(station_code):
                            async with AsyncSessionLocal() as session:
                                pending = (await session.execute(select(AlarmStationState.id).join(Station).join(Alarm, Alarm.id == AlarmStationState.alarm_id).where(Station.station_code == station_code, Alarm.status == AlarmStatus.ACTIVE.value, AlarmStationState.received_at == None))).scalars().first()
                            if pending:
                                await websocket.send_text(json.dumps({'type': 'SYNC_REQUIRED'}))

                    elif msg_type == "AUDIO_STATE_CHANGED":
                        audio_ready = bool(msg.get("audio_ready", False))
                        await manager.update_heartbeat(station_code, audio_ready=audio_ready)

                    elif msg_type == "STATION_EVENT":
                        event_type = msg.get("event_type")
                        alarm_id = msg.get("alarm_id")
                        metadata = msg.get("metadata", {})
                        if isinstance(alarm_id, int) and not isinstance(alarm_id, bool):
                            async with AsyncSessionLocal() as session:
                                st = (await session.execute(
                                    select(Station.id).where(Station.station_code == station_code)
                                )).scalar_one_or_none()
                                accepted = await acknowledge_station_event(session, alarm_id, st, event_type, metadata)
                            await websocket.send_text(json.dumps({'type': 'STATION_EVENT_ACK', 'alarm_id': alarm_id, 'event_type': event_type, 'accepted': accepted}))

                    elif msg_type == "PING":
                        # PING cũng chứng minh kênh realtime còn sống. Không làm mới
                        # đồng hồ ở đây thì một client chỉ dùng PING bị monitor cắt ở
                        # ngưỡng 15 giây dù hoàn toàn khoẻ.
                        await manager.touch_station(station_code)
                        await websocket.send_text(json.dumps({"type": "PONG", "request_id": msg.get('request_id'), "server_time": datetime.now(timezone.utc).isoformat()}))

                except json.JSONDecodeError:
                    pass

        except WebSocketDisconnect:
            await manager.disconnect_station(station_code, websocket)
        except Exception as e:
            logger.error(f"WebSocket station error ({station_code}): {e}")
            await manager.disconnect_station(station_code, websocket)
        finally:
            # Hạn kiểm tra gắn với một phiên kết nối, không phải với mã trạm: dọn ở
            # đây để sổ trong bộ nhớ không giữ lại mã của trạm đã tháo máy.
            _last_pending_sync_check.pop(station_code, None)

    elif actual_type == "dashboard":
        # Strictly authenticate dashboard token
        if not token or not token.strip():
            await reject_websocket(websocket, "Dashboard token required")
            return

        payload = decode_access_token(token)
        if not payload or not payload.get("sub"):
            await reject_websocket(websocket, "Invalid or expired token")
            return

        username = payload.get("sub")
        async with AsyncSessionLocal() as session:
            stmt = select(User).where(User.username == username)
            user = (await session.execute(stmt)).scalar_one_or_none()
            if not user or not user.enabled or user.role not in [UserRole.ADMIN.value, UserRole.OPERATOR.value]:
                await reject_websocket(websocket, "Unauthorized or inactive user")
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
                        await websocket.send_text(json.dumps({"type": "PONG", "request_id": msg.get('request_id'), "server_time": datetime.now(timezone.utc).isoformat()}))
                except json.JSONDecodeError:
                    pass

        except WebSocketDisconnect:
            await manager.disconnect_dashboard(websocket)
        except Exception as e:
            logger.error(f"WebSocket dashboard error: {e}")
            await manager.disconnect_dashboard(websocket)

    else:
        await reject_websocket(websocket, "Unsupported client type")
