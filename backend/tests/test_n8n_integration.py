"""n8n là tích hợp bổ sung, cấu hình bằng biến môi trường.

Các test ở đây khoá đúng hợp đồng mà định hướng yêu cầu:

- Tắt n8n thì hệ thống báo động nội bộ chạy bình thường và **không** tạo bản ghi
  chờ gửi nào (không có tồn đọng để phát lại sau này).
- Bật n8n thì mỗi báo động mới phát sinh đúng một bản ghi.
- n8n lỗi không được làm hỏng luồng tạo báo động.
- Bật mà thiếu webhook URL thì cấu hình bị từ chối ngay lúc khởi động.
"""
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from app.config import Settings, settings
from app.main import app
from app.database import AsyncSessionLocal
from app.models import NotificationOutbox
from app.core.n8n_outbox import outbox_worker
from app.seed import seed_database

N8N_KEYS = ('N8N_ENABLED', 'N8N_WEBHOOK_URL', 'N8N_TIMEOUT_SECONDS', 'N8N_MAX_RETRIES')


@pytest.fixture
def n8n_settings():
    """Đặt cấu hình n8n cho một test rồi trả nguyên trạng."""
    previous = {key: getattr(settings, key) for key in N8N_KEYS}
    yield settings
    for key, value in previous.items():
        setattr(settings, key, value)


async def outbox_count(alarm_id):
    async with AsyncSessionLocal() as session:
        return (await session.execute(
            select(func.count(NotificationOutbox.id)).where(NotificationOutbox.alarm_id == alarm_id)
        )).scalar()


async def create_alarm(alarm_type_id=2):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        token = (await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123456'})).json()['access_token']
        response = await client.post('/api/alarms', headers={'Authorization': f'Bearer {token}'}, json={'alarm_type_id': alarm_type_id})
        assert response.status_code in (200, 201), response.text
        return response.json()


@pytest.mark.asyncio
async def test_disabled_n8n_creates_no_outbox_row(n8n_settings):
    await seed_database()
    n8n_settings.N8N_ENABLED = False
    alarm = await create_alarm()
    assert await outbox_count(alarm['id']) == 0


@pytest.mark.asyncio
async def test_enabled_n8n_creates_exactly_one_outbox_row(n8n_settings):
    await seed_database()
    n8n_settings.N8N_ENABLED = True
    n8n_settings.N8N_WEBHOOK_URL = 'http://127.0.0.1:1/test'
    alarm = await create_alarm()
    assert await outbox_count(alarm['id']) == 1


@pytest.mark.asyncio
async def test_worker_sends_nothing_while_disabled(n8n_settings):
    """Tắt n8n thì worker nền không gọi webhook, dù có bản ghi PENDING cũ."""
    await seed_database()
    async with AsyncSessionLocal() as session:
        item = NotificationOutbox(event_type='ALARM_CREATED', payload={}, status='PENDING', attempt_count=0)
        session.add(item)
        await session.commit()
        item_id = item.id
    n8n_settings.N8N_ENABLED = False
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as post:
        await outbox_worker.process_outbox()
        await outbox_worker._send_item(item_id)
        post.assert_not_called()
    async with AsyncSessionLocal() as session:
        assert (await session.get(NotificationOutbox, item_id)).status == 'PENDING'


@pytest.mark.asyncio
async def test_worker_survives_webhook_failure(n8n_settings):
    """n8n chết không được làm worker nền sập; lỗi phải được ghi lại để thử lại."""
    await seed_database()
    async with AsyncSessionLocal() as session:
        item = NotificationOutbox(event_type='ALARM_CREATED', payload={}, status='PENDING', attempt_count=0)
        session.add(item)
        await session.commit()
        item_id = item.id
    n8n_settings.N8N_ENABLED = True
    n8n_settings.N8N_WEBHOOK_URL = 'http://127.0.0.1:1/test'
    n8n_settings.N8N_MAX_RETRIES = 3
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock, side_effect=RuntimeError('n8n down')):
        await outbox_worker._send_item(item_id)
    async with AsyncSessionLocal() as session:
        stored = await session.get(NotificationOutbox, item_id)
        assert stored.status == 'FAILED'
        assert stored.attempt_count == 1
        assert stored.next_attempt_at is not None
        assert 'n8n down' in stored.last_error


@pytest.mark.asyncio
async def test_health_reports_n8n_disabled(n8n_settings):
    n8n_settings.N8N_ENABLED = False
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        body = (await client.get('/api/health')).json()
    assert body['n8n'] == 'disabled'
    assert body['status'] == 'ok'


def test_enabled_without_webhook_url_is_rejected():
    """Bật n8n mà quên webhook URL là lỗi cấu hình, phải chặn lúc khởi động."""
    with pytest.raises(ValueError, match='N8N_ENABLED'):
        Settings(ENVIRONMENT='development', N8N_ENABLED=True, N8N_WEBHOOK_URL='')
