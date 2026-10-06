import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.seed import seed_database
from app.models import AlarmType, Station, ReceiverGroupStation, Alarm, AlarmEvent, AlarmStatus
from sqlalchemy import select

@pytest_asyncio.fixture(scope="module", autouse=True)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()

@pytest.mark.asyncio
async def test_alarm_idempotency():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_res = await ac.post("/api/auth/login", json={"username": "operator_cc", "password": "pass123456"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        idempotency_key = "idemp-test-unique-key-12345"
        payload = {
            "alarm_type_id": 1,
            "source_location": "Phòng 101",
            "note": "Idempotency test alarm",
            "idempotency_key": idempotency_key
        }

        # First request
        res1 = await ac.post("/api/alarms", headers=headers, json=payload)
        assert res1.status_code == 201
        data1 = res1.json()

        # Second request with same idempotency key
        res2 = await ac.post("/api/alarms", headers=headers, json=payload)
        assert res2.status_code in [200, 201]
        data2 = res2.json()

        # Must return the EXACT SAME alarm ID and not create duplicates
        assert data1["id"] == data2["id"]
        assert data1["server_sequence"] == data2["server_sequence"]

@pytest.mark.asyncio
async def test_department_authorization_restriction():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        admin_res = await ac.post("/api/auth/login", json={"username": "admin", "password": "admin123456"})
        admin_token = admin_res.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Get departments dynamically
        depts_res = await ac.get("/api/departments")
        depts = depts_res.json()
        cc_dept = next(d for d in depts if d["code"] == "CC")
        hscc_dept = next(d for d in depts if d["code"] == "HSCC")

        # Create a restricted alarm type: only allowed for Khoa Cấp cứu
        unique_code = f"RESTRICTED_{int(time.time())}"
        create_type_res = await ac.post("/api/alarm-types", headers=admin_headers, json={
            "code": unique_code,
            "name": "Mã hạn chế khoa",
            "priority": 1,
            "display_color": "#ff0000",
            "allowed_department_ids": [cc_dept["id"]] # Only Khoa Cấp cứu
        })
        assert create_type_res.status_code == 201
        restricted_type_id = create_type_res.json()["id"]

        # 1. Operator CC (belongs to CC) -> Allowed
        op_res = await ac.post("/api/auth/login", json={"username": "operator_cc", "password": "pass123456"})
        op_token = op_res.json()["access_token"]
        res_allowed = await ac.post("/api/alarms", headers={"Authorization": f"Bearer {op_token}"}, json={
            "alarm_type_id": restricted_type_id,
            "source_location": "Khoa CC",
            "note": "Allowed test"
        })
        assert res_allowed.status_code == 201

        # 2. Operator HSCC (belongs to HSCC) -> Forbidden 403
        hs_res = await ac.post("/api/auth/login", json={"username": "operator_hscc", "password": "pass123456"})
        hs_token = hs_res.json()["access_token"]
        res_forbidden = await ac.post("/api/alarms", headers={"Authorization": f"Bearer {hs_token}"}, json={
            "alarm_type_id": restricted_type_id,
            "source_location": "Khoa HSCC",
            "note": "Forbidden test"
        })
        assert res_forbidden.status_code == 403

        # 3. Admin -> Always allowed bypass
        res_admin = await ac.post("/api/alarms", headers=admin_headers, json={
            "alarm_type_id": restricted_type_id,
            "source_location": "Toàn viện",
            "note": "Admin bypass"
        })
        assert res_admin.status_code == 201

@pytest.mark.asyncio
async def test_active_alarms_sync_and_display_completed():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        admin_res = await ac.post("/api/auth/login", json={"username": "admin", "password": "admin123456"})
        admin_token = admin_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Create alarm
        alarm_res = await ac.post("/api/alarms", headers=headers, json={
            "alarm_type_id": 1,
            "source_location": "Phòng Đồng Bộ",
            "note": "Test sync and completion"
        })
        alarm_id = alarm_res.json()["id"]

        # Check sync endpoint for ST-CC-01
        sync_res = await ac.get("/api/stations/ST-CC-01/active-alarms")
        assert sync_res.status_code == 200
        active_list = sync_res.json()
        assert any(a["alarm_id"] == alarm_id for a in active_list)

        # ST-CC-01 dismisses the alarm locally
        d1 = await ac.post("/api/stations/dismiss", json={
            "alarm_id": alarm_id,
            "station_code": "ST-CC-01",
            "note": "Acknowledged CC-01"
        })
        assert d1.status_code == 200

        # Now ST-CC-01 should no longer see it in active-alarms
        sync_after = await ac.get("/api/stations/ST-CC-01/active-alarms")
        assert not any(a["alarm_id"] == alarm_id for a in sync_after.json())

@pytest.mark.asyncio
async def test_health_sub_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # GET /api/health/db
        db_res = await ac.get("/api/health/db")
        assert db_res.status_code == 200
        db_data = db_res.json()
        assert db_data["status"] == "ok"
        assert "latency_ms" in db_data
        assert isinstance(db_data["latency_ms"], (int, float))

        # GET /api/health/websocket
        ws_res = await ac.get("/api/health/websocket")
        assert ws_res.status_code == 200
        ws_data = ws_res.json()
        assert ws_data["status"] == "ok"
        assert "active_connections" in ws_data
        assert "active_stations_count" in ws_data
