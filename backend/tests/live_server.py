"""Khởi động một ASGI server thật (uvicorn) cho các test cần WebSocket.

Vì sao không dùng ``fastapi.testclient.TestClient``: TestClient chạy app trong
event loop của một thread riêng (``anyio.from_thread.BlockingPortal``), trong
khi async engine gom connection vào loop của pytest. Với SQLite thì ``NullPool``
che được sự lệch loop này; với PostgreSQL pool thật thì không, và test hỏng với
``got Future attached to a different loop``.

Chạy trên uvicorn thật còn là bằng chứng đúng hơn cho hành vi từ chối
WebSocket: mã đóng 1008 so với HTTP 403 do chính ASGI server quyết định, nên
TestClient không thay thế được server thật ở điểm này.

Cách ly dữ liệu: server con dùng database riêng, lấy từ ``LIVE_TEST_DATABASE_URL``
nếu có (CI trỏ vào PostgreSQL), nếu không thì một file SQLite tạm. Nhờ vậy nó
không tranh khoá với tiến trình test và không sửa trạng thái DB dùng chung —
lúc khởi động app có đặt lại ``websocket_connected`` cho mọi trạm.
"""
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


async def shutdown(process: subprocess.Popen) -> None:
    """Dừng server, trên Windows phải diệt cả cây tiến trình.

    ``python.exe`` trong venv có thể sinh tiến trình con; chỉ terminate tiến
    trình cha sẽ để lại tiến trình con đang giữ cổng và handle database.
    """
    if process.poll() is not None:
        return
    if os.name == 'nt':
        await asyncio.to_thread(subprocess.run, ['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
    else:
        process.terminate()
    await asyncio.to_thread(process.wait, 10)


@asynccontextmanager
async def running_server(database_url: str):
    """Chạy uvicorn trên một database riêng; nhả cổng và tiến trình khi xong.

    ``database_url`` là URL mà tiến trình test đang dùng. Nếu là SQLite, helper
    tự chuyển sang file tạm để tránh hai tiến trình cùng ghi một file.
    """
    with tempfile.TemporaryDirectory() as temporary:
        url = database_url
        if url.startswith('sqlite'):
            url = 'sqlite+aiosqlite:///' + str(Path(temporary) / 'live.db').replace('\\', '/')
        env = os.environ.copy()
        env.update(
            ENVIRONMENT='test',
            DEMO_MODE='true',
            DATABASE_URL=url,
            AUDIO_UPLOAD_DIR=str(Path(temporary) / 'audio'),
            N8N_WEBHOOK_URL='http://127.0.0.1:1/unavailable',
        )
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True, capture_output=True)
        port = free_port()
        process = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port), '--no-access-log'],
            cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            async with httpx.AsyncClient() as client:
                for _ in range(150):
                    if process.poll() is not None:
                        raise AssertionError('Server thật thoát ngay khi khởi động')
                    try:
                        if (await client.get(f'http://127.0.0.1:{port}/api/health')).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.1)
                else:
                    raise AssertionError('Server thật không lên kịp')
            yield f'http://127.0.0.1:{port}', f'ws://127.0.0.1:{port}/ws'
        finally:
            await shutdown(process)
