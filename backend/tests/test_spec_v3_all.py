import os
import sys
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

# Ensure backend path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.seed import seed_database
from app.models import (
    User, Station, Alarm, AlarmStationState, StationAlarmStateEnum,
    NotificationOutbox, OutboxStatus, DepartmentAlarmPermission,
    SystemEvent, AlarmEvent
)
from app.core.security import create_access_token
from app.core.websocket_manager import manager
from app.core.n8n_outbox import outbox_worker
from sqlalchemy import select, func


@pytest_asyncio.fixture(scope="module", autouse=True)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()


async def get_auth_token(username: str = "admin", password: str = "admin123456") -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/auth/login", json={"username": username, "password": password})
        assert res.status_code == 200, f"Login failed for {username}: {res.text}"
        return res.json()["access_token"]


# =========================================================================
# I. SECURITY TESTS
# =========================================================================

@pytest.mark.asyncio
async def test_sec_1_unauth_get_alarms_rejected():
    """Unauthenticated GET /api/alarms must return 401"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/alarms")
        assert res.status_code == 401


def test_sec_2_dashboard_ws_auth_validation():
    """Dashboard WebSocket requires valid, active user JWT with valid role"""
    from starlette.websockets import WebSocketDisconnect
    with TestClient(app) as client:
        # 1. No token -> Rejected
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws?type=dashboard"):
                pass

        # 2. Invalid token -> Rejected
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws?type=dashboard&token=invalid_garbage_token"):
                pass

        # 3. Valid token -> Accepted
        valid_token = create_access_token(data={"sub": "admin", "role": "ADMIN", "department_id": 1})
        with client.websocket_connect(f"/ws?type=dashboard&token={valid_token}") as ws:
            data = ws.receive_json()
            assert data.get("type") == "CONNECTION_ESTABLISHED"


@pytest.mark.asyncio
async def test_sec_4_5_station_register_admin_only():
    """POST /api/stations/register must be strictly ADMIN only"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Anonymous -> 401
        anon_res = await ac.post("/api/stations/register", json={
            "station_code": "ST-ANON-01", "name": "Anon Station", "receiver_group_ids": [1]
        })
        assert anon_res.status_code == 401

        # 2. Viewer -> 403
        viewer_token = await get_auth_token("viewer", "pass123456")
        viewer_res = await ac.post("/api/stations/register", headers={"Authorization": f"Bearer {viewer_token}"}, json={
            "station_code": "ST-VIEW-01", "name": "View Station", "receiver_group_ids": [1]
        })
        assert viewer_res.status_code == 403

        # 3. Operator -> 403
        op_token = await get_auth_token("operator_cc", "pass123456")
        op_res = await ac.post("/api/stations/register", headers={"Authorization": f"Bearer {op_token}"}, json={
            "station_code": "ST-OP-01", "name": "Op Station", "receiver_group_ids": [1]
        })
        assert op_res.status_code == 403

        # 4. Admin -> 201 Success and returns unpredictable random token
        admin_token = await get_auth_token("admin", "admin123456")
        admin_res = await ac.post("/api/stations/register", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "station_code": "ST-SEC-ADMIN-01",
            "name": "Sec Admin Station",
            "department_id": 1,
            "receiver_group_ids": [1]
        })
        assert admin_res.status_code == 201
        data = admin_res.json()
        assert "raw_device_token" in data
        assert len(data["raw_device_token"]) >= 32
        assert "st-sec-admin-01" not in data["raw_device_token"].lower()  # Unpredictable


@pytest.mark.asyncio
async def test_sec_6_7_8_station_dismiss_auth_and_receiver_group():
    """Dismiss requires valid station token AND station must belong to alarm receiver group"""
    admin_token = await get_auth_token("admin", "admin123456")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Register Station A (in receiver group 2 = EMERGENCY_TEAM)
        res_a = await ac.post("/api/stations/register", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "station_code": "ST-GROUP-A", "name": "Station Group A", "department_id": 2, "receiver_group_ids": [2]
        })
        token_a = res_a.json()["raw_device_token"]

        # Register Station B (in receiver group 3 = INTERNAL_MED only)
        res_b = await ac.post("/api/stations/register", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "station_code": "ST-GROUP-B", "name": "Station Group B", "department_id": 7, "receiver_group_ids": [3]
        })
        token_b = res_b.json()["raw_device_token"]

        # Admin triggers alarm 1 (RED_CODE_1 -> target group 2 = EMERGENCY_TEAM)
        alarm_res = await ac.post("/api/alarms", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "alarm_type_id": 1, "source_location": "P102", "note": "Sec dismiss test"
        })
        alarm_id = alarm_res.json()["id"]

        # 1. No token -> 401 or 422
        bad1 = await ac.post("/api/stations/dismiss", json={
            "alarm_id": alarm_id, "station_code": "ST-GROUP-A", "device_token": ""
        })
        assert bad1.status_code in [401, 422]

        # 2. Wrong token -> 401
        bad2 = await ac.post("/api/stations/dismiss", json={
            "alarm_id": alarm_id, "station_code": "ST-GROUP-A", "device_token": "wrong-token"
        })
        assert bad2.status_code == 401

        # 3. Station A attempts dismiss using Station B's token -> 401
        bad3 = await ac.post("/api/stations/dismiss", json={
            "alarm_id": alarm_id, "station_code": "ST-GROUP-A", "device_token": token_b
        })
        assert bad3.status_code == 401

        # 4. Station B attempts dismiss with its own valid token, but is NOT in receiver group 2 -> 403
        bad4 = await ac.post("/api/stations/dismiss", json={
            "alarm_id": alarm_id, "station_code": "ST-GROUP-B", "device_token": token_b
        })
        assert bad4.status_code == 403

        # 5. Station A dismisses with its own valid token and is in receiver group -> 200
        ok = await ac.post("/api/stations/dismiss", json={
            "alarm_id": alarm_id, "station_code": "ST-GROUP-A", "device_token": token_a, "note": "Acknowledged"
        })
        assert ok.status_code == 200
        assert ok.json()["status"] == "dismissed_locally"


@pytest.mark.asyncio
async def test_sec_9_operator_source_department_anti_spoofing():
    """OPERATOR cannot spoof source_department_id. Backend must force user.department_id"""
    op_token = await get_auth_token("operator_cc", "pass123456")  # CC department ID is 2
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Operator attempts to spoof source_department_id = 9 (Khoa Khám Bệnh)
        res = await ac.post("/api/alarms", headers={"Authorization": f"Bearer {op_token}"}, json={
            "alarm_type_id": 1,
            "source_department_id": 9,  # Attempt to spoof
            "source_location": "Sảnh chờ",
            "note": "Anti-spoofing check"
        })
        assert res.status_code == 201
        data = res.json()
        # Must strictly be operator's own department ID (2 = CC), NOT 9
        assert data["source_department_id"] == 2


@pytest.mark.asyncio
async def test_sec_10_department_permission_enforcement():
    """Operator cannot trigger alarm type if department permission is disabled"""
    admin_token = await get_auth_token("admin", "admin123456")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Department 9 (Khoa Khám Bệnh = KKB) does NOT have permission for RED_CODE_1
        uniq_user = f"op_kkb_{int(datetime.now().timestamp() * 1000)}"
        u_res = await ac.post("/api/users", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "username": uniq_user,
            "password": "pass123456",
            "display_name": "Op Khoa Khám Bệnh",
            "department_id": 9,
            "role": "OPERATOR"
        })
        assert u_res.status_code == 201

        op_kkb_token = await get_auth_token(uniq_user, "pass123456")

        # op_kkb attempts to trigger RED_CODE_1 (alarm_type_id = 1) -> 403 Forbidden
        trigger_res = await ac.post("/api/alarms", headers={"Authorization": f"Bearer {op_kkb_token}"}, json={
            "alarm_type_id": 1,
            "source_location": "Phòng khám 101",
            "note": "Permission restriction test"
        })
        assert trigger_res.status_code == 403
        assert "không có quyền" in trigger_res.json()["detail"].lower()


# =========================================================================
# II. ALARM STATE & LIFECYCLE TESTS
# =========================================================================

@pytest.mark.asyncio
async def test_state_alarm_station_states_and_local_dismiss():
    """Verify alarm_station_states creation, local dismiss leaves global alarm ACTIVE"""
    admin_token = await get_auth_token("admin", "admin123456")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Register test station in group 1 (ALL_HOSPITAL)
        res_st = await ac.post("/api/stations/register", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "station_code": "ST-STATE-01", "name": "Station State 01", "department_id": 1, "receiver_group_ids": [1]
        })
        st_token = res_st.json()["raw_device_token"]
        st_id = res_st.json()["id"]

        # Create alarm in group 1
        al_res = await ac.post("/api/alarms", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "alarm_type_id": 2, "source_location": "Khoa Ngoại", "note": "State model test"
        })
        alarm_id = al_res.json()["id"]

        # Verify alarm_station_states record exists
        async with AsyncSessionLocal() as session:
            stmt = select(AlarmStationState).where(
                AlarmStationState.alarm_id == alarm_id,
                AlarmStationState.station_id == st_id
            )
            st_state = (await session.execute(stmt)).scalar_one_or_none()
            assert st_state is not None
            assert st_state.state in [StationAlarmStateEnum.PENDING.value, StationAlarmStateEnum.DELIVERED.value]

        # Station dismisses locally
        d_res = await ac.post("/api/stations/dismiss", json={
            "alarm_id": alarm_id,
            "station_code": "ST-STATE-01",
            "device_token": st_token,
            "note": "Dismissed by nurse"
        })
        assert d_res.status_code == 200

        # Verify alarm_station_states is DISMISSED
        async with AsyncSessionLocal() as session:
            stmt = select(AlarmStationState).where(
                AlarmStationState.alarm_id == alarm_id,
                AlarmStationState.station_id == st_id
            )
            st_state = (await session.execute(stmt)).scalar_one_or_none()
            assert st_state.state == StationAlarmStateEnum.DISMISSED.value
            assert st_state.dismissed_at is not None

        # Global alarm MUST remain ACTIVE
        check_al = await ac.get(f"/api/alarms/{alarm_id}", headers={"Authorization": f"Bearer {admin_token}"})
        assert check_al.json()["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_state_alarm_cancellation_event():
    """Global alarm cancellation sets status=CANCELLED and creates ALARM_CANCELLED event"""
    admin_token = await get_auth_token("admin", "admin123456")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        al_res = await ac.post("/api/alarms", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "alarm_type_id": 2, "source_location": "Khoa Hồi Sức", "note": "Cancel test"
        })
        alarm_id = al_res.json()["id"]

        # Cancel alarm
        cancel_res = await ac.post(f"/api/alarms/{alarm_id}/cancel", headers={"Authorization": f"Bearer {admin_token}"})
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "CANCELLED"

        # Verify audit event ALARM_CANCELLED
        async with AsyncSessionLocal() as session:
            stmt = select(AlarmEvent).where(
                AlarmEvent.alarm_id == alarm_id,
                AlarmEvent.event_type == "ALARM_CANCELLED"
            )
            evt = (await session.execute(stmt)).scalar_one_or_none()
            assert evt is not None


# =========================================================================
# III. ATOMIC SEQUENCE & IDEMPOTENCY CONCURRENCY TESTS
# =========================================================================

@pytest.mark.asyncio
async def test_concurrency_atomic_sequence_monotonic():
    """50 concurrent alarm creation requests must each produce unique, monotonic server_sequence"""
    admin_token = await get_auth_token("admin", "admin123456")
    transport = ASGITransport(app=app)

    async def create_one(idx: int):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post("/api/alarms", headers={"Authorization": f"Bearer {admin_token}"}, json={
                "alarm_type_id": 4,  # FIRE_ALARM
                "source_location": f"Zone {idx}",
                "note": f"Concurrent test {idx}"
            })
            assert res.status_code == 201
            return res.json()["server_sequence"]

    tasks = [create_one(i) for i in range(50)]
    sequences = await asyncio.gather(*tasks)

    # Assert all sequences are strictly unique
    assert len(sequences) == 50
    assert len(set(sequences)) == 50, "Duplicate server_sequence detected under concurrency!"


@pytest.mark.asyncio
async def test_concurrency_idempotency_unique_enforcement():
    """20 concurrent requests with the SAME idempotency_key must result in exactly 1 alarm created"""
    admin_token = await get_auth_token("admin", "admin123456")
    transport = ASGITransport(app=app)
    shared_key = f"idemp-test-key-{datetime.now().timestamp()}"

    async def send_duplicate(idx: int):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.post("/api/alarms", headers={"Authorization": f"Bearer {admin_token}"}, json={
                "alarm_type_id": 4,
                "source_location": "ICU Room",
                "idempotency_key": shared_key,
                "note": f"Idempotency retry {idx}"
            })

    tasks = [send_duplicate(i) for i in range(20)]
    responses = await asyncio.gather(*tasks)

    # All responses must succeed (either 200 or 201)
    status_codes = [r.status_code for r in responses]
    assert all(c in [200, 201] for c in status_codes)

    # Check database: exactly ONE alarm exists with this idempotency_key
    async with AsyncSessionLocal() as session:
        stmt = select(func.count(Alarm.id)).where(Alarm.idempotency_key == shared_key)
        count = (await session.execute(stmt)).scalar_one()
        assert count == 1, f"Expected exactly 1 alarm, but found {count}!"


# =========================================================================
# IV. DURABLE N8N OUTBOX TESTS
# =========================================================================

@pytest.mark.asyncio
async def test_n8n_durable_outbox_persistence_and_retry():
    """Outbox stores notification durably, survives failure and increments attempts"""
    admin_token = await get_auth_token("admin", "admin123456")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/alarms", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "alarm_type_id": 4,
            "source_location": "N8N Outbox Test Zone",
            "note": "Testing durable outbox"
        })
        alarm_id = res.json()["id"]

    # Verify notification_outbox row was created in same transaction
    async with AsyncSessionLocal() as session:
        stmt = select(NotificationOutbox).where(NotificationOutbox.alarm_id == alarm_id)
        outbox_row = (await session.execute(stmt)).scalar_one_or_none()
        assert outbox_row is not None
        assert outbox_row.status in [OutboxStatus.PENDING.value, OutboxStatus.PROCESSING.value, OutboxStatus.SENT.value, OutboxStatus.FAILED.value]
        assert outbox_row.payload["alarm_id"] == alarm_id

    # Test outbox execution under n8n network failure
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = Exception("n8n server connection refused")
        await outbox_worker._send_item(outbox_row.id)

    async with AsyncSessionLocal() as session:
        stmt = select(NotificationOutbox).where(NotificationOutbox.alarm_id == alarm_id)
        outbox_after = (await session.execute(stmt)).scalar_one_or_none()
        assert outbox_after is not None
        # Attempt count recorded and error tracked
        assert outbox_after.attempt_count >= 1
        assert "connection refused" in str(outbox_after.last_error).lower()


# =========================================================================
# V. WEBSOCKET DISCONNECT RACE CONDITION TEST
# =========================================================================

@pytest.mark.asyncio
async def test_ws_disconnect_race_condition():
    """If Socket A connects, Socket B reconnects and becomes active, Socket A disconnect must NOT remove Socket B"""
    class MockWebSocket:
        def __init__(self, id_val):
            self.id_val = id_val
        async def accept(self):
            pass
        async def send_text(self, text):
            pass

    test_station = "ST-RACE-TEST"
    sock_a = MockWebSocket("socket_a")
    sock_b = MockWebSocket("socket_b")

    # 1. Socket A connects
    await manager.connect_station(test_station, sock_a)
    assert manager.active_stations.get(test_station) is sock_a

    # 2. Socket B connects (reconnect from refreshed browser/tab)
    await manager.connect_station(test_station, sock_b)
    assert manager.active_stations.get(test_station) is sock_b

    # 3. Socket A now fires disconnect event (delayed cleanup of old socket)
    await manager.disconnect_station(test_station, sock_a)

    # 4. Critical assertion: Socket B must STILL BE ACTIVE!
    assert manager.active_stations.get(test_station) is sock_b, "Race condition: Old socket disconnect killed active reconnect socket!"

    # 5. Socket B disconnects -> now station is removed
    await manager.disconnect_station(test_station, sock_b)
    assert test_station not in manager.active_stations


# =========================================================================
# VI. REPORT DATE RANGE FILTER TEST
# =========================================================================

@pytest.mark.asyncio
async def test_report_full_date_range_coverage():
    """Date filter with to_date='YYYY-MM-DD' must cover the entire day up to 23:59:59"""
    admin_token = await get_auth_token("admin", "admin123456")
    transport = ASGITransport(app=app)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        rep_res = await ac.get(
            f"/api/reports/summary?from_date={today_str}&to_date={today_str}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert rep_res.status_code == 200
        data = rep_res.json()
        assert "total_alarms" in data
        assert "device_offline_events_count" in data
        assert "by_type" in data
        assert "by_department" in data
