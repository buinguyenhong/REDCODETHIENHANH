"""Container launcher: migrate the schema, then run the application.

Cấu hình hoàn toàn bằng biến môi trường (``DATABASE_URL`` và các biến khác trong
``.env``). Không còn nhánh thiết lập database trong container: thiếu
``DATABASE_URL`` thì ``app/config.py`` báo lỗi rõ ràng thay vì mở một giao diện
cài đặt.
"""
import subprocess
import sys

subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True)
sys.exit(subprocess.call([
    sys.executable, '-m', 'uvicorn', 'app.main:app',
    '--host', '0.0.0.0', '--port', '8000', '--workers', '1', '--no-access-log',
]))
