import os
import sys
import json
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone

# Ensure backend path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.seed import seed_database
from app.models import (
    Station, Alarm, AlarmStationState, ReceiverGroup, ReceiverGroupStation
)
from app.core.websocket_manager import manager
from sqlalchemy import select


@pytest_asyncio.fixture(scope="module", autouse=True)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()


class MockLoadStationWebSocket:
    def __init__(self, code: str):
        self.code = code
        self.received_messages = []
        self.closed = False

    async def accept(self):
        pass

    async def send_text(self, text: str):
        self.received_messages.append(text)

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = True


@pytest.mark.asyncio
async def test_100_stations_connected_with_10_consecutive_alarms():
    """
    Section XIV Load Test:
    - 100 stations connected via WebSocket
    - 10 consecutive alarms triggered
    - Verifications:
      * No crash
      * Zero alarm loss
      * No duplicates per station
      * Monotonic unique server_sequences
      * Strict FIFO arrival order
      * 1000 successful deliveries
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        admin_res = await ac.post("/api/auth/login", json={"username": "admin", "password": "admin123456"})
        admin_token = admin_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. Create 100 stations in database and commit first
        async with AsyncSessionLocal() as session:
            rg_all = (await session.execute(select(ReceiverGroup).where(ReceiverGroup.code == "ALL_HOSPITAL"))).scalar_one()
            for i in range(1, 101):
                st_code = f"ST-LOAD-{i:03d}"
                st_obj = (await session.execute(select(Station).where(Station.station_code == st_code))).scalar_one_or_none()
                if not st_obj:
                    st_obj = Station(
                        station_code=st_code,
                        name=f"Load Station {i:03d}",
                        device_token_hash="hash",
                        enabled=True
                    )
                    session.add(st_obj)
                    await session.flush()
                    session.add(ReceiverGroupStation(receiver_group_id=rg_all.id, station_id=st_obj.id))
            await session.commit()

        # 2. Connect 100 active station sockets in WebSocket manager
        mock_sockets = {}
        for i in range(1, 101):
            st_code = f"ST-LOAD-{i:03d}"
            sock = MockLoadStationWebSocket(st_code)
            mock_sockets[st_code] = sock
            async with manager._lock:
                manager.active_stations[st_code] = sock

        assert len(manager.active_stations) >= 100

        # 3. Trigger 10 consecutive alarms
        alarm_ids = []
        server_sequences = []

        for j in range(1, 11):
            al_res = await ac.post("/api/alarms", headers=headers, json={
                "alarm_type_id": 2,  # RED_CODE_2 targets group 1 (ALL_HOSPITAL)
                "source_location": f"Load Testing Ward {j}",
                "note": f"Sequential load alarm {j}"
            })
            assert al_res.status_code == 201
            data = al_res.json()
            alarm_ids.append(data["id"])
            server_sequences.append(data["server_sequence"])

        # Wait a moment for background broadcast tasks to flush to all 100 sockets
        await asyncio.sleep(0.5)

        # 4. Assert server_sequences are strictly monotonic and unique
        assert len(server_sequences) == 10
        assert len(set(server_sequences)) == 10, "Duplicate sequence detected in load test!"
        assert sorted(server_sequences) == server_sequences, "Sequences not strictly monotonic!"

        # 5. Assert delivery across all 100 stations
        for st_code, sock in mock_sockets.items():
            received_alarms = []
            for raw_msg in sock.received_messages:
                try:
                    parsed = json.loads(raw_msg)
                    if parsed.get("type") == "ALARM_EVENT" and parsed.get("event") == "ALARM_TRIGGERED":
                        received_alarms.append(parsed["data"]["alarm_id"])
                except Exception:
                    pass

            # Each station must receive all 10 alarms
            assert len(received_alarms) == 10, f"Station {st_code} received {len(received_alarms)} alarms instead of 10!"

            # Strict FIFO order
            assert received_alarms == alarm_ids, f"Station {st_code} received alarms out of FIFO order!"

            # Zero duplicates
            assert len(set(received_alarms)) == 10, f"Station {st_code} has duplicate alarm deliveries!"

        # 6. Clean up mock sockets from manager
        for st_code, sock in mock_sockets.items():
            await manager.disconnect_station(st_code, sock)
