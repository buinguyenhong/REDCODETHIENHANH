import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func

from app.main import app
from app.database import AsyncSessionLocal, engine, Base
from app.seed import seed_database
from app.models import Alarm, AlarmEvent, AlarmStationState, NotificationOutbox
from app.api.reports import parse_date_range
from app.core.n8n_outbox import outbox_worker
from app.config import settings


@pytest_asyncio.fixture(scope='module', autouse=True)
async def prepare_database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await seed_database()


@pytest.mark.asyncio
async def test_atomic_creation_failure_does_not_leave_alarm():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        login = await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123456'})
        key = str(uuid.uuid4())
        with patch('app.api.alarms.NotificationOutbox', side_effect=RuntimeError('injected before commit')):
            with pytest.raises(RuntimeError):
                await client.post('/api/alarms', headers={'Authorization': f"Bearer {login.json()['access_token']}"}, json={'alarm_type_id': 2, 'idempotency_key': key})
        async with AsyncSessionLocal() as session:
            assert (await session.execute(select(func.count(Alarm.id)).where(Alarm.idempotency_key == key))).scalar() == 0


@pytest.mark.asyncio
async def test_activation_cancel_and_history():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        login = await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123456'})
        headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
        code = 'REVIEW-' + uuid.uuid4().hex[:8]
        station = (await client.post('/api/stations/register', headers=headers, json={'station_code': code, 'name': 'Review receiver', 'receiver_group_ids': [1]})).json()
        credential = {'station_code': code, 'device_token': station['raw_device_token']}
        assert (await client.post('/api/stations/activate', json=credential)).status_code == 200
        alarm = (await client.post('/api/alarms', headers=headers, json={'alarm_type_id': 2})).json()
        with patch('app.api.stations.manager.send_to_station', new_callable=AsyncMock, return_value=True) as send:
            assert (await client.post(f"/api/alarms/{alarm['id']}/cancel", headers=headers)).status_code == 200
            assert any(call.args[0] == code and call.args[1]['type'] == 'ALARM_CANCELLED' for call in send.call_args_list)
        async with AsyncSessionLocal() as session:
            outbox = (await session.execute(select(NotificationOutbox).where(NotificationOutbox.alarm_id == alarm['id']))).scalars().all()
            assert len(outbox) == 1 and outbox[0].event_type == 'ALARM_CREATED'
        await client.delete(f"/api/stations/{station['id']}", headers=headers)
        async with AsyncSessionLocal() as session:
            assert (await session.execute(select(func.count(AlarmStationState.id)).where(AlarmStationState.station_id == station['id']))).scalar() > 0


def test_vietnam_day_boundaries():
    start, end = parse_date_range('2026-10-06', '2026-10-06')
    assert start == datetime(2026, 10, 5, 17, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 6, 16, 59, 59, 999999, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_outbox_recovers_abandoned_processing():
    async with AsyncSessionLocal() as session:
        item = NotificationOutbox(event_type='ALARM_CREATED', payload={}, status='PROCESSING', locked_at=datetime.now(timezone.utc) - timedelta(minutes=10), attempt_count=0)
        session.add(item)
        await session.commit()
        item_id = item.id
    old_url = settings.N8N_WEBHOOK_URL
    try:
        settings.N8N_WEBHOOK_URL = 'http://integration.invalid/webhook'
        with patch.object(outbox_worker, '_send_item', new_callable=AsyncMock) as send:
            await outbox_worker.process_outbox()
            async with AsyncSessionLocal() as session:
                recovered = await session.get(NotificationOutbox, item_id)
                # A recovered item may wait behind an older due batch (limit 20).
                assert recovered.status in {'FAILED', 'PROCESSING'}
                assert recovered.status != 'PROCESSING' or any(call.args[0] == item_id for call in send.call_args_list)
    finally:
        settings.N8N_WEBHOOK_URL = old_url
