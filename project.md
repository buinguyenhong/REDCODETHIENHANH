# REDCODE HOSPITAL — PROJECT REQUIREMENTS

**Version:** 2.0 — consolidated 2026-10-06

**Status:** Source of truth for requirements; implementation acceptance is tracked separately.

**Target repository:** `buinguyenhong/REDCODETHIENHANH`
**Purpose:** Đặc tả duy nhất của dự án. Hợp nhất baseline (hai file spec cũ có nội dung giống nhau), yêu cầu sửa lỗi sau review và các quyết định mới của người dùng. Lịch sử thực thi/bằng chứng kiểm thử nằm trong `agent_changelog.md`.

## Cách sử dụng và thứ tự ưu tiên

- Mục 45 quy định yêu cầu reliability bổ sung; mục 46 ghi các quyết định mới về role, xác nhận thiết bị và thời hạn alarm. Các mục này thay thế nội dung baseline nếu có xung đột.
- README chỉ hướng dẫn sử dụng/chạy dự án, không tự thay đổi nghiệp vụ.
- Agent phải đọc tài liệu này trước khi sửa, cập nhật `agent_changelog.md` sau mỗi đợt, ghi rõ FIXED/PARTIAL/BLOCKED và bằng chứng thực chạy.
- Không đồng nhất yêu cầu với chức năng đã được nghiệm thu; test mock/build không thay thế kiểm thử mạng/browser/loa thực.

---

## 1. Mục tiêu

Xây dựng hệ thống Redcode nội bộ bệnh viện có độ ổn định cao, hoạt động lâu dài trên LAN, phục vụ khoảng 50 thiết bị và có khả năng mở rộng khoảng 100 thiết bị.

Hệ thống phải tập trung vào:

1. Phát cảnh báo realtime.
2. Phát âm thanh tại đúng các thiết bị được cấu hình.
3. Hiển thị cảnh báo trực quan, nghiêm trọng và không thể nhầm lẫn.
4. Theo dõi kết nối của từng client.
5. Ghi log/audit đầy đủ, không giới hạn thời gian lưu.
6. Báo cáo và xuất file.
7. Gửi thông tin Redcode sang n8n.
8. Hoạt động độc lập với Internet và n8n.
9. Tự phục hồi kết nối/client khi có sự cố.
10. Kiến trúc tinh gọn, không thêm thành phần không cần thiết.

### Không làm trong phiên bản này

Không triển khai:

- Redis
- RabbitMQ
- Kafka
- Kubernetes
- Microservices
- Supabase
- Cloud database/storage
- Native Android application nếu browser/kiosk đáp ứng được
- AI/chatbot
- Các tính năng nghiệp vụ ngoài Redcode
- Thông báo kết thúc Redcode qua Mattermost/Telegram/Zalo

---

# 2. Kiến trúc bắt buộc

```text
                         INTERNET
                            |
                    Integration Server
                         Docker
                           |
                          n8n
                           ^
                           |
                      HTTP Webhook
                           |
========================================================
                    HOSPITAL INTERNAL LAN
                           |
                    +---------------+
                    | REDCODE SERVER|
                    | Ubuntu Docker |
                    +---------------+
                      |      |     |
                    Nginx  FastAPI  |
                           |        |
                      WebSocket     |
                           |        |
                     PostgreSQL ----+
                     existing container
                     database: redcode
                           |
             +-------------+-------------+
             |             |             |
            PC            PC          Android
         receiver       receiver       kiosk
             |             |             |
          speaker       speaker       speaker
```

## 2.1 PostgreSQL

PostgreSQL đã tồn tại trên một container riêng.

**Không tạo PostgreSQL container mới.**

Chỉ tạo database riêng:

```text
redcode
```

FastAPI kết nối đến database này.

Client không được phép truy cập PostgreSQL trực tiếp.

## 2.2 Core services

Production chỉ cần:

- Nginx
- FastAPI
- React build
- PostgreSQL container hiện có

Nginx là entry point duy nhất cho client.

Routing:

```text
/        -> React static files
/api/*   -> FastAPI HTTP
/ws      -> FastAPI WebSocket
/assets  -> local static assets/audio
```

---

# 3. Nguyên tắc vận hành quan trọng nhất

## 3.1 Redcode core không phụ thuộc n8n

Luồng đúng:

```text
Client
  |
  v
Redcode Server
  |
  +--> PostgreSQL
  |
  +--> WebSocket --> receivers
  |
  +--> n8n       --> chat channels
```

Không được:

```text
Client -> n8n -> Redcode
```

Không được chờ n8n trả kết quả trước khi phát cảnh báo.

Nếu n8n chết:

- Redcode vẫn phát cảnh báo.
- Audio vẫn hoạt động.
- WebSocket vẫn hoạt động.
- Log vẫn được ghi.
- Chỉ integration notification bị lỗi/retry.

## 3.2 Internet không phải dependency của Redcode

Client không cần Internet.

Redcode server cũng không cần Internet để thực hiện nghiệp vụ cảnh báo.

---

# 4. Công nghệ

## Frontend

- React
- Vite
- React Router
- WebSocket native/browser
- XLSX export
- Lucide hoặc icon library nhẹ nếu cần

Có thể tái sử dụng phần UI/business concept của repo hiện tại nhưng phải refactor khỏi Supabase.

## Backend

- Python
- FastAPI
- Uvicorn
- SQLAlchemy 2.x hoặc SQLModel
- Pydantic
- JWT hoặc session/token phù hợp
- Password hashing bằng Argon2 hoặc bcrypt

## Database

- PostgreSQL hiện có

## Reverse proxy

- Nginx

## Deployment

- Docker Compose cho Redcode API + Nginx
- PostgreSQL dùng container/network hiện có

---

# 5. Authentication và Authorization

## 5.1 User

User thuộc một khoa/phòng ban.

Không quản lý nhân viên/HIS trong phiên bản này.

```text
User
  |
  +-- Department
  |
  +-- Role
  |
  +-- Permissions
```

Roles tối thiểu:

- `ADMIN`
- `OPERATOR`

Không tạo hoặc cho đăng nhập VIEWER. Tài khoản VIEWER cũ bị vô hiệu hóa, giữ lịch sử.

## 5.2 Quyền phát Redcode

Quyền phụ thuộc user/khoa.

Ví dụ:

```text
Cấp cứu
  RED_CODE_1 = allowed
  RED_CODE_2 = allowed
  BLUE_CODE  = denied
```

Không hard-code permission trong React.

## 5.3 Receiver station

Các máy cố định không cần đăng nhập thủ công mỗi ngày.

Mỗi station có:

- station_id
- station_name
- department
- location
- IP
- receiver_group
- device token/activation token

Device credential là chi tiết kỹ thuật nội bộ. Admin đăng nhập trên máy nhận, chọn trạm và xác nhận thiết bị; hệ thống tự cấp/lưu credential. Không hiển thị form nhập/copy token thủ công. Sau khi xác nhận, station tự kết nối.

---

# 6. Alarm types

Alarm type phải là dữ liệu cấu hình, không hard-code.

Ví dụ mặc định:

```text
RED_CODE_1
RED_CODE_2
BLUE_CODE
FIRE_ALARM
```

Admin có thể:

- tạo
- sửa
- bật/tắt
- sắp xếp
- cấu hình màu
- cấu hình âm thanh
- cấu hình receiver group
- cấu hình permission

Mỗi alarm type tối thiểu có:

```text
id
code
name
description
enabled
display_color
priority
audio_sequence
repeat_count
repeat_interval_ms
validity_seconds
```

---

# 7. Receiver groups

Không gán từng station thủ công cho từng alarm nếu có thể tránh.

Tạo:

```text
receiver_groups
```

Ví dụ:

```text
RED_CODE_1_GROUP
RED_CODE_2_GROUP
BLUE_CODE_GROUP
FIRE_ALARM_GROUP
```

Một group có nhiều station.

Một station có thể thuộc nhiều group.

Quan hệ:

```text
receiver_groups
receiver_group_stations
```

Alarm type trỏ đến receiver group.

Điều này giúp mở rộng từ 50 lên 100+ thiết bị mà không phải sửa logic.

---

# 8. Alarm lifecycle

Không sử dụng lẫn các status như `active`, `Đang báo động`, `resolved`.

Machine status phải thống nhất bằng enum.

Đề xuất:

```text
CREATED
ACTIVE
DISPLAY_COMPLETED
EXPIRED
CANCELLED
```

### CREATED

Alarm vừa được tạo và ghi database.

### ACTIVE

Alarm đang được broadcast/hiển thị/phát âm thanh.

### DISPLAY_COMPLETED

Các receiver đã hoàn tất trạng thái hiển thị hoặc người dùng đã tắt cảnh báo tại station.

### CANCELLED

Chỉ dùng khi alarm được tạo nhầm và có quyền hủy.

### EXPIRED

Thời hạn phát cảnh báo đã hết; UI hiển thị **CẢNH BÁO ĐÃ PHÁT**. Hết hạn dừng visual/audio, không xóa lịch sử và không gửi n8n event kết thúc. Yêu cầu hiện tại dùng ACTIVE/EXPIRED/CANCELLED cho global status; presentation state theo từng trạm, không cần workflow hoàn thành sự cố.

Không cần workflow "xử lý công việc" hoặc "hoàn thành sự cố".

**V1 không gửi thông báo kết thúc alarm qua n8n.**

---

# 9. Local dismiss và global alarm

Dismiss tại một client là **local action**.

Ví dụ:

```text
Alarm #1001
  |
  +-- RC-001 -> dismissed
  +-- RC-002 -> active
  +-- RC-003 -> dismissed
```

Không được để RC-001 dismiss làm biến mất cảnh báo trên RC-002.

Mỗi station phải có delivery/presentation state riêng.

Global alarm record vẫn được giữ để audit.

---

# 10. FIFO và nhiều alarm đồng thời

Nếu nhiều alarm đến liên tiếp:

```text
10:00:00 RED_CODE_1
10:00:03 BLUE_CODE
10:00:05 RED_CODE_2
```

Phải xử lý theo thứ tự tạo:

```text
RED_CODE_1
    ->
BLUE_CODE
    ->
RED_CODE_2
```

Không được mất alarm.

Mỗi alarm có timestamp/server sequence để đảm bảo ordering.

Không dùng client clock để quyết định thứ tự.

---

# 11. Alarm creation flow

```text
User
 |
 | POST /api/alarms
 v
FastAPI
 |
 +-- authenticate
 |
 +-- authorize
 |
 +-- validate alarm type
 |
 +-- determine receiver group
 |
 +-- create alarm
 |
 +-- create CREATED event
 |
 +-- broadcast WebSocket
 |
 +-- enqueue/send n8n notification
 |
 v
Response
```

n8n không nằm trong critical path.

---

# 12. WebSocket

WebSocket là cơ chế realtime chính.

Client giữ kết nối:

```text
/ws
```

Server phải hỗ trợ:

- connect
- authentication
- station identification
- heartbeat
- reconnect
- alarm event
- system status
- acknowledgement/dismiss event
- connection state

## 12.1 Reconnect

Client phải tự reconnect khi:

- server restart
- mạng mất
- WebSocket bị đóng
- browser reconnect
- VLAN/network transient failure

Backoff tăng dần, có giới hạn.

Sau reconnect:

```text
connect
  ->
authenticate
  ->
send station status
  ->
query active/recent state
  ->
synchronize missed state
```

WebSocket không phải source of truth.

PostgreSQL mới là source of truth.

---

# 13. Heartbeat và device monitoring

Mỗi station heartbeat khoảng:

```text
5 seconds
```

Server đánh dấu offline nếu vượt ngưỡng cấu hình, mặc định khoảng:

```text
15 seconds
```

Có thể cấu hình.

Theo dõi tối thiểu:

```text
station
IP
last_seen
websocket_connected
audio_ready
browser/client_ready
status
```

Không cần theo dõi CPU/RAM/client process ở V1.

---

# 14. Client offline behavior

Khi client mất kết nối:

1. Server ghi `DEVICE_DISCONNECTED`.
2. Dashboard Admin hiển thị OFFLINE.
3. Khi client tự kết nối lại:
   - ghi `DEVICE_CONNECTED`
   - cập nhật last_seen
   - đồng bộ trạng thái
4. Client hiển thị trạng thái mất kết nối.
5. Không gửi thông báo mất client qua Mattermost/Telegram/Zalo.

Client phải tự reconnect.

---

# 15. Audio

Audio phải nằm trên Redcode Server/local LAN.

Không phụ thuộc:

- Internet
- CDN
- Supabase Storage
- Google Drive
- cloud storage

Ví dụ:

```text
/assets/audio/
  red-code-1/
  red-code-2/
  blue-code/
  fire-alarm/
```

Audio sequence phải cấu hình được.

Ví dụ:

```text
RED CODE 1
  1. red_code_1.mp3
  2. cap_cuu.mp3
  3. location.mp3
```

Có cấu hình:

- sequence
- repeat count
- interval
- enabled/disabled

---

# 16. Audio readiness

Station phải có trạng thái:

```text
AUDIO_READY
AUDIO_NOT_READY
UNKNOWN
```

Admin phải nhìn được trạng thái này.

Nếu browser policy không cho autoplay audio khi chưa có user interaction, coding agent **không được giả định rằng browser luôn hoạt động**.

Phải có cơ chế test audio readiness.

Nếu browser thuần không đáp ứng được yêu cầu unattended audio ổn định trên Android thực tế, phải báo cáo rõ limitation trước khi chọn native/wrapper solution.

Không tự ý đưa native Android vào V1 nếu chưa có bằng chứng cần thiết.

---

# 17. Alarm UI

UI phải tuân thủ nguyên tắc:

> NORMAL = yên tĩnh, tinh gọn.  
> ALARM = rõ ràng, mạnh, không thể nhầm lẫn.

## Không sử dụng các phong cách phổ biến của AI

Tránh:

- gradient tím/xanh
- glassmorphism
- dashboard SaaS generic
- quá nhiều rounded cards
- excessive shadows
- neon/futuristic AI
- card layout dày đặc
- sidebar quá lớn
- icon trong vòng tròn chỉ để trang trí
- quá nhiều chart

## Visual direction

Phong cách:

**Clinical Control Interface**

Đặc điểm:

- typography rõ
- ít màu
- khoảng trắng có chủ đích
- đường phân cách tinh tế
- bố cục giống control system
- thông tin phân cấp mạnh
- không trang trí dư thừa

---

# 18. Alarm popup

Không dùng modal nhỏ thông thường.

Khi alarm xảy ra, client chuyển sang **Alarm State**.

Phải hiển thị nổi bật:

```text
RED CODE 1

CẤP CỨU

KHU CẤP CỨU
PHÒNG 03

[GHI CHÚ nếu có]

[TẮT CẢNH BÁO]
```

Màu cảnh báo phải thể hiện rõ mức độ nghiêm trọng.

Không dùng màu nhạt/pastel.

Không để người dùng phải đọc nhiều để hiểu cảnh báo.

---

# 19. Animation

Animation được phép nhưng phải có mục đích.

Được phép:

- alarm entrance
- subtle pulse
- connection state transition
- state change

Không dùng animation liên tục gây mỏi mắt hoặc làm giảm khả năng đọc.

Âm thanh và visual alarm phải được kích hoạt gần như đồng thời.

---

# 20. Sau khi dismiss

Khi người dùng tắt cảnh báo:

- popup biến mất
- audio dừng
- trạng thái cảnh báo trên client trở về bình thường
- alarm vẫn còn trong log
- recent alarm vẫn hiển thị trên dashboard

Không xóa record.

---

# 21. Dashboard

Dashboard người dùng thường phải rất đơn giản.

Có:

1. Nút phát Redcode được phép.
2. Active/recent alerts.
3. Trạng thái kết nối.
4. Thông tin station/user.

Không tạo quá nhiều card thống kê.

---

# 22. Admin dashboard

Admin cần:

### System status

```text
Redcode Core
Database
WebSocket
n8n Integration
```

### Device status

```text
Online
Offline
Audio Ready
Last Seen
```

### Recent events

Các event mới nhất.

### Configuration

- Departments
- Users
- Alarm types
- Receiver groups
- Stations
- Audio
- n8n integration

---

# 23. Reporting

Reporting và xuất XLSX chỉ dành cho ADMIN. OPERATOR xem alarm log trên dashboard, không truy cập API/UI reports hoặc export.

V1 chỉ cần:

### Tổng quan

- tổng alarm
- alarm theo ngày
- alarm theo tháng
- alarm theo loại
- alarm theo khoa
- average acknowledgement/presentation time nếu dữ liệu đủ
- số lần station offline
- tổng thời gian offline nếu dữ liệu đủ

### Export

Bắt buộc hỗ trợ:

```text
XLSX
```

PDF không bắt buộc ở V1.

Không xây dựng BI/Grafana riêng.

---

# 24. Database schema

Database tối thiểu:

```text
departments
users
stations
alarm_types
receiver_groups
receiver_group_stations
alarms
alarm_events
system_events
audio_files
```

## departments

```text
id
code
name
enabled
created_at
updated_at
```

## users

```text
id
username
password_hash
display_name
department_id
role
enabled
created_at
updated_at
last_login_at
```

## stations

```text
id
station_code
name
department_id
location
ip_address
device_token_hash
enabled
last_seen_at
websocket_connected
audio_ready
client_ready
status
created_at
updated_at
```

## alarm_types

```text
id
code
name
description
enabled
priority
display_color
receiver_group_id
repeat_count
repeat_interval_ms
created_at
updated_at
```

## receiver_groups

```text
id
code
name
description
enabled
created_at
updated_at
```

## receiver_group_stations

```text
receiver_group_id
station_id
```

Unique composite key.

## alarms

```text
id
alarm_type_id
created_by_user_id
source_department_id
source_location
note
status
created_at
activated_at
display_completed_at
cancelled_at
server_sequence
```

## alarm_events

```text
id
alarm_id
station_id nullable
event_type
event_time
metadata jsonb
created_at
```

Event examples:

```text
CREATED
BROADCAST
RECEIVED
DISPLAYED
AUDIO_STARTED
AUDIO_COMPLETED
DISMISSED
CANCELLED
```

## system_events

```text
id
station_id nullable
event_type
severity
message
metadata jsonb
created_at
```

Examples:

```text
DEVICE_CONNECTED
DEVICE_DISCONNECTED
WEBSOCKET_CONNECTED
WEBSOCKET_DISCONNECTED
AUDIO_READY
AUDIO_NOT_READY
N8N_REQUEST_SUCCESS
N8N_REQUEST_FAILED
AUTH_FAILED
SERVER_ERROR
DATABASE_ERROR
```

## audio_files

```text
id
code
name
file_path
mime_type
enabled
created_at
updated_at
```

Do not store large audio binary in PostgreSQL unless there is a compelling reason. Store files on local persistent storage and metadata in PostgreSQL.

---

# 25. Audit requirements

Every critical action must be traceable.

At minimum:

- login
- failed login
- alarm created
- alarm broadcast
- station received
- audio started
- audio completed
- dismiss
- cancel
- device connect
- device disconnect
- configuration change
- n8n success/failure
- server/database/system error

Logs are retained indefinitely.

---

# 26. API baseline

Suggested endpoints:

```text
POST   /api/auth/login
POST   /api/auth/logout
GET    /api/auth/me

GET    /api/dashboard
GET    /api/system/status

POST   /api/alarms
GET    /api/alarms
GET    /api/alarms/{id}
POST   /api/alarms/{id}/cancel

POST   /api/stations/register
POST   /api/stations/heartbeat
GET    /api/stations
GET    /api/stations/{id}

POST   /api/stations/{id}/dismiss
POST   /api/stations/{id}/audio-test

GET    /api/alarm-types
POST   /api/alarm-types
PUT    /api/alarm-types/{id}
DELETE /api/alarm-types/{id}

GET    /api/receiver-groups
POST   /api/receiver-groups
PUT    /api/receiver-groups/{id}

GET    /api/departments
POST   /api/departments
PUT    /api/departments/{id}

GET    /api/users
POST   /api/users
PUT    /api/users/{id}

GET    /api/reports/alarms
GET    /api/reports/devices

GET    /api/audio
POST   /api/audio
DELETE /api/audio/{id}

GET    /api/health
GET    /api/health/db
GET    /api/health/websocket

WS     /ws
```

Coding agent có thể điều chỉnh endpoint naming nhưng không được phá vỡ các nguyên tắc nghiệp vụ.

---

# 27. n8n webhook

Redcode server gọi một webhook riêng cho Redcode.

Ví dụ:

```text
POST /webhook/redcode/alarm
```

Payload:

```json
{
  "event": "RED_CODE_CREATED",
  "alarm_id": 1258,
  "alarm_type": "RED_CODE_1",
  "alarm_name": "RED CODE 1",
  "department": "Cấp cứu",
  "location": "Khu cấp cứu",
  "note": "Phòng 03",
  "created_at": "2026-10-05T10:30:15+07:00"
}
```

Không gửi event kết thúc alarm.

n8n tự quyết định:

- Mattermost channel
- Telegram
- Zalo
- routing
- format

Redcode không hard-code channel ID.

---

# 28. n8n retry

n8n request phải có:

- timeout
- retry
- logging

Nếu n8n unavailable:

```text
N8N_REQUEST_FAILED
```

nhưng alarm core vẫn hoàn thành bình thường.

Không để n8n block WebSocket/alarm creation.

---

# 29. Security

Bắt buộc:

- PostgreSQL không expose cho client.
- Secret/password không commit Git.
- `.env` không commit.
- Device token phải được hash hoặc bảo vệ phù hợp.
- Password hash Argon2/bcrypt.
- API authorization ở backend.
- Không tin permission từ frontend.
- CORS chỉ cho origin nội bộ cần thiết.
- Input validation bằng Pydantic.
- SQL injection phải được ngăn chặn bằng ORM/parameterized query.
- Không log password/token.

---

# 30. Docker

Cần cung cấp:

```text
docker-compose.yml
.env.example
Dockerfile
nginx/
```

Compose không được tự tạo PostgreSQL mới.

FastAPI container phải connect được tới PostgreSQL network hiện có.

Nếu PostgreSQL ở Docker network khác, document rõ cách connect:

- external Docker network, hoặc
- hostname/IP của PostgreSQL container/service.

Không hard-code IP production.

---

# 31. Persistent data

Phải bảo đảm persistent:

```text
PostgreSQL
Audio
Uploaded/configured assets
```

Container restart không được làm mất dữ liệu.

---

# 32. Health check

FastAPI phải có:

```text
GET /api/health
```

trả trạng thái tổng quát.

Ví dụ:

```json
{
  "status": "ok",
  "database": "ok",
  "websocket": "ok",
  "n8n": "ok"
}
```

N8n down không làm `status` core thành failed nếu database/API/WebSocket vẫn hoạt động; có thể biểu diễn n8n là degraded.

---

# 33. Error handling

Frontend phải có xử lý:

- API timeout
- WebSocket disconnect
- reconnect
- duplicate alarm event
- stale event
- authentication expiration
- server restart

Backend phải có:

- structured logging
- exception handling
- transaction rollback
- validation
- database connection recovery

---

# 34. Idempotency và duplicate protection

Alarm creation phải tránh duplicate do double-click hoặc network retry.

Nút phát alarm phải:

- disable rất ngắn trong lúc request
- có request id/idempotency key nếu cần

Backend phải đảm bảo một request retry không tạo nhiều alarm ngoài ý muốn.

---

# 35. Time handling

Server là nguồn thời gian chính.

Lưu PostgreSQL timestamp dạng timezone-aware.

Khuyến nghị:

```text
UTC trong database
Asia/Ho_Chi_Minh ở UI
```

Nếu triển khai toàn bộ nội bộ Việt Nam, vẫn phải thiết kế timezone rõ ràng.

Không dùng timestamp từ browser để quyết định thứ tự alarm.

---

# 36. UI/UX acceptance criteria

UI phải:

- đẹp
- hiện đại
- tinh gọn
- rõ ràng
- phù hợp môi trường bệnh viện
- không giống template AI phổ biến
- không lạm dụng card
- không lạm dụng animation
- responsive cho PC và Android
- touch-friendly trên màn hình Android

### Alarm

Trong điều kiện LAN bình thường, từ khi server nhận alarm đến khi client nhận event phải ở mức realtime, mục tiêu dưới 1 giây.

Popup phải rõ:

```text
LOẠI REDCODE
KHOA
VỊ TRÍ
GHI CHÚ
```

Màu cảnh báo phải đủ tương phản.

Nút dismiss phải dễ thao tác bằng touch.

---

# 37. Kiosk requirements

Receiver client phải có:

- auto start
- fullscreen/kiosk
- auto reconnect
- không yêu cầu login thủ công mỗi lần boot
- hiển thị trạng thái READY
- tự phục hồi khi mất WebSocket

Windows:

- có thể dùng Edge/Chrome kiosk + Windows startup/task scheduler

Android:

- kiosk/browser auto-launch nếu thiết bị hỗ trợ

Nếu Android browser không đáp ứng autoplay/audio unattended, phải ghi nhận kết quả test và đề xuất phương án kỹ thuật trước khi thay đổi kiến trúc.

---

# 38. Existing repository migration

Repo hiện tại:

```text
buinguyenhong/redcodever2
```

đang dùng:

```text
React
Vite
Tailwind
Supabase
Supabase Realtime
Supabase Auth
Supabase Storage
```

Không cần vứt bỏ toàn bộ UI.

Có thể tái sử dụng:

- React structure
- routing concept
- alarm UI concept
- monitor concept
- reports concept

Nhưng phải loại bỏ dependency runtime vào Supabase.

Đặc biệt phải sửa các vấn đề status không thống nhất hiện tại như:

```text
"Đang báo động"
"active"
"resolved"
```

thành machine enum thống nhất.

---

# 39. Implementation phases

## Phase 1 — Foundation

- FastAPI
- PostgreSQL schema
- migrations
- configuration
- Docker
- health check

## Phase 2 — Auth

- users
- departments
- roles
- permissions
- login

## Phase 3 — Stations

- registration
- device identity
- heartbeat
- WebSocket
- reconnect
- monitoring

## Phase 4 — Alarm engine

- alarm types
- receiver groups
- alarm creation
- FIFO
- WebSocket broadcast
- event log

## Phase 5 — Audio

- local audio
- configuration
- audio readiness
- test audio
- alarm sequence

## Phase 6 — Frontend

- dashboard
- alarm UI
- admin
- monitor
- configuration

## Phase 7 — Reports

- reports
- filtering
- XLSX export

## Phase 8 — n8n

- webhook
- retry
- failure logging

## Phase 9 — Production hardening

- Docker
- Nginx
- kiosk
- restart
- backup validation
- load test
- reconnect test
- alarm test

---

# 40. Acceptance test bắt buộc

Coding agent chỉ được xem implementation hoàn thành khi test được:

### Test 01
User không có permission không thể phát alarm.

### Test 02
User có permission phát alarm thành công.

### Test 03
50+ client WebSocket cùng kết nối.

### Test 04
Alarm được broadcast đúng receiver group.

### Test 05
Client ngoài receiver group không nhận alarm.

### Test 06
Hai alarm liên tiếp được xử lý FIFO.

### Test 07
Client mất mạng tự reconnect.

### Test 08
Server restart, client tự reconnect.

### Test 09
n8n down nhưng Redcode vẫn phát alarm.

### Test 10
n8n down được ghi log.

### Test 11
Client offline xuất hiện trong Admin dashboard.

### Test 12
Client reconnect chuyển lại ONLINE.

### Test 13
Audio local vẫn phát khi Internet bị ngắt.

### Test 14
Audio test được từ Admin.

### Test 15
Dismiss tại client A không làm mất alarm tại client B.

### Test 16
Alarm history vẫn tồn tại sau dismiss.

### Test 17
Export XLSX hoạt động.

### Test 18
Database restart không mất dữ liệu.

### Test 19
Container restart không mất configuration/audio/data.

### Test 20
Browser refresh không làm mất station identity.

### Test 21
Double-click/retry không tạo duplicate alarm.

### Test 22
Unauthorized API request bị từ chối.

### Test 23
Password/token không xuất hiện trong log.

### Test 24
Alarm UI rõ ràng trên màn hình PC.

### Test 25
Alarm UI thao tác tốt bằng touch trên Android.

---

# 41. Coding rules cho Agent

1. Không tự ý thêm công nghệ mới nếu chưa có lý do.
2. Không đưa Redis/message broker vào V1.
3. Không đưa Supabase trở lại.
4. Không tạo PostgreSQL container mới.
5. Không hard-code receiver/channel/permission.
6. Không hard-code alarm type.
7. Không hard-code department.
8. Không để client gọi n8n trực tiếp.
9. Không để n8n nằm trong critical path.
10. Không dùng polling thay cho WebSocket để realtime alarm.
11. Không xóa audit log.
12. Không để dismiss của một client ảnh hưởng client khác.
13. Không commit `.env` hoặc secret.
14. Không dùng UI template AI phổ biến.
15. Không làm UI nhiều card/gradient/glassmorphism.
16. Không thêm tính năng ngoài scope nếu không cần.
17. Mọi cấu hình nghiệp vụ quan trọng phải nằm ở database/admin UI.
18. Mọi thay đổi schema phải dùng migration.
19. API phải có validation và authorization ở backend.
20. Code phải dễ bảo trì và ưu tiên tính ổn định.

---

# 42. Definition of Done

Implementation được coi là đạt khi:

- Có thể chạy bằng Docker.
- Kết nối PostgreSQL container hiện có.
- React + FastAPI hoạt động qua Nginx.
- PC client hoạt động.
- Receiver station hoạt động.
- WebSocket realtime hoạt động.
- Heartbeat hoạt động.
- Offline monitoring hoạt động.
- Alarm routing hoạt động.
- Audio hoạt động.
- Audit log hoạt động.
- n8n integration hoạt động độc lập.
- Reports/export hoạt động.
- Authentication/authorization hoạt động.
- Restart/reconnect hoạt động.
- Không phụ thuộc Internet.
- Không mất dữ liệu khi restart container.
- UI đáp ứng đúng design direction.
- Tất cả acceptance tests chính được kiểm tra.

---

# 43. Ưu tiên khi có xung đột

Nếu phải lựa chọn giữa tính năng và độ ổn định, thứ tự ưu tiên là:

```text
1. Alarm delivery reliability
2. Audio reliability
3. Realtime connection
4. Data integrity
5. Audit/logging
6. Device monitoring
7. Security
8. Configuration
9. Reporting
10. UI polish
11. Convenience features
```

Không hy sinh 1–7 để thêm tính năng mới.

---

# 44. Ghi chú cuối cho coding agent

Đây là hệ thống cảnh báo y tế nội bộ, không phải một dashboard CRUD thông thường.

Mọi quyết định implementation phải ưu tiên:

**đúng — nhanh — ổn định — có thể truy vết — dễ phục hồi — ít thành phần.**

Nếu phát hiện một yêu cầu chưa đủ rõ và có thể ảnh hưởng đến tính an toàn/reliability, agent phải ghi rõ vấn đề và phương án đề xuất thay vì tự ý xây dựng một nghiệp vụ phức tạp.

Đặc biệt, trước khi kết luận Android/browser audio đáp ứng yêu cầu unattended alarm, phải kiểm thử trên thiết bị thực tế.

---

# 45. Yêu cầu bổ sung sau code review

Các yêu cầu sau hợp nhất yêu cầu thực thi sau review R01–R16. Thực hiện theo thứ tự A → B → C; trạng thái thực thi và bằng chứng nằm trong `agent_changelog.md`.

## Batch A — Reliability blockers

- **R01 — Schema:** migration bảo toàn dữ liệu, đồng bộ ORM/cột/default/nullable/FK/index; PostgreSQL sequence khởi tạo theo dữ liệu hiện có. Có đường adoption được kiểm chứng cho DB dev từng tạo bằng create_all. Production chạy Alembic trước Uvicorn, không dùng create_all thay migration; một API worker khi WebSocket manager còn in-memory. Nghiệm thu fresh migrate/startup/login/station/alarm/dismiss/report và upgrade giữ history trên database test riêng.
- **R02/R10 — Atomic alarm và recovery:** alarm, immutable target snapshot, station states, CREATED audit và outbox cùng một transaction. Idempotency theo actor/request và payload fingerprint; cùng request trả một alarm, key khác payload trả conflict. Frontend giữ key khi retry uncertain request. DB-backed recovery sau crash giữa commit/broadcast và retry chưa ACK qua WebSocket; không thay realtime bằng client polling. ACK timestamps phản ánh hành động thực. Fault injection trước/sau commit và concurrent retries phải được kiểm chứng.
- **R03/R06 — FIFO/audio:** server điều phối concurrent delivery; client dedup theo ID, sort server_sequence, không dùng client clock. Enqueue B/C không restart head A; cleanup/generation guard chặn callback cũ. Play rejection chỉ báo FAILED, không báo started/completed thành công. Test audio có resume/play awaited, kết quả trả server/admin, không ngắt alarm. Unlock retry đúng một lần. Readiness phân biệt UNKNOWN/NOT_READY/READY và khả năng browser play với xác nhận loa vật lý. Nghiệm thu browser ba alarm, sync/duplicate/stale events, repeat/interval, autoplay rejection.
- **R04 — Cancel:** schema backend/frontend thống nhất, broadcast tới target và dashboard; cancel head dừng audio/tiến queue, cancel pending chỉ remove pending; reconnect reconcile cancelled. API idempotent, không tạo n8n cancel/end. Local dismiss không ảnh hưởng trạm khác.
- **R05 — Heartbeat/restart:** timeout đóng đúng socket với identity guard; socket cũ không update connection mới. Startup reconcile persisted ONLINE; client ACK watchdog, capped reconnect và sync retry khi HTTP lỗi. Nghiệm thu half-open, socket A/B race và server restart.

## Batch B — Configuration, audit và vận hành

- **R07/R08 — Kiosk/auth:** boot/refresh bằng credential trạm nội bộ, không cần JWT user sau provisioning; station 401 hiển thị lỗi activation. Dọn socket/timer khi token/user/station đổi, xử lý revoke/expiry; phân biệt dashboard monitoring và receiver audio. Offline dismiss lưu pending action, retry idempotent, không replay alarm đã dismiss. Provisioning theo mục 46.
- **R10/R12/R13/R16 — Permission/config:** backend là nguồn permission duy nhất, API effective permissions; Admin chỉnh quyền khoa/user theo mô hình được chốt, bật/tắt cấu hình, ordered audio sequence/repeat/interval, receiver membership và n8n integration. Omitted membership khác explicit empty; sửa tên group không xóa thành viên; target snapshot không đổi sau tạo. Soft-disable để giữ history, rotate/revoke/disable đóng socket cũ; audit cấu hình. Lifecycle theo mục 46, không bổ sung workflow xử lý sự cố.
- **R09 — Outbox:** claim/lease/locked_at, reclaim abandoned PROCESSING, due-time filter trước limit, capped exponential backoff và attempt audit. At-least-once với stable event ID/idempotency cho n8n, không chặn core. Có backlog/failure monitoring và Admin retry khi hết retries; config/credential được quản trị và bảo vệ.
- **R11/R14/R15 — State/security/health:** typed event allowlist, target authorization, transition/idempotency guards; ACK muộn không ghi đè DISMISSED/CANCELLED/EXPIRED. DISPLAYED chỉ lúc overlay head hiển thị. Connect/disconnect có station ID; structured errors/rollback, config before/after audit không chứa secret. Production fail-fast với PostgreSQL, DEMO_MODE=false, SECRET_KEY riêng ≥32 ký tự và origin allowlist cụ thể; seed idempotent, chỉ bootstrap Admin, không demo data. Validate enum/length/bounds/FK/color/null/local audio; upload filename server-generated, path containment, size/content validation. Credentials query không xuất hiện trong Nginx/Uvicorn logs. Health/readiness phản ánh DB/tasks/recovery; n8n degraded không làm core failed.
- **R16 — Reports/deploy:** report chỉ ADMIN; ngày Asia/Ho_Chi_Minh quy đổi UTC, invalid/reversed range trả 4xx, UI timezone explicit. SQL aggregation/pagination theo ngày/tháng/type/khoa; per-station offline count/duration và average presentation/ACK khi có dữ liệu, không giả số thiếu. XLSX detail đầy đủ timestamps/error và chống spreadsheet formula. Image build frontend từ checkout sạch, external PostgreSQL network rõ ràng, healthchecks/restart/audio persistence. Backup/restore DB và audio phải kiểm chứng round trip; document single-worker constraint. Migration forward-only; rollback bằng backup đã kiểm chứng/image tương ứng, không tự drop bảng hoặc downgrade.

## Batch C — UI và acceptance

1. Clinical Control Interface: typography/phân cấp rõ, ít cards/shadows, không glass/blur trang trí/animation liên tục; alarm full-screen rõ loại/khoa/location/note/dismiss.
2. Responsive nội dung dài và Android nhỏ; dismiss luôn tiếp cận được, timeout/loading/errors rõ.
3. Meaningful regression cho queue/audio/activation/cancel/auth lifecycle; không chỉ mock assertions.
4. Chạy 50+ rồi 100 WebSocket thật qua Nginx trên PostgreSQL: group-in/out, heartbeat, simultaneous alarms, slow client, reconnect/restart. Ghi latency p50/p95/max, lost/duplicate count; mục tiêu LAN bình thường dưới 1 giây.
5. Kiểm thử n8n down/crash retry, DB/container restart, config/audio persistence, backup restore, credential log scan và acceptance 01–25.
6. Kiểm thử PC/Android/loa thật: unattended boot/autoplay, mất mạng/refresh/reboot, volume/mute/sleep. Thiếu môi trường ghi BLOCKED và bước tái hiện; build/mock không thay bằng chứng thực.

## Bàn giao

Mỗi đợt cập nhật `agent_changelog.md`: finding R01–R16 với FIXED/PARTIAL/BLOCKED, file/migration thay đổi, commands/môi trường/pass/fail, ma trận acceptance 01–25, fresh deploy/upgrade/rollback/backup và giới hạn đã kiểm chứng. Không kết luận production-ready khi blockers hoặc acceptance thiết yếu chưa có bằng chứng.

# 46. Quyết định nghiệp vụ hiện hành — 2026-10-06

Mục này ưu tiên hơn mọi nội dung baseline hoặc yêu cầu review cũ có xung đột.

## Vai trò và thiết bị nhận

- Chỉ **ADMIN** và **OPERATOR** được tạo tài khoản/đăng nhập. VIEWER cũ bị vô hiệu hóa, giữ lịch sử; các mô tả Viewer trong baseline không còn áp dụng.
- ADMIN quản trị cấu hình, xác nhận thiết bị và xem reports/XLSX. OPERATOR phát alarm theo quyền khoa và xem alarm log; không truy cập API/UI báo cáo/export.
- Admin đăng nhập trên máy nhận, chọn trạm, xác nhận qua `POST /api/stations/{id}/confirm-device`. Server tự rotate credential, thu hồi kết nối cũ; browser tự lưu identity để boot/refresh. Không yêu cầu người dùng nhập/copy token thủ công; credential chỉ là chi tiết nội bộ.
- Trạm đã xác nhận có **TEST LOA** local, **TEST HIỂN THỊ** overlay không tạo alarm, **TEST KẾT NỐI** WebSocket PING/PONG RTT timeout 5 giây. User khoa dùng được trên thiết bị đã xác nhận; khóa diagnostics khi có alarm thật.

## Thời hạn alarm và đồng bộ

- `alarm_types.validity_seconds`: mặc định **300 giây**, range **10–86400 giây**, quản trị theo loại alarm.
- Mỗi alarm snapshot `expires_at` lúc tạo. Đổi cấu hình không thay thời hạn alarm đã phát.
- Global status hiện hành: **ACTIVE / EXPIRED / CANCELLED**. EXPIRED hiển thị **CẢNH BÁO ĐÃ PHÁT**, không đồng nghĩa hủy/sự cố hoàn thành. Các status presentation trong baseline được theo dõi ở trạm, không dùng làm workflow toàn cục.
- Hết hạn dừng visual/audio, lưu history/audit đúng một lần, không gửi n8n end/expiry. Cancel vẫn riêng và không gửi n8n cancellation.
- Trạm thuộc target snapshot nhưng offline/đăng nhập sau đồng bộ alarm **còn hiệu lực**, kèm cấu hình audio/expiry, theo FIFO. Alarm hết hạn/cancel hoặc đã local dismiss không được phát lại.
- Migration hiện hành `20261006_validity` bổ sung validity/expiry và vô hiệu hóa VIEWER; giữ dữ liệu/history.

## Phần chưa nghiệm thu

Test API SQLite, unit audio và build không đóng acceptance mạng/loa. Các mục còn PARTIAL/BLOCKED gồm PostgreSQL fresh/upgrade/adoption, Docker/Nginx/restart/restore, concurrent browser FIFO/reconnect, outbox multi-worker/admin controls, cấu hình/audit/report còn thiếu và PC/Android unattended audio. Ma trận chi tiết được duy trì trong `agent_changelog.md`.
