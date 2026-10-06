import uuid
from datetime import datetime, timezone, timedelta
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.main import app
from app.database import Base, engine, AsyncSessionLocal
from app.seed import seed_database
from app.models import Alarm, AlarmEvent


@pytest_asyncio.fixture(scope='module', autouse=True)
async def setup():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await seed_database()


@pytest.mark.asyncio
async def test_confirm_then_late_login_sync_and_expiry():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        token = (await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123456'})).json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        station = (await client.post('/api/stations/register', headers=headers, json={'station_code': 'VALID-' + uuid.uuid4().hex[:8], 'name': 'Validity test', 'department_id': 2, 'receiver_group_ids': [1]})).json()
        operator = (await client.post('/api/auth/login', json={'username': 'operator_cc', 'password': 'pass123456'})).json()['access_token']
        denied = await client.post(f"/api/stations/{station['id']}/confirm-device", headers={'Authorization': f'Bearer {operator}'})
        assert denied.status_code == 403
        assert (await client.get('/api/reports/summary', headers={'Authorization': f'Bearer {operator}'})).status_code == 403
        assert (await client.get('/api/reports/export-xlsx', headers={'Authorization': f'Bearer {operator}'})).status_code == 403
        assert (await client.get('/api/alarms', headers={'Authorization': f'Bearer {operator}'})).status_code == 200
        alarm = (await client.post('/api/alarms', headers=headers, json={'alarm_type_id': 2})).json()
        assert alarm['expires_at'] is not None
        confirmed = (await client.post(f"/api/stations/{station['id']}/confirm-device", headers=headers)).json()
        assert confirmed['raw_device_token'] != station['raw_device_token']
        credentials = {'X-Station-Token': confirmed['raw_device_token']}
        path = f"/api/stations/{station['station_code']}/active-alarms"
        assert (await client.get(path, headers={'X-Station-Token': station['raw_device_token']})).status_code == 401
        pending = (await client.get(path, headers=credentials)).json()
        assert any(item['alarm_id'] == alarm['id'] and item['audio_sequence'] for item in pending)
        async with AsyncSessionLocal() as session:
            stored = await session.get(Alarm, alarm['id'])
            stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()
        pending = (await client.get(path, headers=credentials)).json()
        assert all(item['alarm_id'] != alarm['id'] for item in pending)
        history = (await client.get(f"/api/alarms/{alarm['id']}", headers=headers)).json()
        assert history['status'] == 'EXPIRED'
        async with AsyncSessionLocal() as session:
            events = (await session.execute(select(AlarmEvent).where(AlarmEvent.alarm_id == alarm['id'], AlarmEvent.event_type == 'EXPIRED'))).scalars().all()
            assert len(events) == 1


@pytest.mark.asyncio
async def test_validity_setting_snapshotted():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        token = (await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123456'})).json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        created = await client.post('/api/alarm-types', headers=headers, json={'code': 'VALIDITY_' + uuid.uuid4().hex[:8], 'name': 'Validity', 'validity_seconds': 60})
        alarm_type = created.json()
        assert created.status_code == 201
        assert (await client.put(f"/api/alarm-types/{alarm_type['id']}", headers=headers, json={'validity_seconds': 0})).status_code == 422
        alarm = (await client.post('/api/alarms', headers=headers, json={'alarm_type_id': alarm_type['id']})).json()
        assert (datetime.fromisoformat(alarm['expires_at']) - datetime.fromisoformat(alarm['created_at'])).total_seconds() == 60
        await client.put(f"/api/alarm-types/{alarm_type['id']}", headers=headers, json={'validity_seconds': 120})
        history = (await client.get(f"/api/alarms/{alarm['id']}", headers=headers)).json()
        assert history['expires_at'] == alarm['expires_at']
        assert (await client.post('/api/users', headers=headers, json={'username': 'obsolete', 'display_name': 'Obsolete', 'password': 'example123', 'role': 'VIEWER'})).status_code == 422
