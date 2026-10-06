# REDCODE — Code review và đối chiếu đặc tả

Ngày review: 2026-10-06.

## 1. Kết luận

**Dự án đã có nền tảng và nhiều chức năng V1, nhưng chưa đạt Definition of Done để triển khai production.** Các khoảng trống lớn nhất nằm ở migration, tính toàn vẹn giao dịch tạo alarm, FIFO/audio phía trình duyệt, phục hồi kết nối và audit. Build thành công và test hiện có pass chưa đủ để kết luận hệ thống cảnh báo hoạt động ổn định.

Nguồn yêu cầu: `REDCODE_SPEC.md` và `REDCODE_IMPLEMENTATION_SPEC_V2.md`. Hai file có cùng SHA-256 `5B9FA88166A3D0A358708225F7E982767DA053C3F00A69C400B0B55539279482`, đều là baseline 1.0, 1615 dòng. README tự mô tả “Spec V3 Implementation”; chưa có đặc tả V3 trong workspace để xác nhận những thay đổi nghiệp vụ đó.

Review dựa trên mã nguồn đang có, đọc test, chạy build và test trong môi trường tạm. Không chỉnh sửa implementation.

## 2. Kiểm chứng đã thực hiện

| Kiểm tra | Kết quả | Ý nghĩa |
|---|---|---|
| `npm run build` tại `frontend/` | PASS, Vite build thành công | Xác nhận bundle tạo được; không chứng minh hành vi browser |
| `python -m pytest tests -q -p no:cacheprovider` tại `backend/` | **29 passed**, 5 warnings, 26.29 giây | Chạy với SQLite tạm, development/demo, audio tạm; không dùng DB dự án |
| Alembic upgrade trên SQLite trống rồi truy vấn ORM `User` | **FAIL: `no such column: users.last_login_at`** | Migration thành công nhưng schema tạo ra không chạy được ORM |
| Docker CLI | Có, version 28.5.1 | Docker engine chưa chạy: không kết nối được `dockerDesktopLinuxEngine` |
| Git tracked `.env`, `*.db`, `frontend/dist/*` | Không có kết quả | Các file này không nằm trong danh sách tracked hiện tại |
| Git diff sau build/test | Không có thay đổi tracked trước khi thêm tài liệu review | Review không sửa mã nguồn ứng dụng |

Database kiểm thử đặt tại `C:/Users/Admin/AppData/Local/Temp/opencode/`. Test hiện hữu chủ yếu tạo bảng bằng `Base.metadata.create_all`, bỏ qua migration; do đó che khuất lỗi production. `test_alembic_migrations.py` chỉ kiểm tra upgrade/downgrade, không chạy ứng dụng trên schema đó. Test tải 50/100 trạm dùng `MockWebSocket`, không phải 50/100 kết nối mạng thật. Test 50 heartbeat gửi 50 request vào cùng một station.

Chưa kiểm chứng: PostgreSQL thực, Docker/Nginx end-to-end, mất mạng/server restart/DB restart thực, loa thiết bị, unattended Android, giao diện trên browser/Android và backup restore.

## 3. Đã triển khai được gì

| Nhóm yêu cầu | Đã có | Đánh giá |
|---|---|---|
| Kiến trúc | FastAPI, SQLAlchemy async, React/Vite/Router, Nginx, Compose, audio volume; Compose không tạo PostgreSQL mới | Đúng hướng; startup/migration chưa đạt |
| Auth | JWT, password hashing, kiểm tra user enabled, dependency phân quyền ADMIN/OPERATOR/VIEWER, login audit | Có backend cơ bản; vòng đời socket/auth còn thiếu |
| Permission | Bảng `department_alarm_permissions`, backend kiểm tra khi tạo alarm; operator không spoof source department | Có cơ chế, nhưng hai nguồn permission và UI không đồng nhất |
| Stations | Admin provisioning, token ngẫu nhiên/hash, localStorage identity, heartbeat, monitor, audio-test API | Có cơ chế, nhưng bootstrap kiosk và timeout/restart có lỗi |
| Alarm engine | Alarm type cấu hình DB, nhóm nhận many-to-many, sequence PostgreSQL, unique idempotency key, broadcast | Có engine; giao dịch, ordering và delivery recovery chưa đủ |
| Local dismiss | State riêng `alarm_station_states`, endpoint xác thực station, không đổi global alarm khi dismiss | Có; frontend thất bại request có thể làm mất audit/replay lại |
| Audio | WAV local, upload metadata/file, sequence/repeat player, gửi AUDIO_STARTED/COMPLETED/FAILED | Có; nhiều lỗi vòng đời playback/readiness |
| Frontend | Login, operator, kiosk, admin CRUD/monitor/audit, report, fullscreen alarm overlay | Có màn hình chức năng; chưa đáp ứng đủ cấu hình và visual direction |
| Reports | Khoảng ngày, tổng số/theo loại/theo khoa/status, đếm disconnect, tải XLSX | Đã có một phần yêu cầu |
| n8n | Outbox DB, worker HTTP timeout/retry; không await n8n trong create alarm | Đúng hướng; crash recovery chưa đạt, cancel trái baseline |
| Tests | Auth/permission, local dismiss, idempotency/concurrency, mock broadcast/load, migration cycle | Có 29 test pass; còn thiếu regression browser và production integration |

## 4. Findings theo ưu tiên

Quy ước: **P0** chặn nghiệm thu core/production; **P1** phải hoàn thiện trước nghiệm thu V1; **P2** cải thiện UI/tài liệu. Các lỗi hành vi browser dưới đây được xác định bằng đọc code, chưa chạy browser automation.

### R01 — P0: Migration không khớp ORM; production startup bỏ qua migration

- `backend/alembic/versions/8280022f67e9_initial_schema.py:42-57`: thiếu `users.last_login_at` so với model.
- Migration stations dùng `last_heartbeat_at`, thiếu `last_seen_at` và `websocket_connected` mà ORM sử dụng.
- Migration alarms dùng `alarm_code` bắt buộc, `location_text`, `triggered_by_user_id`; model dùng `source_location`, `created_by_user_id`, `activated_at` và không có `alarm_code`.
- Migration event dùng `event_metadata`/`details`; model map cột `metadata`, có `event_time`, `system_events.station_id`; audio migration thiếu `updated_at`.
- `backend/app/main.py:35-38` gọi `create_all`; `backend/Dockerfile:23` chỉ chạy Uvicorn. `create_all` không sửa cột cũ và không tạo sequence PostgreSQL được khai báo trong migration.

**Hậu quả:** database migrate sạch không chạy được ứng dụng; database tạo bằng startup có thể thiếu `alarm_server_sequence`, làm POST alarm thất bại trên PostgreSQL. Đã tái hiện thiếu `users.last_login_at` trên schema migrate.

**Yêu cầu:** đồng bộ ORM/migration bằng đường nâng cấp bảo toàn dữ liệu, startup production chạy migration trước API; test login/create/heartbeat/report trên PostgreSQL tạo hoàn toàn bằng Alembic.

### R02 — P0: Tạo alarm không nguyên tử và có khoảng mất realtime

`backend/app/api/alarms.py:176-178` commit riêng alarm, rồi `:198-266` mới tạo station states/events/outbox và commit tiếp. Process chết hoặc giao dịch thứ hai lỗi sẽ để lại alarm thiếu deliveries/audit/outbox. Retry cùng key trả ngay existing ở `:115-117`, không hoàn tất phần còn thiếu. Crash sau commit thứ hai nhưng trước broadcast cũng khiến receiver đang online không biết alarm mới, vì client chỉ sync lúc reconnect.

**Yêu cầu:** dùng flush lấy ID, commit một lần cho toàn bộ alarm + target snapshot + states + audit + outbox; bổ sung phục hồi delivery chưa ACK từ DB sau crash/send fail. Realtime chính vẫn WebSocket.

### R03 — P0: FIFO chưa dựa trên sequence; alarm mới làm phát lại alarm đang phát

`frontend/src/context/WebSocketContext.jsx:62-65,125-129` chỉ append, không sắp xếp `server_sequence`; sync response cũ đến sau realtime mới sẽ đưa alarm cũ vào cuối hàng đợi. Backend POST đồng thời cũng không bảo đảm thứ tự commit/broadcast theo nextval.

Effect `:170-219` phụ thuộc toàn bộ `activeAlarms`. Khi append alarm B, effect gọi `playAlarmSequence` cho alarm A lại từ đầu, vì `soundPlayer.js:48` gọi stop. Việc enqueue/sync do đó có thể lặp âm thanh và audit. Effect không có cleanup playback khi đổi/unmount.

**Yêu cầu:** merge/dedup/sort theo server ordering, điều phối delivery khi create đồng thời, playback gắn với ID head chứ không với toàn bộ queue. Kiểm thử sync/realtime cạnh tranh và 3 alarm đến khi A đang phát.

### R04 — P0: Hủy alarm không dừng trên receiver; đồng thời gửi n8n event ngoài scope

`backend/app/api/alarms.py:346-354` chỉ gửi dashboard, không gửi station. Payload là `{type: ALARM_EVENT, event: ALARM_CANCELLED}`, nhưng frontend `WebSocketContext.jsx:122-147` chỉ xử lý cancel ở top-level `type: ALARM_CANCELLED`; case ALARM_EVENT không xử lý cancel. `:331-343` enqueue `RED_CODE_CANCELLED` cho n8n, trong khi spec §§8,27 yêu cầu không gửi kết thúc alarm V1.

**Yêu cầu:** thống nhất contract cancel, gửi đúng target stations và dashboard, dừng current/remove queued alarm, reconcile cancellation khi reconnect; bỏ outbox cancellation. Cancel lặp phải idempotent.

### R05 — P0: Heartbeat timeout làm socket sống nhưng bị loại khỏi routing

`backend/app/core/websocket_manager.py:226-228` gọi disconnect mà không đóng socket, không giữ identity socket khi xử lý timeout. Socket đó vẫn nhận heartbeat; `update_heartbeat:94-110` đánh ONLINE trong DB nhưng không đưa socket trở lại `active_stations`. Frontend không nhận close nên không reconnect, và station không nhận alarm nữa.

Monitor chỉ duyệt heartbeat map in-memory; server restart không reset/reconcile station từng ONLINE trong DB, dẫn đến station offline thực vẫn ONLINE. Timeout cũng có thể đụng socket mới nếu reconnect giữa snapshot và disconnect.

**Yêu cầu:** đóng đúng socket hết hạn, bảo vệ race bằng socket identity; reconcile persisted status lúc startup; chỉ báo websocket_connected khi có socket thật. Test không heartbeat rồi tiếp tục heartbeat, timeout/reconnect race và server restart.

### R06 — P0: Audio báo ready/success sai và test loa có thể ngắt alarm

- `soundPlayer.js:88-99`: play reject vẫn gọi onStart; sau đó có thể gọi onComplete. Server state FAILED sẽ bị ghi thành AUDIO_STARTED/AUDIO_COMPLETED dù không phát được.
- `playTestTone:109-134` gọi stop alarm, không await `ctx.resume()`, đánh READY dù context có thể còn suspended; không trả kết quả thành công/thất bại về admin.
- `unlockAudio:34-39` chỉ phát silent audio. UI `ReceiverStationView.jsx:58-65,234-241` gọi đó là “kiểm tra âm thanh thực tế”, không phát âm thanh nghe được.
- `WebSocketContext.jsx:274` expose singleton readiness thay cho state `audioReady`; test tone không cập nhật React state ngay.
- Unlock không tự tiếp tục/retry alarm đang bị chặn, vì effect không phụ thuộc kết quả unlock.

**Yêu cầu:** playback có session/generation bảo vệ callback cũ, lỗi không báo started/completed thành công; test local audio nghe được và có kết quả server; test không ngắt alarm; readiness UNKNOWN/NOT_READY/READY rõ ràng. Resume alarm sau unlock bằng hành động được kiểm soát.

### R07 — P1: Kiosk độc lập không cấu hình được qua UI hiện tại

`ReceiverStationView.jsx:15-24` luôn gọi GET stations, endpoint cần user login (`stations.py:21-26`); `client.js:22-26` redirect mọi 401 về `/login`. Máy kiosk mới chỉ có station code/token nên không tải được dropdown để kích hoạt. Máy kiosk đã cấu hình nhưng không có JWT cũng vẫn bị redirect mỗi lần mount.

**Yêu cầu:** activation bằng station code/token qua API station-authenticated trả thông tin chính trạm; không bắt receiver login user để tải danh sách. Phân biệt station 401 và user session 401. Kiểm thử boot/refresh kiosk chỉ có device credential.

### R08 — P1: Reconnect/auth và local dismiss chưa bền vững

- `WebSocketProvider` không theo dõi token/user từ AuthContext: login/logout không trực tiếp thay đổi socket. Logout có thể giữ socket dashboard đã xác thực.
- Cleanup effect close socket nhưng onclose vẫn schedule reconnect; callback/timer/socket cũ có thể mở kết nối sai identity sau config change hoặc unmount.
- Không có heartbeat ACK watchdog phía client cho kết nối half-open; sync lỗi chỉ console warn, không retry khi socket vẫn OPEN.
- Sync chỉ merge, không loại state đã cancel/dismiss; stale realtime có thể đưa alarm trở lại sau dismiss.
- `dismissCurrentAlarm:226-241` xóa UI trước, API lỗi chỉ warn; không có pending dismiss/retry. Sau reconnect alarm bị phát lại, audit thiếu.
- Dashboard cũng đưa mọi broadcast vào overlay/audio; dismiss ở dashboard không có station không được lưu state riêng.

**Yêu cầu:** quản lý connection theo identity/auth lifecycle, disposed guard, watchdog, resync retry; lưu pending dismiss và retry idempotent. Xác định rõ dashboard monitoring và receiver playback để routing âm thanh không bị mở rộng ngoài cấu hình.

### R09 — P1: Outbox bị kẹt PROCESSING sau restart

`n8n_outbox.py:49-50,72-77`: chuyển batch sang PROCESSING rồi commit trước send; worker chỉ query PENDING/FAILED. Process chết giữa send/batch làm record PROCESSING bị bỏ vĩnh viễn. Model không có lease/locked_at để phục hồi. `:131` backoff là `2 * attempt`, không phải exponential như comment. Các thất bại trước lần cuối chưa được ghi SystemEvent.

**Yêu cầu:** claim/lease rõ ràng, reclaim expired processing, due-time filter ở SQL trước limit, exponential capped backoff và audit mỗi attempt. Nêu semantics at-least-once, gửi định danh event để n8n dedup khi send thành công nhưng crash trước commit.

### R10 — P1: Permission có hai nguồn; UI không thể cấu hình đầy đủ

`alarms.py:125-136` đọc relational permission rồi fallback JSON, mặc định cho phép nếu không có cấu hình. Seed ghi relational permissions nhưng không JSON. `OperatorDashboard.jsx:25-39` chỉ đọc JSON nên hiển thị mã bị backend từ chối; VIEWER cũng được UI đưa vào màn hình phát alarm. Admin không có permission editor; API chỉ GET permission, sửa allowed IDs qua alarm type tạo hai nguồn trạng thái.

**Yêu cầu:** một source of truth; API trả allowed alarm types/effective permissions theo user; UI dùng kết quả đó. Thêm editor admin cho user/khoa theo quy tắc được chốt, test deny/allow/new type/disabled department. Idempotency lookup hiện trước permission và key toàn cục: phải scope user + payload fingerprint và từ chối cùng key khác payload. Frontend giữ key của một thao tác qua retry; hiện `OperatorDashboard.jsx:72` sinh key mới mỗi lần gửi lại.

### R11 — P1: Audit/state không phản ánh thực tế; state terminal bị ghi đè

- Create alarm gán received/displayed timestamp trước ACK (`alarms.py:215-224`); sync GET tự gán DISPLAYED (`stations.py:234-255`) trước UI thực sự hiển thị.
- `main.py:155-165` coi RECEIVED và DISPLAYED như nhau; client chưa gửi DISPLAYED lúc alarm lên head.
- STATION_EVENT nhận event type/metadata tùy ý, không kiểm tra target tồn tại trước append audit, không có guard state transition. Event đến muộn có thể ghi đè DISMISSED, khiến alarm xuất hiện lại sau sync.
- Connection audit `websocket_manager.py:200-205` đặt `station_id=None` dù biết station code, gây khó thống kê per station.
- CRUD chủ yếu thiếu config-change audit; lỗi DB/server chỉ logger text, chưa có cơ chế structured error logging/audit đầy đủ theo spec.

**Yêu cầu:** typed event allowlist + target authorization + state transition monotonic/terminal, timestamp theo ACK thực, event id/dedup, station_id đúng; append-only config audit gồm actor/before/after không chứa secret. Database unavailable không được làm error handler ghi DB lỗi lặp vô hạn.

### R12 — P1: Sửa receiver group có thể xóa toàn bộ membership

`AdminDashboard.jsx:405-412` mở edit group luôn đặt `station_ids: []`; `:425-433` gửi mảng rỗng khi save. Backend `receiver_groups.py:71-75` thay thế toàn bộ membership. `ReceiverGroupOut` không trả membership nên UI không có dữ liệu giữ lại. Chỉ sửa tên nhóm cũng có thể khiến không trạm nào nhận alarm.

Sync/dismiss còn tính target từ group hiện tại (`stations.py:203-232,313-318`), không dựa snapshot station states khi alarm tạo; sửa nhóm sau alarm có thể phát alarm cũ đến trạm mới hoặc mất alarm trạm cũ.

**Yêu cầu:** đọc/edit membership đúng; phân biệt omitted và empty list; target alarm snapshot bất biến dùng cho routing/sync/dismiss. Test sửa tên không đổi routing và đổi group không làm thay đổi lịch sử target.

### R13 — P1: Xóa cứng cấu hình phá dữ liệu audit hoặc lỗi foreign key

`stations.py:438-448`, `alarm_types.py:118-128`, các DELETE users/departments/groups dùng hard delete. Station model `models/__init__.py:99` cascade delete-orphan station states; alarm type model `:148` có quan hệ alarms không có cách xử lý xóa history an toàn. SQLite test không chứng minh PostgreSQL FK behavior.

**Yêu cầu:** soft-disable cấu hình đã tham gia alarm/audit, đóng/revoke socket khi disable/rotate token; không xóa station state/history. Station schema hiện thiếu field enabled cho update. Thử DELETE bằng API trên PostgreSQL có history và bảo đảm dữ liệu giữ nguyên.

### R14 — P1: Cấu hình production và upload còn thiếu validation

- `config.py:7,10,21`: demo mặc định true, secret mặc định cố định, wildcard origins.
- `.env.example` thiếu DEMO_MODE/INITIAL_ADMIN_PASSWORD; Compose chỉ force ENVIRONMENT=production. Copy example không bảo đảm tránh seed tài khoản demo.
- Production seed kiểm tra admin trước rồi seed tất cả khoa/group; nếu không có admin password vẫn commit cấu hình, lần startup sau có thể seed lại và lỗi duplicate (`seed.py:39-45,130-145`).
- Pydantic chưa ràng buộc enum role, độ dài, ID/repeat/interval/color/path; update thường gán null vào field not-null và chưa kiểm tra FK.
- `audio.py:35-39` ghép code + filename rồi ghi file trực tiếp, không sanitize/path containment, MIME/content/size validation ở backend. `audio_sequence` cho phép URL Internet tùy ý.
- WebSocket token nằm query; Nginx không redaction access log cho `/ws` nên token có thể xuất hiện trong request log.

**Yêu cầu:** fail-fast production config, demo explicit opt-in, CORS allowlist; seed idempotent, không hard-code cấu hình khoa bệnh viện trong bootstrap production; validation có bound và lỗi 4xx; upload filename do server tạo, local assets only; credential không nằm log (auth message hoặc log-format redaction).

### R15 — P1: Health DB down có thể trả 500 thay cho trạng thái lỗi

`health.py:16-19` bắt lỗi SELECT 1 rồi `:33-34` query count bằng DB đang lỗi. Endpoint sẽ raise thay vì trả HealthResponse. WebSocket status luôn hard-code ok, không phản ánh monitor task; health còn gọi n8n trực tiếp mỗi lần admin poll.

**Yêu cầu:** tách liveness/readiness, trả trạng thái ổn định khi DB down và recover, kiểm tra background task; n8n degraded không làm core failed và dùng trạng thái worker/cached probe.

### R16 — P1/P2: Báo cáo, admin config và UI còn thiếu so với baseline

- Reports chưa có theo ngày/tháng, thời gian presentation/ack trung bình, offline theo từng trạm/duration dù đã có timestamp; summary tải mọi Alarm vào RAM.
- Ngày report coi UTC (`reports.py:28,37`) trong khi người dùng Việt Nam chọn ngày địa phương; UI locale vi-VN không đặt timezone Asia/Ho_Chi_Minh. Date input sai chưa được xử lý 4xx.
- XLSX chỉ có state + giờ dismiss trong một chuỗi (`reports.py:156-165`), thiếu sheet chi tiết timestamps/error per station. Note/location/user data ghi vào cell cần xử lý tránh thành formula khi bắt đầu bằng `=`.
- Admin chỉ chọn 1 audio (`AdminDashboard.jsx:171,201`), edit sẽ làm mất các file tiếp theo trong sequence; không có editor sắp thứ tự đa file, audio enabled, permission và n8n configuration. Các save ép enabled=true nên không quản trị enable/disable đầy đủ.
- Global status chỉ ACTIVE/CANCELLED khác enum lifecycle đề xuất; sau mọi trạm dismiss vẫn ACTIVE, UI report mô tả “chưa hoàn tất trình chiếu” không còn đúng. Cần chốt cách derive presentation completion theo spec thay vì tự coi thay đổi README là yêu cầu mới.
- UI dùng nhiều rounded cards/shadows, blur ở overlay (`AlarmOverlay.jsx:60`), continuous bounce/ping; chưa đúng clinical direction. Overlay fixed có nội dung dài nhưng chưa xử lý overflow/mobile height; cần test thực trước kết luận nút touch luôn thấy được.
- API client không có timeout/AbortController; exception/error/loading trên nhiều màn hình chỉ console.
- Compose không build frontend trong image, mount `frontend/dist` từ host; external PG network chỉ comment, thiếu healthcheck/readiness và quy trình backup/restore đã kiểm chứng.

**Yêu cầu:** hoàn thiện những mục baseline còn thiếu sau P0/P1 core, dùng SQL aggregates/pagination, timezone rõ, XLSX chi tiết, giao diện clinical responsive và deploy tái lập từ checkout sạch.

## 5. Đối chiếu 25 acceptance tests của đặc tả

“Có test cơ bản” không đồng nghĩa nghiệm thu production; chi tiết các lỗi có thể làm hỏng trường hợp tương ứng ở mục 4.

| Tests | Bằng chứng hiện có | Khoảng trống |
|---|---|---|
| 01–02: quyền phát alarm | Có backend tests pass | Permission UI/effective policy chưa đồng bộ |
| 03: 50+ WS | Mock sockets | Chưa có 50+ real network sockets được kiểm chứng |
| 04–05: receiver routing | Có code filter group; tests group auth | Cần real delivery/exclusion, config-change snapshot, dashboard audio scope |
| 06: FIFO | Test tuần tự mock | Chưa test browser concurrent sync/realtime, effect restart |
| 07–08: reconnect mạng/server | Có backoff | Watchdog/timeout/restart state chưa đúng; chưa test thực |
| 09–10: n8n down | Worker/mock failure | Chưa test crash PROCESSING và fault-injection create transaction |
| 11–12: offline/online admin | Code monitor | Timeout socket sống và DB stale sau restart |
| 13: audio khi ngắt Internet | Local WAV có sẵn | Chưa test browser/thiết bị, sequence còn nhận remote URL |
| 14: admin audio test | API send signal | Chưa có ACK thực; test có thể ngắt alarm/báo ready sai |
| 15–16: local dismiss/history | Backend test pass | Mạng lỗi/pending dismiss, late event, hard delete chưa bảo toàn |
| 17: XLSX | Endpoint và UI có | Cần kiểm tra nội dung chi tiết, timezone và formula handling |
| 18–19: DB/container persistence | Volume/network cấu hình một phần | Chưa kiểm chứng restart/restore PostgreSQL/Docker |
| 20: refresh identity | localStorage có | Kiosk mount gọi API user-auth và redirect login |
| 21: double-click/retry | DB unique/concurrency test | Frontend retry tạo key mới; transaction partial; scope key |
| 22: unauthorized API | Có auth tests | STATION_EVENT target validation, credential revocation còn thiếu |
| 23: token/password logs | Password hash, không tracked env | Query credential có nguy cơ log tại Nginx; chưa log-scan |
| 24–25: PC/Android UI | Code responsive | Chưa có browser/device evidence |

## 6. Hướng xử lý

Giao agent thực thi theo `REDCODE_AGENT_EXECUTION_REQUEST.md`. Ưu tiên R01–R06 trước; sau đó hoàn thiện các P1 và test production. Không dùng số test pass hoặc mock latency làm bằng chứng thay thế kiểm thử thật. Các mục cần loa/Android thực phải ghi rõ BLOCKED khi không có thiết bị, kèm checklist và kết quả thực tế khi thực hiện được.
