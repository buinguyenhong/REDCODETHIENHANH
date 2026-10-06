"""Run manually after Alembic upgrade on an isolated database."""
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings


async def smoke():
    # Preserve demo seeding while disabling startup create_all: schema must
    # genuinely come from Alembic, not be silently repaired by test startup.
    settings.ENVIRONMENT = 'production'
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            login = await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123456'})
            assert login.status_code == 200, login.text
            headers = {'Authorization': f"Bearer {login.json()['access_token']}"}
            created = await client.post('/api/alarms', headers=headers, json={'alarm_type_id': 2, 'source_location': 'Migration smoke'})
            assert created.status_code == 201, created.text
            assert (await client.get('/api/reports/export-xlsx', headers=headers)).status_code == 200


if __name__ == '__main__':
    asyncio.run(smoke())
