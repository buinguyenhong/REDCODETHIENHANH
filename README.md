# REDCODE HOSPITAL — Hệ thống cảnh báo y tế khẩn cấp nội bộ

## Bệnh viện Đa khoa Thiện Hạnh

Hệ thống cảnh báo trên mạng LAN: **FastAPI + React/Vite + Nginx + PostgreSQL**, WebSocket realtime, âm thanh local và hàng đợi thông báo n8n độc lập.

## Tài liệu dự án

- [`project.md`](project.md): đặc tả hợp nhất, yêu cầu reliability và quyết định nghiệp vụ hiện hành. Mục 45–46 được ưu tiên khi xung đột với baseline.
- [`agent_changelog.md`](agent_changelog.md): lịch sử thay đổi, commit, kết quả kiểm thử và ma trận nghiệm thu.
- [`docs/testing_guide.md`](docs/testing_guide.md): regression commands, 13 nhóm kiểm thử LAN/browser/loa, ma trận acceptance và mẫu biên bản.
- [`docs/production_deployment.md`](docs/production_deployment.md): triển khai server thực, PostgreSQL/network/TLS, provisioning, backup/restore, upgrade/rollback và chẩn đoán vận hành.
- [`docs/production_deployment_flow.md`](docs/production_deployment_flow.md): sơ đồ dễ theo dõi, 12 bước triển khai chi tiết, luồng xác nhận trạm, nâng cấp và rollback.

## Luồng vận hành

### Cấu hình PostgreSQL bằng `DATABASE_URL`

PostgreSQL là bắt buộc ở production và do IT dựng sẵn trên container riêng. REDCODE chỉ kết nối tới đó: khai báo `DATABASE_URL` trong `.env` **một lần khi triển khai**, launcher chạy `alembic upgrade head` rồi khởi động API. Không có cơ chế thiết lập database trong ứng dụng — thiếu `DATABASE_URL` ở production thì `app/config.py` dừng ngay lúc khởi động với thông báo rõ ràng, thay vì mở một giao diện cài đặt.

DB/network/user do IT chuẩn bị trước. Alembic quản lý schema, migration forward-only.

### Cấu hình n8n bằng biến môi trường

n8n là **tích hợp bổ sung**, không thuộc đường báo động cốt lõi. Bật/tắt bằng `N8N_ENABLED` trong `.env`; cấu hình một lần khi triển khai, không có trang Admin quản lý kết nối. `N8N_ENABLED=true` mà thiếu `N8N_WEBHOOK_URL` là lỗi cấu hình và bị chặn lúc khởi động.

Khi tắt: hệ thống báo động nội bộ chạy bình thường và **không** tạo bản ghi chờ gửi nào, nên không có tồn đọng để phát lại về sau. Khi bật: mỗi báo động mới phát sinh đúng một bản ghi outbox; worker nền gửi kèm `Idempotency-Key` ổn định để workflow dedup, có retry/backoff và lease recovery. n8n chết không ảnh hưởng việc tạo, truyền hay phát báo động.

Chỉ gửi khi **phát sinh báo động** (loại, vị trí, ghi chú). Không gửi thông báo kết thúc báo động hay mất kết nối thiết bị qua n8n.

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
- Station ACK lifecycle: `PENDING → DELIVERED → DISPLAYED → AUDIO_STARTED → AUDIO_COMPLETED`; local `DISMISSED` terminal. `AUDIO_FAILED → FAILED` giữ lỗi; successful retry có thể `FAILED → AUDIO_STARTED`. ACK cũ/lặp không làm lùi state hoặc ghi audit lặp. Sync không giả received/display/audio ACK.
- Global lifecycle chỉ `ACTIVE → CANCELLED` hoặc `ACTIVE → EXPIRED`, không chuyển giữa hai terminal status. Cancel/expiry broadcast tới dashboard và target stations; không gửi n8n kết thúc.
- Permission chỉ lưu ở `department_alarm_permissions`. API `allowed_department_ids` là projection tương thích, không còn cột JSON. Migration `20261007_permissions` nhập legacy grants hợp lệ chỉ khi chưa có normalized grant/denial; normalized denial được giữ.
- Reports dùng khoảng half-open theo giờ bệnh viện: từ ngày đầu 00:00 đến **trước** 00:00 ngày sau ngày cuối, quy đổi UTC. Datetime không offset được hiểu theo Asia/Ho_Chi_Minh.
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
N8N_ENABLED=true
N8N_WEBHOOK_URL=http://n8n:5678/webhook/redcode
N8N_TIMEOUT_SECONDS=4
N8N_MAX_RETRIES=3
```

Fresh install cần `INITIAL_ADMIN_PASSWORD` để bootstrap Admin. Production không seed tài khoản/khoa demo; cấu hình nghiệp vụ từ Admin/API. `ALLOWED_ORIGINS` phải là allowlist cụ thể, không dùng `*`.

### 2. Kết nối PostgreSQL hiện có

Trong `docker-compose.yml`, bật `existing_postgres_network` ở networks của backend và khai báo external network phía cuối file với tên network PostgreSQL hiện có. `DATABASE_URL` phải dùng hostname/container alias truy cập được trên network đó. Compose không tạo PostgreSQL container mới.

`N8N_WEBHOOK_URL` mặc định là `http://n8n:5678/webhook/redcode` — hostname `n8n` chỉ phân giải được khi backend cùng Docker network với container n8n. Nếu n8n do IT dựng riêng, bật network tương ứng trong `docker-compose.yml` (xem mục networks ở cuối file); nếu không, mọi thông báo sẽ lỗi DNS, retry rồi cạn lượt (`EXHAUSTED`) trong khi báo động nội bộ vẫn chạy bình thường. Path `/webhook/redcode` phải khớp path của Webhook node trong workflow n8n — lệch path trả 404 và cũng bị tính là gửi thất bại.

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

Suite có regression lifecycle, permission, date boundary, migration và `test_live_transport.py` chạy server Uvicorn/socket TCP thật trên DB riêng. Các benchmark cũ dùng mock không chứng minh tải LAN. `LIVE_TEST_DATABASE_URL` có thể chỉ định PostgreSQL **test riêng** cho live test; mặc định live test dùng SQLite tạm. Live test ACK mô phỏng protocol, không chứng minh loa/browser phát audio thật.

`.github/workflows/ci.yml` chạy backend pytest/migration, live transport trên PostgreSQL 16 test service, frontend test/build và Docker image build. Xem trạng thái run trên GitHub Actions; workflow không deploy production. Không có lint/typecheck script trong package hiện tại.

## Kiosk audio và trạng thái nghiệm thu

Browser thông thường có thể chặn autoplay khi chưa có tương tác. Windows kiosk có thể cấu hình launcher phù hợp, ví dụ:

```cmd
chrome.exe --kiosk "http://192.168.1.100/kiosk" --autoplay-policy=no-user-gesture-required
```

Android cần browser kiosk được cấu hình autoplay hoặc WebView `setMediaPlaybackRequiresUserGesture(false)`. Phải thử boot/refresh/reconnect, loa/mute/volume/sleep trên thiết bị thật; flag hoặc browser play thành công chưa chứng minh loa thực phát được.

Các finding còn PARTIAL/BLOCKED và acceptance chưa đủ bằng chứng được ghi trong changelog. Docker engine chưa chạy ở đợt kiểm chứng gần nhất; chưa nghiệm thu PostgreSQL/Nginx/container end-to-end, backup restore, tải mạng thật và PC/Android unattended audio.
