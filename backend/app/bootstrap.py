"""Database-independent first-install API. Never imported by the main app."""
import asyncio
import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

app = FastAPI(docs_url=None, redoc_url=None)
lock = asyncio.Lock()
config_path = Path(os.getenv('REDCODE_RUNTIME_CONFIG', '/app/config/runtime.json'))
token_path = config_path.parent / 'setup-token'


def setup_token():
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32), encoding='utf-8')
        token_path.chmod(0o600)
    return token_path.read_text(encoding='utf-8').strip()


def authorize(token):
    if config_path.exists():
        raise HTTPException(409, 'Thiết lập đã hoàn tất')
    if not token or not secrets.compare_digest(token, setup_token()):
        raise HTTPException(403, 'Mã thiết lập không hợp lệ')


class DatabaseSetup(BaseModel):
    database_url: str
    admin_password: str = Field(min_length=12, max_length=128)


async def probe(url):
    if not url.startswith('postgresql+asyncpg://'):
        raise HTTPException(422, 'Cần PostgreSQL URL postgresql+asyncpg://')
    engine = create_async_engine(url, pool_pre_ping=True, connect_args={'timeout': 10})
    try:
        async with engine.connect() as connection:
            await asyncio.wait_for(connection.execute(text('SELECT 1')), 10)
    except Exception:
        raise HTTPException(422, 'Không kết nối được PostgreSQL. Kiểm tra địa chỉ, network và quyền.')
    finally:
        await engine.dispose()


@app.get('/api/setup/status')
async def status():
    return {'configured': False, 'mode': 'database_setup'}


@app.get('/api/health')
async def health():
    return {'status': 'setup_required', 'database': 'not_configured'}


@app.post('/api/setup/test')
async def test(data: DatabaseSetup, x_setup_token: str = Header(default='')):
    authorize(x_setup_token)
    await probe(data.database_url)
    return {'status': 'connected'}


@app.post('/api/setup/complete')
async def complete(data: DatabaseSetup, x_setup_token: str = Header(default='')):
    async with lock:
        authorize(x_setup_token)
        await probe(data.database_url)
        secret = secrets.token_hex(32)
        env = dict(os.environ, DATABASE_URL=data.database_url, SECRET_KEY=secret,
                   INITIAL_ADMIN_PASSWORD=data.admin_password, ENVIRONMENT='production', DEMO_MODE='false')
        process = await asyncio.create_subprocess_exec(
            os.sys.executable, '-m', 'alembic', 'upgrade', 'head', env=env,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        if await process.wait() != 0:
            raise HTTPException(422, 'Migration thất bại. Kiểm tra schema/quyền DB trước khi thử lại; không dùng create_all.')
        # Bootstrap the admin before committing installer configuration.
        seed = await asyncio.create_subprocess_exec(os.sys.executable, '-c',
            'import asyncio; from app.seed import seed_database; asyncio.run(seed_database())',
            env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        if await seed.wait() != 0:
            raise HTTPException(422, 'Không khởi tạo được Admin. Kiểm tra DB trước khi thử lại.')
        temporary = config_path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'DATABASE_URL': data.database_url, 'SECRET_KEY': secret}), encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(config_path)
        token_path.unlink(missing_ok=True)
        asyncio.create_task(restart())
        return {'status': 'configured', 'message': 'Đang khởi động hệ thống. Đăng nhập Admin sau ít giây.'}


async def restart():
    await asyncio.sleep(2)
    os._exit(75)


@app.api_route('/api/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
async def unavailable(path: str):
    raise HTTPException(503, 'Chưa thiết lập database')
