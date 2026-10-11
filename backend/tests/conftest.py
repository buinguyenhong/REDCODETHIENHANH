"""Legacy suites exercise enabled integration; new tests explicitly check off.

n8n nay cấu hình bằng biến môi trường, nên fixture bật n8n bằng cách sửa
``settings`` thay vì ghi bảng ``integration_settings``. Các suite cũ vẫn giữ
nguyên hành vi: mặc định n8n được bật trong test để nhánh ghi outbox được chạy.
"""
import pytest_asyncio
from app.config import settings
from app.database import engine, Base

N8N_KEYS = ('N8N_ENABLED', 'N8N_WEBHOOK_URL', 'N8N_TIMEOUT_SECONDS', 'N8N_MAX_RETRIES')


@pytest_asyncio.fixture(scope='module', autouse=True)
async def integration_fixture():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    previous = {key: getattr(settings, key) for key in N8N_KEYS}
    settings.N8N_ENABLED = True
    settings.N8N_WEBHOOK_URL = 'http://127.0.0.1:1/test-webhook'
    settings.N8N_TIMEOUT_SECONDS = 1
    settings.N8N_MAX_RETRIES = 3
    yield
    for key, value in previous.items():
        setattr(settings, key, value)
