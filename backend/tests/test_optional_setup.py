import uuid
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from app.main import app
from app.database import AsyncSessionLocal
from app.models import NotificationOutbox
from app.seed import seed_database


@pytest.mark.asyncio
async def test_disabled_then_enabled_only_new_alarms():
    await seed_database()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        token = (await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123456'})).json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        config = {'enabled': False, 'webhook_url': 'http://127.0.0.1:1/test', 'timeout_seconds': 1, 'max_retries': 3}
        assert (await client.put('/api/settings/n8n', headers=headers, json=config)).status_code == 200
        old = (await client.post('/api/alarms', headers=headers, json={'alarm_type_id': 2})).json()
        config['enabled'] = True
        assert (await client.put('/api/settings/n8n', headers=headers, json=config)).status_code == 200
        new = (await client.post('/api/alarms', headers=headers, json={'alarm_type_id': 2})).json()
        async with AsyncSessionLocal() as session:
            for alarm, count in [(old, 0), (new, 1)]:
                assert (await session.execute(select(func.count(NotificationOutbox.id)).where(NotificationOutbox.alarm_id == alarm['id']))).scalar() == count
        assert (await client.get('/api/settings/n8n')).status_code == 401


@pytest.mark.asyncio
async def test_first_enable_cutoff_prevents_legacy_backlog():
    from datetime import datetime, timezone
    from app.models import IntegrationSettings
    from app.core.n8n_outbox import outbox_worker
    async with AsyncSessionLocal() as session:
        integration = await session.get(IntegrationSettings, 1)
        integration.enabled = True
        integration.enabled_since = datetime.now(timezone.utc)
        legacy = NotificationOutbox(event_type='ALARM_CREATED', payload={}, status='PENDING', attempt_count=0,
                                    created_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
        session.add(legacy)
        await session.commit()
        item_id = legacy.id
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as post:
        await outbox_worker._send_item(item_id)
        post.assert_not_called()
    async with AsyncSessionLocal() as session:
        assert (await session.get(NotificationOutbox, item_id)).status == 'PENDING'


@pytest.mark.asyncio
async def test_bootstrap_auth_postgres_validation_and_closed_after_configuration(tmp_path):
    from app import bootstrap
    config = tmp_path / 'runtime.json'
    with patch.object(bootstrap, 'config_path', config), patch.object(bootstrap, 'token_path', tmp_path / 'setup-token'):
        token = bootstrap.setup_token()
        async with AsyncClient(transport=ASGITransport(app=bootstrap.app), base_url='http://test') as client:
            assert (await client.get('/api/setup/status')).json()['configured'] is False
            data = {'database_url': 'sqlite+aiosqlite:///tmp.db', 'admin_password': 'test-password-123'}
            assert (await client.post('/api/setup/test', json=data)).status_code == 403
            assert (await client.post('/api/setup/test', json=data, headers={'X-Setup-Token': token})).status_code == 422
            config.write_text('{}')
            assert (await client.post('/api/setup/test', json=data, headers={'X-Setup-Token': token})).status_code == 409
