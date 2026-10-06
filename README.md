# REDCODE HOSPITAL — Hệ thống cảnh báo y tế khẩn cấp nội bộ

## Bệnh viện Đa khoa Thiện Hạnh

Hệ thống cảnh báo trên mạng LAN: **FastAPI + React/Vite + Nginx + PostgreSQL**, WebSocket realtime, âm thanh local và hàng đợi thông báo n8n độc lập.

## Tài liệu dự án

- [`project.md`](project.md): đặc tả hợp nhất, yêu cầu reliability và quyết định nghiệp vụ hiện hành. Mục 45–46 được ưu tiên khi xung đột với baseline.
- [`agent_changelog.md`](agent_changelog.md): lịch sử thay đổi, commit, kết quả kiểm thử và ma trận nghiệm thu.

## Luồng vận hành

1. **ADMIN** cấu hình khoa, quyền phát alarm, loại alarm, audio và nhóm nhận; quản trị báo cáo/XLSX.
2. Trên máy nhận, Admin đăng nhập, chọn trạm và **xác nhận thiết bị**. Hệ thống tự cấp/lưu credential nội bộ, không cần nhập hoặc copy token. Rotate credential thu hồi kết nối cũ.
3. Thiết bị đã xác nhận tự kết nối lại bằng identity đã lưu. Trạm có **TEST LOA**, **TEST HIỂN THỊ**, **TEST KẾT NỐI**; diagnostics bị khóa khi có alarm thật.
4. **OPERATOR** phát alarm theo quyền khoa và xem alarm log. Không có vai trò VIEWER; Operator không truy cập report/export.
5. Alarm định tuyến theo target snapshot, queue FIFO theo `server_sequence`. Dismiss chỉ dừng cảnh báo tại trạm đó; global cancel gửi tới các target và dashboard.
6. Loại alarm có `validity_seconds` mặc định **300**, range **10–86400**; alarm snapshot `expires_at`. Trạng thái toàn cục **ACTIVE / EXPIRED / CANCELLED**. Hết hạn hiển thị **CẢNH BÁO ĐÃ PHÁT**, dừng audio/overlay, giữ history; không gửi n8n kết thúc.
7. Máy vào sau hoặc reconnect nhận lại alarm thuộc target còn hiệu lực; alarm hết hạn, đã cancel hoặc local dismiss không phát lại.

## Kiến trúc và dữ liệu

- Nginx phục vụ React, audio local, proxy `/api` và `/ws` tới FastAPI.
- PostgreSQL lưu alarm, immutable target/station states, configuration, audit và `notification_outbox`; Alembic quản lý schema.
- Alarm/station states/CREATED audit/outbox được ghi trong một transaction. Idempotency chống trùng khi retry; API effective permissions kiểm tra quyền ở backend.
- Outbox có retry/backoff và lease recovery; n8n không nằm trong critical path của alarm.
- WebSocket manager còn in-memory: triển khai **một API worker**. Tải thực và crash/reconnect vẫn cần nghiệm thu.

## Triển khai Docker

### 1. Chuẩn bị cấu hình

Tạo `.env` dựa trên `.env.example`, thay bằng giá trị riêng của môi trường; không commit secret. Production yêu cầu:

```env
ENVIRONMENT=production
DEMO_MODE=false
INITIAL_ADMIN_PASSWORD=<mat-khau-admin-rieng>
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<postgres-host>:5432/<database>
SECRET_KEY=<secret-ngau-nhien-rieng-toi-thieu-32-ky-tu>
ALLOWED_ORIGINS=http://192.168.1.100
N8N_WEBHOOK_URL=http://<n8n-host>:5678/webhook/redcode/alarm
N8N_TIMEOUT_SECONDS=5
N8N_MAX_RETRIES=3
```

Fresh install cần `INITIAL_ADMIN_PASSWORD` để bootstrap Admin. Production không seed tài khoản/khoa demo; cấu hình nghiệp vụ từ Admin/API. `ALLOWED_ORIGINS` phải là allowlist cụ thể, không dùng `*`.

### 2. Kết nối PostgreSQL hiện có

Trong `docker-compose.yml`, bật `existing_postgres_network` ở networks của backend và khai báo external network phía cuối file với tên network PostgreSQL hiện có. `DATABASE_URL` phải dùng hostname/container alias truy cập được trên network đó. Compose không tạo PostgreSQL container mới.

Nếu dùng n8n qua hostname container, backend cũng phải truy cập được network tương ứng; có thể dùng địa chỉ LAN phù hợp.

### 3. Build và khởi chạy

```bash
docker compose build
docker compose up -d
```

Backend image tự chạy `alembic upgrade head` trước Uvicorn. Nginx image build frontend từ source, không cần `frontend/dist` sẵn. Volume `redcode_audio_data` giữ audio qua container restart. Mở địa chỉ máy chủ LAN ở port 80 theo Compose hiện tại.

### 4. Nâng cấp, backup và rollback

- Backup PostgreSQL bằng `pg_dump` và archive audio volume trước nâng cấp; kiểm chứng restore vào database test riêng.
- DB cũ từng tạo bằng `create_all` và chưa có `alembic_version` cần kiểm tra schema/adoption trên bản sao trước; không chạy initial create-tables migration trực tiếp lên DB có bảng.
- Migration runtime/validity là forward-only. Rollback bằng DB/audio backup đã kiểm chứng cùng image cũ tương ứng; không tự downgrade/drop history.
- Xem chi tiết và các giới hạn adoption/restore trong `agent_changelog.md`.

## Kiểm thử

Dùng **database test riêng**, không dùng DB dự án hoặc production cho test phá hủy. Ví dụ PowerShell tại root, với SQLite tạm ở thư mục đã tồn tại:

```powershell
$env:ENVIRONMENT = 'development'
$env:DEMO_MODE = 'true'
$env:DATABASE_URL = 'sqlite+aiosqlite:///C:/Users/Admin/AppData/Local/Temp/opencode/redcode-doc-tests.db'
# Chạy trong thư mục backend để import app và cấu hình test đúng.
Push-Location backend
try { ..\venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider } finally { Pop-Location }
```

Trong thư mục `frontend`:

```bash
npm test
npm run build
```

Kết quả gần nhất của đợt implementation: **35 backend tests passed**, **3 JS audio tests passed**, frontend build **PASS**. Test tải 50/100 hiện có dùng mock socket, không chứng minh acceptance WebSocket/LAN thật. Lịch sử commands và bằng chứng trong changelog; đợt hợp nhất tài liệu chỉ kiểm tra tài liệu/diff.

## Kiosk audio và trạng thái nghiệm thu

Browser thông thường có thể chặn autoplay khi chưa có tương tác. Windows kiosk có thể cấu hình launcher phù hợp, ví dụ:

```cmd
chrome.exe --kiosk "http://192.168.1.100/kiosk" --autoplay-policy=no-user-gesture-required
```

Android cần browser kiosk được cấu hình autoplay hoặc WebView `setMediaPlaybackRequiresUserGesture(false)`. Phải thử boot/refresh/reconnect, loa/mute/volume/sleep trên thiết bị thật; flag hoặc browser play thành công chưa chứng minh loa thực phát được.

Các finding còn PARTIAL/BLOCKED và acceptance chưa đủ bằng chứng được ghi trong changelog. Docker engine chưa chạy ở đợt kiểm chứng gần nhất; chưa nghiệm thu PostgreSQL/Nginx/container end-to-end, backup restore, tải mạng thật và PC/Android unattended audio.
