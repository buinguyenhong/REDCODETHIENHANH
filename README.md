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

### Cài ứng dụng trước, kết nối PostgreSQL sau

Docker hỗ trợ `DATABASE_URL=`: launcher mở giao diện thiết lập độc lập DB. Production vẫn cần `DEMO_MODE=false`, SECRET_KEY riêng và origin allowlist trong deployment env. Mở địa chỉ Redcode, IT lấy mã qua `docker compose exec backend cat /app/config/setup-token`, nhập PostgreSQL URL và mật khẩu Admin ≥12 ký tự. Kiểm tra → migrate → tạo Admin → ứng dụng tự chuyển sang chế độ chính. Runtime config được lưu mode 0600 trong volume `redcode_runtime_config`; backup bảo mật volume này. Không có PostgreSQL thì chưa vận hành alarm.

DB/network/user phải được IT chuẩn bị trước; wizard không tự cài PostgreSQL hoặc gắn external Docker network. Cấu hình DB đã có qua env vẫn dùng startup Alembic như trước. Bootstrap đóng sau hoàn tất, không phải công cụ đổi DB đang vận hành.

### Kết nối n8n sau

Admin → **CÀI ĐẶT TÍCH HỢP n8n** (`/admin/settings`) nhập webhook/timeout/retries, test rồi bật/lưu; không cần recreate backend. Khi tắt không tạo outbox cho alarm mới. Lần bật đầu không gửi backlog cũ trước `enabled_since`. Tắt tạm dừng worker; các job đủ điều kiện từ thời điểm đã bật lần đầu vẫn retry khi bật lại. Event test là `REDCODE_CONNECTION_TEST`, workflow cần phân biệt với alarm thật.

Migration mới `20261007_integrations` mặc định **tắt** n8n kể cả deployment có env webhook cũ. Sau upgrade, Admin cần cấu hình/bật lại; env N8N_* không còn source cấu hình runtime. Webhook lưu trong DB, chỉ Admin đọc/chỉnh; không chứa user/password trong URL và không ghi URL vào audit.

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

Suite có regression lifecycle, permission, date boundary, migration và `test_live_transport.py` chạy server Uvicorn/socket TCP thật trên DB riêng. Các benchmark cũ dùng mock không chứng minh tải LAN. `LIVE_TEST_DATABASE_URL` có thể chỉ định PostgreSQL **test riêng** cho live test; mặc định live test dùng SQLite tạm. Live test ACK mô phỏng protocol, không chứng minh loa/browser phát audio thật.

`.github/workflows/ci.yml` chạy backend pytest/migration, live transport trên PostgreSQL 16 test service, frontend test/build và Docker image build. Xem trạng thái run trên GitHub Actions; workflow không deploy production. Không có lint/typecheck script trong package hiện tại.

## Kiosk audio và trạng thái nghiệm thu

Browser thông thường có thể chặn autoplay khi chưa có tương tác. Windows kiosk có thể cấu hình launcher phù hợp, ví dụ:

```cmd
chrome.exe --kiosk "http://192.168.1.100/kiosk" --autoplay-policy=no-user-gesture-required
```

Android cần browser kiosk được cấu hình autoplay hoặc WebView `setMediaPlaybackRequiresUserGesture(false)`. Phải thử boot/refresh/reconnect, loa/mute/volume/sleep trên thiết bị thật; flag hoặc browser play thành công chưa chứng minh loa thực phát được.

Các finding còn PARTIAL/BLOCKED và acceptance chưa đủ bằng chứng được ghi trong changelog. Docker engine chưa chạy ở đợt kiểm chứng gần nhất; chưa nghiệm thu PostgreSQL/Nginx/container end-to-end, backup restore, tải mạng thật và PC/Android unattended audio.
