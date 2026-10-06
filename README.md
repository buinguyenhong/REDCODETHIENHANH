# REDCODE HOSPITAL — HỆ THỐNG CẢNH BÁO Y TẾ KHẨN CẤP NỘI BỘ
## Bệnh Viện Đa Khoa Thiện Hạnh (Spec V3 Implementation)

Hệ thống cảnh báo y tế khẩn cấp nội bộ (Redcode Hospital System) hoạt động độc lập 100% trên mạng nội bộ LAN của bệnh viện, tuân thủ nghiêm ngặt các tiêu chuẩn an toàn, tính bền vững giao dịch (idempotency), phân quyền theo khoa phòng, mô hình trạng thái trạm chi tiết (`alarm_station_states`) và hàng đợi gửi tin ngoại vi bền bỉ (`notification_outbox`).

---

## 1. Architecture (Kiến Trúc Tổng Thể)

Hệ thống giữ nguyên kiến trúc tiêu chuẩn: **FastAPI + React (Vite) + Nginx + PostgreSQL**, không phụ thuộc Redis, Kafka hay dịch vụ đám mây bên ngoài.

```text
[Màn hình Kiosk / PC Trạm nhận]          [Dashboard Điều hành / Bác sĩ]
         │ (Station Token Hash)                    │ (JWT Bearer Token)
         └──────────────────┬──────────────────────┘
                            │ (Port 80/443 HTTP & WSS)
                            ▼
                   [Nginx Reverse Proxy]
                     ├── /             -> React SPA (Production bundle)
                     ├── /assets/audio -> Static Tone & Còi báo động nội bộ
                     ├── /api/*        -> FastAPI REST API
                     └── /ws           -> FastAPI WebSocket Gateway
                            │
                            ▼
                  [FastAPI Core Server]
                     ├── WebSocket Gateway:
                     │     ├── /ws?type=dashboard&token=<JWT> (Auth user/role)
                     │     └── /ws?type=station&station_code=...&token=...
                     ├── ConnectionManager:
                     │     ├── Active sockets map (Race condition safe)
                     │     └── Heartbeat monitor (Offline threshold 15s)
                     ├── Atomic Sequence Engine:
                     │     └── nextval('alarm_server_sequence') (PostgreSQL)
                     └── Outbox Background Worker:
                           └── Polling notification_outbox -> n8n Webhook
                            │
                            ▼
              [PostgreSQL Database (redcode)]
```

---

## 2. Database Schema (Mô Hình Cơ Sở Dữ Liệu)

Cơ sở dữ liệu được quản lý bằng **Alembic Migrations** với các ràng buộc mức cơ sở dữ liệu:

1. **`alarms`**:
   - `id`: Khóa chính.
   - `alarm_code`: Định danh duy nhất (VD: `RC1-20261006-0001`).
   - `server_sequence`: Số thứ tự nguyên tăng dần tuyệt đối (**PostgreSQL Sequence `alarm_server_sequence`**).
   - `idempotency_key`: Chuỗi chống trùng lặp, **UNIQUE index mức DB**.
   - `status`: Chỉ nhận `ACTIVE` hoặc `CANCELLED` (đơn giản hóa trạng thái toàn cục).
2. **`alarm_station_states`**: Bảng quan hệ theo dõi chi tiết trạng thái báo động tại từng trạm:
   - `(alarm_id, station_id)`: **UNIQUE constraint**.
   - `state`: `PENDING`, `DELIVERED`, `DISPLAYED`, `AUDIO_STARTED`, `AUDIO_COMPLETED`, `DISMISSED`, `FAILED`.
   - Các mốc thời gian: `received_at`, `displayed_at`, `audio_started_at`, `audio_completed_at`, `dismissed_at`, `failed_at`.
   - `error_message`: Lưu thông tin lỗi âm thanh hoặc mạng nếu trạng thái là `FAILED`.
3. **`notification_outbox`**: Bảng hàng đợi ngoại vi bền bỉ:
   - `status`: `PENDING`, `PROCESSING`, `SENT`, `FAILED`.
   - `attempt_count`, `next_attempt_at`, `last_error`, `locked_at`.
4. **`department_alarm_permissions`**: Phân quyền quan hệ giữa Khoa/Phòng và Mã báo động:
   - `(department_id, alarm_type_id)`: **UNIQUE constraint**.
   - `enabled`: Cho phép hoặc chặn quyền kích hoạt mã.
5. **`stations`**:
   - `device_token_hash`: Lưu trữ giá trị băm cryptographic SHA-256 kèm salt bí mật, **không lưu token gốc**.
6. **`alarm_events` & `system_events`**: Audit log bất biến lưu lại toàn bộ lịch sử hành vi hệ thống.

---

## 3. Station Provisioning (Cấp Phát & Quản Lý Trạm)

- **Admin-only Provisioning**: Chỉ tài khoản có vai trò `ADMIN` mới được gọi `POST /api/stations/register` hoặc cập nhật cấu hình trạm. Operator và Viewer bị từ chối với mã lỗi `403 Forbidden`.
- **Cryptographically Secure Token**: Loại bỏ hoàn toàn quy tắc sinh token có thể dự đoán (như `station-token-{station_code}`). Token được sinh ngẫu nhiên an toàn bằng `secrets.token_urlsafe(32)`.
- **Hiển thị đúng một lần**: Server trả về `raw_device_token` một lần duy nhất lúc tạo trạm để người quản trị dán vào cấu hình máy kiosk. Database chỉ lưu trữ `device_token_hash`.
- Frontend Kiosk không tự sinh token fallback. Nếu thiếu token, trạm không được phép kết nối.

---

## 4. Authentication & Authorization (Xác Thực & Phân Quyền)

1. **Dashboard WebSocket (`/ws?type=dashboard&token=<JWT>`)**:
   - Bắt buộc truyền JWT token hợp lệ qua tham số query.
   - Server giải mã JWT, kiểm tra tài khoản tồn tại, trạng thái kích hoạt (`enabled=True`), và vai trò (`ADMIN`, `OPERATOR`, `VIEWER`).
   - Nếu token không hợp lệ hoặc thiếu: Ngắt kết nối ngay lập tức với mã `1008 Policy Violation`, không đưa vào danh sách quản lý.
2. **Station WebSocket (`/ws?type=station&station_code=...&token=...`)**:
   - Xác thực trạm dựa trên cặp `station_code` và `token`. Server băm token và so sánh trực tiếp với `device_token_hash` trong DB.
3. **Station Dismiss (`POST /api/stations/dismiss`)**:
   - Bắt buộc gửi kèm `device_token` của trạm.
   - Server kiểm tra: token hợp lệ + trạm đang hoạt động + trạm **thuộc nhóm nhận (receiver group)** của báo động đó. Trạm ngoài nhóm nhận hoặc sai token sẽ bị từ chối (`401`/`403`).
4. **Active Alarm Sync (`GET /api/stations/{station_code}/active-alarms`)**:
   - Bắt buộc header `X-Station-Token`. Trạm A không thể lấy dữ liệu của Trạm B.
5. **Anti-Spoofing Department**:
   - Khi `OPERATOR` tạo báo động, server luôn gắn `source_department_id = current_user.department_id`, bỏ qua giá trị `source_department_id` do client gửi lên.
   - Kiểm tra bảng `department_alarm_permissions`: Nếu khoa phòng bị vô hiệu hóa quyền với mã đó, trả về `403 Forbidden`.

---

## 5. Alarm Lifecycle (Vòng Đời Báo Động Toàn Cục)

- **Trạng thái toàn cục (Global Alarm Status)**: Chỉ có 2 trạng thái: `ACTIVE` và `CANCELLED`.
- **Local Dismiss độc lập**: Khi trạm bấm "Tắt cảnh báo tại đây" (Dismiss), chỉ có bản ghi `alarm_station_states.state` của trạm đó chuyển thành `DISMISSED` và ngừng phát âm thanh tại trạm đó. Báo động toàn cục (`alarms.status`) **vẫn giữ nguyên `ACTIVE`** và các trạm khác trong bệnh viện vẫn tiếp tục hú còi.
- **Hủy báo động toàn cục (Global Cancel)**: Chỉ Admin hoặc người có thẩm quyền mới được hủy toàn cục qua `POST /api/alarms/{id}/cancel`.
  - Trạng thái chuyển thành `CANCELLED`.
  - Phát sinh sự kiện riêng biệt `ALARM_CANCELLED` gửi qua WebSocket cho toàn bộ dashboard và client (tuyệt đối không dùng lại sự kiện `ALARM_TRIGGERED`).

---

## 6. Station Alarm State (Mô Hình Trạng Thái Trạm)

Mỗi trạm trong nhóm nhận được quản lý qua một bản ghi trong `alarm_station_states`:
- **`PENDING`**: Trạm đang offline khi có báo động phát sinh.
- **`DELIVERED`**: Báo động đã gửi tới socket trạm khi trạm đang online.
- **`DISPLAYED`**: Trạm đã mở popup/màn hình khẩn cấp.
- **`AUDIO_STARTED`**: File âm thanh bắt đầu phát ra loa.
- **`AUDIO_COMPLETED`**: Chu kỳ phát âm thanh đã hoàn tất.
- **`DISMISSED`**: Nhân viên y tế tại trạm đã bấm xác nhận tắt còi cục bộ.
- **`FAILED`**: Xảy ra lỗi phát âm thanh (ví dụ: browser autoplay restriction) hoặc lỗi mạng.

Khi trạm kết nối lại sau khi mất mạng, trạm gọi API đồng bộ để lấy các báo động đang ở trạng thái `PENDING` theo đúng thứ tự FIFO (`server_sequence`).

---

## 7. Durable n8n Notification Outbox (Gửi Tin Ngoại Vi Bền Vững)

- **Transaction Isolation**: Báo động và bản ghi outbox được tạo trong **cùng một giao dịch cơ sở dữ liệu**. Trigger còi báo động bệnh viện hoàn toàn không phụ thuộc vào trạng thái của n8n.
- **Non-blocking**: Nếu n8n bị sập, treo hoặc mất mạng, còi báo động toàn viện vẫn hoạt động bình thường 100%.
- **Durable Worker**: Một background worker định kỳ quét bảng `notification_outbox` với status `PENDING`/`FAILED`, gửi webhook sang n8n với timeout và số lần thử lại tối đa (`N8N_MAX_RETRIES`).
- **Exponential Backoff**: Khi gửi thất bại (HTTP 5xx hoặc Timeout), worker tăng `attempt_count`, lưu `last_error` và tính toán `next_attempt_at = now + 2^attempt`.
- **Khởi động lại không mất dữ liệu**: Vì lưu trong database, khi server khởi động lại, outbox worker tiếp tục xử lý các thông báo chưa gửi thành công.

---

## 8. WebSocket Reliability & Race Condition Fix

- **Disconnect Race Condition Fix**: Hàm `disconnect_station(station_code, websocket)` yêu cầu truyền cả instance `websocket`. Server chỉ gỡ bỏ trạm nếu socket đang ngắt kết nối chính là socket đang active hiện tại. Trường hợp Socket A ngắt kết nối sau khi Socket B đã kết nối lại sẽ không làm mất kết nối của Socket B.
- **FIFO Guarantee**: Danh sách báo động tại client và server được duy trì theo thứ tự hàng đợi FIFO dựa trên `server_sequence`.
- **Deduplication**: Client tự động đối soát `alarm_id` giữa luồng realtime broadcast và luồng active-alarm sync, đảm bảo không phát lặp âm thanh hoặc hiển thị 2 lần.

---

## 9. Audio Requirements & Unattended Operation (Vận Hành Kiosk Không Người Can Thiệp)

### Yêu cầu đặc tả:
1. Trạng thái `AUDIO_READY` chỉ được xác lập khi thiết bị đã thực sự kiểm tra hoặc phát thử thành công âm thanh ra loa.
2. Không nuốt lỗi phát âm thanh: Khi browser chặn âm thanh, client gửi ngay sự kiện `AUDIO_FAILED` về server để ghi audit log và đánh dấu `alarm_station_states.state = FAILED`.

### Giới hạn thực tế của Trình duyệt Web (Known Limitations):
> **QUAN TRỌNG**: Các trình duyệt hiện đại (Google Chrome, Microsoft Edge, Android WebView) áp dụng chính sách **Autoplay Policy** nghiêm ngặt. Trình duyệt mặc định chặn phát âm thanh tự động nếu trang web mở lên mà chưa có tương tác chạm/click của người dùng (*User Gesture*).

### Giải pháp kỹ thuật cho thiết bị Kiosk thực tế:

#### A. Thiết bị Windows Kiosk (PC màn hình trực ban):
Cấu hình khởi động trình duyệt Chrome/Edge bằng cờ dòng lệnh (flags) bỏ qua kiểm tra tương tác:
```cmd
chrome.exe --kiosk "http://192.168.1.100/kiosk" --autoplay-policy=no-user-gesture-required --disable-features=PreloadMediaEngagementData,MediaEngagementBypassAutoplayPolicies
```
Với cờ `--autoplay-policy=no-user-gesture-required`, Windows Kiosk khi bật nguồn tự mở Chrome và phát còi hú ngay lập tức khi có Redcode mà không cần ai chạm vào chuột/bàn phím.

#### B. Thiết bị Android Kiosk (Tablet treo tường):
1. **Sử dụng Fully Kiosk Browser** (hoặc Kiosk Launcher chuyên dụng):
   - Mở Fully Kiosk Browser Settings -> *Web Browsing* -> Bật `Enable Autoplay` và cấp quyền `Audio / Media`.
2. **Native Kiosk Wrapper (Android WebView)**:
   Nếu đóng gói ứng dụng native bằng WebView, thiết lập trong code Java/Kotlin:
   ```java
   webView.getSettings().setMediaPlaybackRequiresUserGesture(false);
   ```

---

## 10. Báo Cáo & Thống Kê (Reports)

1. **Bộ lọc khoảng ngày chính xác**:
   - Khi chọn `to_date = "YYYY-MM-DD"`, server tự động mở rộng mốc thời gian kết thúc đến `23:59:59.999999` của ngày đó. Không bị mất dữ liệu phát sinh trong ngày kết thúc.
2. **Bộ lọc sự kiện ngoại tuyến (Offline Events)**:
   - Các sự kiện mất kết nối thiết bị (`DEVICE_DISCONNECTED`), mất âm thanh được lọc theo cùng khoảng ngày báo cáo.
3. **Xuất Excel (XLSX)**:
   - File Excel chứa chi tiết từng ca báo động kèm tổng hợp trạng thái của từng trạm (`alarm_station_states`): Thời gian hiển thị, thời gian bắt đầu hú còi, thời gian hoàn thành, thời gian trạm tắt còi, và thông báo lỗi (nếu có).

---

## 11. Hướng Dẫn Triển Khai Production (Docker Compose)

### 1. File cấu hình môi trường (`.env`):
```env
ENVIRONMENT=production
DEMO_MODE=false
INITIAL_ADMIN_PASSWORD=MatKhauKhoiTaoAdminCucKyBaoMat2026!
DATABASE_URL=postgresql+asyncpg://postgres:matkhau_pg@postgres:5432/redcode
SECRET_KEY=khoa-bao-mat-redcode-thienhanh-32-ky-tu-tro-len
N8N_WEBHOOK_URL=http://n8n:5678/webhook/redcode/alarm
N8N_TIMEOUT_SECONDS=4
N8N_MAX_RETRIES=3
ALLOWED_ORIGINS=*
```

### 2. Khởi chạy hệ thống:
```bash
docker compose up -d --build
```

### 3. Thực hiện Alembic Migrations:
```bash
docker compose exec backend alembic upgrade head
```

---

## 12. Lệnh Kiểm Thử Toàn Diện (Test Commands)

Chạy toàn bộ 29 ca kiểm thử tự động (Unit, Integration, Security, State, Concurrency, Alembic, Load Test):

```powershell
# Chạy toàn bộ test suite
.\venv\Scripts\pytest -v

# Chạy riêng bộ kiểm thử toàn diện Spec V3
.\venv\Scripts\pytest -v backend/tests/test_spec_v3_all.py

# Chạy bài kiểm thử tải 100 trạm nhận kết nối đồng thời + 10 báo động liên tiếp
.\venv\Scripts\pytest -v backend/tests/test_100_stations_load.py

# Kiểm tra chu trình Alembic Migration (Upgrade -> Downgrade -> Upgrade)
.\venv\Scripts\pytest -v backend/tests/test_alembic_migrations.py

# Kiểm tra build giao diện frontend
cd frontend
npm run build
```

---

## 13. Danh Mục Trạng Thái & Giới Hạn Còn Tồn Tại (Known Limitations)

1. **Unattended Audio trên trình duyệt phổ thông**:
   - Như đã phân tích tại Mục 9, trình duyệt Chrome/Edge/Safari mặc định chặn âm thanh không tương tác. Bắt buộc phải khởi chạy với cờ `--autoplay-policy=no-user-gesture-required` trên Windows Kiosk hoặc cấu hình `setMediaPlaybackRequiresUserGesture(false)` trên Android Wrapper.
2. **Mạng LAN nội bộ không có Internet**:
   - n8n outbox worker sẽ tự động retry tối đa 3 lần với exponential backoff rồi dừng lại ở trạng thái `FAILED`. Báo động tại bệnh viện vẫn hoạt động bình thường và không bị ảnh hưởng.
3. **Database Dialect Sequence**:
   - Trên PostgreSQL (Production), hệ thống dùng native PostgreSQL Sequence `alarm_server_sequence`.
   - Trên SQLite (Test nội bộ), hệ thống tự động kích hoạt `SequenceGenerator` với mutex locking để đảm bảo tính duy nhất và tăng dần tuyệt đối.
