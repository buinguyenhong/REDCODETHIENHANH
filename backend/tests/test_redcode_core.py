import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import engine, Base
from app.seed import seed_database
from app.core.security import create_access_token

@pytest_asyncio.fixture(scope="module", autouse=True)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()

@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["database"] == "ok"

@pytest.mark.asyncio
async def test_auth_login_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/auth/login", json={
            "username": "operator_cc",
            "password": "pass123456"
        })
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["user"]["username"] == "operator_cc"
        assert data["user"]["role"] == "OPERATOR"

@pytest.mark.asyncio
async def test_auth_login_invalid():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/auth/login", json={
            "username": "operator_cc",
            "password": "wrong_password"
        })
        assert res.status_code == 401

@pytest.mark.asyncio
async def test_unauthorized_alarm_creation_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/alarms", json={
            "alarm_type_id": 1,
            "source_location": "Phòng 101",
            "note": "Test unauth"
        })
        assert res.status_code == 401

@pytest.mark.asyncio
async def test_viewer_cannot_create_alarm():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Login as viewer
        login_res = await ac.post("/api/auth/login", json={
            "username": "viewer",
            "password": "pass123456"
        })
        token = login_res.json()["access_token"]
        
        # Try to trigger alarm
        res = await ac.post(
            "/api/alarms",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "alarm_type_id": 1,
                "source_location": "Phòng 102",
                "note": "Test viewer reject"
            }
        )
        assert res.status_code == 403

@pytest.mark.asyncio
async def test_operator_create_alarm_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_res = await ac.post("/api/auth/login", json={
            "username": "operator_cc",
            "password": "pass123456"
        })
        token = login_res.json()["access_token"]
        
        res = await ac.post(
            "/api/alarms",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "alarm_type_id": 1,
                "source_location": "Khu cấp cứu giường 02",
                "note": "Bệnh nhân ngưng thở đột ngột"
            }
        )
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "ACTIVE"
        assert data["server_sequence"] >= 1
        assert data["alarm_type"]["code"] == "RED_CODE_1"
        assert len(data["events"]) >= 2  # CREATED and BROADCAST

@pytest.mark.asyncio
async def test_station_heartbeat_and_local_dismiss():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Send station heartbeat
        hb_res = await ac.post("/api/stations/heartbeat", json={
            "station_code": "ST-CC-01",
            "device_token": "station-token-cc-01",
            "audio_ready": True,
            "client_ready": True
        })
        assert hb_res.status_code == 200
        assert hb_res.json()["status"] == "ok"

        # Operator triggers an alarm
        login_res = await ac.post("/api/auth/login", json={
            "username": "operator_cc",
            "password": "pass123456"
        })
        token = login_res.json()["access_token"]
        alarm_res = await ac.post(
            "/api/alarms",
            headers={"Authorization": f"Bearer {token}"},
            json={"alarm_type_id": 1, "source_location": "Phòng 01", "note": "Test local dismiss"}
        )
        alarm_id = alarm_res.json()["id"]

        # Local dismiss at station ST-CC-01
        dismiss_res = await ac.post("/api/stations/dismiss", json={
            "alarm_id": alarm_id,
            "station_code": "ST-CC-01",
            "note": "Bác sĩ trực tiếp nhận"
        })
        assert dismiss_res.status_code == 200
        assert dismiss_res.json()["status"] == "dismissed_locally"

        # Verify global alarm record is STILL active (Local dismiss doesn't terminate for whole hospital)
        check_alarm = await ac.get(f"/api/alarms/{alarm_id}")
        assert check_alarm.status_code == 200
        assert check_alarm.json()["status"] == "ACTIVE"

@pytest.mark.asyncio
async def test_export_xlsx():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_res = await ac.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123456"
        })
        token = login_res.json()["access_token"]

        res = await ac.get("/api/reports/export-xlsx", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res.headers["content-type"]
        assert len(res.content) > 1000  # Valid binary Excel file
