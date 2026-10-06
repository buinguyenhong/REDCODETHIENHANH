import pytest
import pytest_asyncio
import asyncio
import time
import json
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.websocket_manager import manager
from app.main import app
from app.database import engine, Base
from app.seed import seed_database
from httpx import AsyncClient, ASGITransport

@pytest_asyncio.fixture(scope="module", autouse=True)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()

class MockWebSocket:
    def __init__(self, station_code: str):
        self.station_code = station_code
        self.messages = []
        self.closed = False

    async def accept(self):
        pass

    async def send_text(self, text: str):
        self.messages.append(json.loads(text))

    async def close(self, code=1000, reason=""):
        self.closed = True

@pytest.mark.asyncio
async def test_50_concurrent_stations_broadcast_latency():
    """
    Section 29 Non-functional requirement:
    - 50+ concurrent receiver stations connected.
    - Broadcast delivery latency to all 50 stations must be under 1.0 second (1000ms).
    """
    num_stations = 50
    mock_sockets = {}

    # Connect 50 concurrent stations
    for i in range(1, num_stations + 1):
        code = f"ST-BENCH-{i:03d}"
        ws = MockWebSocket(code)
        mock_sockets[code] = ws
        await manager.connect_station(code, ws)

    assert len(manager.active_stations) >= num_stations

    # Measure broadcast delivery time
    test_payload = {
        "alarm_id": 9999,
        "code": "RED_CODE_LOAD_TEST",
        "name": "Thử nghiệm tải 50 trạm",
        "priority": 1,
        "location": "Toàn bệnh viện",
        "created_at": "2026-10-06T00:00:00Z"
    }

    start_time = time.perf_counter()
    await manager.broadcast_alarm(test_payload)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    print(f"\n[BENCHMARK] Thời gian broadcast tới {num_stations} trạm: {elapsed_ms:.2f} ms")

    # Assert broadcast latency <= 1000ms (Spec Section 29)
    assert elapsed_ms < 1000.0, f"Broadcast latency {elapsed_ms:.2f}ms exceeded 1000ms limit"

    # Verify every single station received the broadcast
    for code, ws in mock_sockets.items():
        assert len(ws.messages) >= 1
        last_msg = ws.messages[-1]
        assert last_msg["type"] == "ALARM_EVENT"
        assert last_msg["event"] == "ALARM_TRIGGERED"
        assert last_msg["data"]["alarm_id"] == 9999

    # Cleanup connections
    for code in mock_sockets:
        await manager.disconnect_station(code)

@pytest.mark.asyncio
async def test_50_concurrent_heartbeats():
    """
    Verify the server handles 50 concurrent heartbeat requests without failure.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Provision station dynamically to obtain real cryptographically secure token
        admin_res = await ac.post("/api/auth/login", json={"username": "admin", "password": "admin123456"})
        admin_token = admin_res.json()["access_token"]
        reg_res = await ac.post("/api/stations/register", headers={"Authorization": f"Bearer {admin_token}"}, json={
            "station_code": "ST-BENCH-50",
            "name": "Benchmark Station 50",
            "department_id": 2,
            "receiver_group_ids": [1]
        })
        assert reg_res.status_code == 201
        st_token = reg_res.json()["raw_device_token"]

        tasks = []
        for i in range(1, 51):
            tasks.append(
                ac.post("/api/stations/heartbeat", json={
                    "station_code": "ST-BENCH-50",
                    "device_token": st_token,
                    "audio_ready": True,
                    "client_ready": True
                })
            )

        start = time.perf_counter()
        responses = await asyncio.gather(*tasks)
        total_time_ms = (time.perf_counter() - start) * 1000

        print(f"\n[BENCHMARK] 50 concurrent heartbeats executed in: {total_time_ms:.2f} ms")

        for res in responses:
            assert res.status_code == 200
            assert res.json()["status"] == "ok"
