"""Legacy suites exercise enabled integration; new tests explicitly check off."""
import pytest_asyncio
from datetime import datetime, timezone
from app.database import engine, Base, AsyncSessionLocal
from app.models import IntegrationSettings


@pytest_asyncio.fixture(scope='module', autouse=True)
async def integration_fixture():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        row = await session.get(IntegrationSettings, 1)
        if row is None:
            row = IntegrationSettings(id=1)
            session.add(row)
        row.enabled = True
        row.webhook_url = 'http://127.0.0.1:1/test-webhook'
        row.timeout_seconds = 1
        row.max_retries = 3
        row.enabled_since = datetime(2020, 1, 1, tzinfo=timezone.utc)
        await session.commit()
