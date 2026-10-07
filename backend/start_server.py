"""Container launcher: setup first, then migrate and run the normal application."""
import os
import subprocess
import sys
from pathlib import Path

path = Path(os.getenv('REDCODE_RUNTIME_CONFIG', '/app/config/runtime.json'))
while True:
    configured = path.exists() or bool(os.getenv('DATABASE_URL', '').strip())
    if configured:
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True)
        module = 'app.main:app'
    else:
        from app.bootstrap import setup_token
        setup_token()
        print('Database setup required. Retrieve installation code from /app/config/setup-token inside backend container.', flush=True)
        module = 'app.bootstrap:app'
    code = subprocess.call([sys.executable, '-m', 'uvicorn', module, '--host', '0.0.0.0', '--port', '8000', '--workers', '1', '--no-access-log'])
    if code != 75:
        sys.exit(code)
