# Yêu cầu thực thi cho agent tiếp theo

## Mục tiêu và đầu vào

Hoàn thiện dự án tại `D:/Project/RED CODE` theo `REDCODE_SPEC.md`, `REDCODE_IMPLEMENTATION_SPEC_V2.md` và findings trong `REDCODE_CODE_REVIEW.md`.

Hai file spec hiện giống hệt nhau (baseline 1.0). README “V3” không thay thế đặc tả. Đọc đầy đủ spec và review trước khi sửa. Mục tiêu là hoàn thiện implementation hiện tại; giữ kiến trúc FastAPI + React/Vite + Nginx + PostgreSQL hiện có, ưu tiên reliability/delivery/audio/audit trước UI polish.

Không thêm Redis/broker/Supabase/microservices hay PostgreSQL production container mới. Không commit secret, không xóa history, không làm local dismiss ảnh hưởng trạm khác, không gửi event kết thúc/cancel qua n8n. Mọi đổi schema qua migration. Không sử dụng DB hiện hữu cho test phá hủy; dùng database test riêng trên PostgreSQL hiện có theo cấu hình cung cấp.

## Batch A — Sửa các blocker P0

### A1. Schema và production startup — R01

1. Chọn schema ORM thống nhất, viết migration nâng cấp bảo toàn dữ liệu cho schema từng được tạo bằng Alembic và đường chuyển đổi có tài liệu cho database dev tạo bằng create_all.
2. Đồng bộ tất cả cột/nullable/default/FK/index với ORM; sequence PostgreSQL hoạt động và khởi tạo phù hợp với dữ liệu hiện hữu.
3. Production chạy `alembic upgrade head` trước Uvicorn; không dùng create_all thay migration. Chạy một API worker nếu connection manager còn in-memory và document rõ giới hạn này.
4. Test database trống migrate → startup → login → register station → create alarm → dismiss → report/XLSX. So sánh metadata/schema và kiểm tra nâng cấp không mất history.

**Nghiệm thu:** không còn lỗi missing columns; PostgreSQL alarm creation có sequence đúng; fresh install và upgrade data-preserving hoạt động.

### A2. Giao dịch alarm, idempotency và delivery recovery — R02, R10

1. Alarm + immutable target snapshot + station states + CREATED audit + notification outbox trong một transaction, lấy alarm ID bằng flush.
2. Scope idempotency theo actor/request, kiểm tra payload fingerprint; retry cùng request trả đúng một alarm, khác payload cùng key trả conflict.
3. Giữ cùng key frontend cho một thao tác đang uncertain/retry; chỉ tạo key mới khi thao tác mới.
4. Có cơ chế DB-backed dispatch/retry delivery chưa nhận ACK qua WebSocket, phục hồi được crash sau commit trước broadcast; không thay realtime bằng polling alarm ở client.
5. ACK received/displayed/audio ghi đúng thời điểm và không giả timestamp trước khi client thực hiện.

**Nghiệm thu:** fault injection trước commit không có alarm mồ côi; crash sau commit có đầy đủ state/audit/outbox và reconnect/dispatch nhận lại đúng một lần ở presentation; concurrent retries tạo một record.

### A3. FIFO và audio session — R03, R06

1. Điều phối thứ tự delivery khi tạo đồng thời; queue merge dedup theo alarm ID và ordering server sequence, không dùng client clock.
2. Audio chỉ bắt đầu khi head ID đổi hoặc retry audio rõ ràng; alarm B/C enqueue không restart A. Có cleanup và playback generation guard cho promise/callback cũ.
3. Play reject báo FAILED, không gọi success started/completed; state/readiness phản ánh chính xác.
4. Audio test dùng file/tone nghe được, await resume/play, có result về server/admin; không làm gián đoạn alarm đang phát.
5. Unlock sau autoplay block có thể tiếp tục alarm hiện tại đúng một lần. Audio readiness có UNKNOWN/NOT_READY/READY, phân biệt browser playback test với xác nhận loa thực.

**Nghiệm thu:** browser test 3 alarm + sync cạnh tranh + duplicate/stale event, repeat/interval đúng, không overlap/restart sai; simulated play rejection không có success audit.

### A4. Cancel contract — R04

1. Thống nhất message schema backend/frontend, broadcast cancellation tới target stations và dashboards.
2. Cancel head dừng audio và tiến queue; cancel pending chỉ remove pending; reconnect reconcile alarm đã cancel.
3. Cancel API idempotent; không tạo n8n cancellation/end notification.

**Nghiệm thu:** hai receiver nhận alarm; global cancel dừng cả hai; local dismiss vẫn độc lập; outbox chỉ chứa event phát alarm theo spec.

### A5. Heartbeat, timeout và restart — R05

1. Timeout đóng đúng socket, identity/race guard đầy đủ; old socket không update heartbeat/state của connection mới.
2. Server startup reconcile station ONLINE cũ về tình trạng thực, ghi disconnect hợp lý; cập nhật online chỉ khi connection thực.
3. Client có heartbeat ACK watchdog/half-open detection và capped reconnect, station sync retry nếu HTTP lỗi nhưng socket còn sống.

**Nghiệm thu:** dừng heartbeat, socket bị đóng, client reconnect và nhận alarm tiếp; socket A timeout không làm mất B; server restart không để thiết bị chết hiện ONLINE.

## Batch B — Hoàn thiện các yêu cầu P1

### B1. Kiosk activation/auth lifecycle — R07, R08

- Tạo luồng station code/token activation trả metadata chính station, không cần user JWT để kiosk boot/refresh.
- Không redirect station 401 sang login user; hiển thị lỗi activation phù hợp.
- Socket lifecycle theo token/user/station identity; login/logout/config change dọn socket/timer cũ; auth revoked/expired xử lý rõ.
- Phân biệt dashboard monitoring với receiver audio theo routing cấu hình.
- Local dismiss khi mất mạng lưu pending action, dừng tại chỗ và retry idempotent; reconnect không replay alarm đã local dismiss đang chờ xác nhận.

### B2. Permission/configuration — R10, R12, R13, R16

- Một nguồn permission ở backend và API effective permissions; UI không suy ra từ JSON cũ, VIEWER không có nút dispatch.
- Admin chỉnh được permission theo khoa/user theo mô hình được chốt, enabled/disabled các cấu hình, ordered multi-file audio sequence/repeat/interval, receiver membership và n8n integration.
- Edit tên receiver group giữ membership; omitted khác explicit empty; alarm target snapshot không đổi theo config sau tạo.
- Soft-disable cấu hình có history, giữ audit/state; rotate/revoke token hoặc disable station đóng socket cũ. Audit mọi config action.
- Chốt lifecycle theo baseline: trạng thái trình chiếu hoàn tất khác cancel sự cố, không tạo workflow xử lý công việc. Nếu giữ global ACTIVE/CANCELLED, phải document mapping/derived presentation completion và xác nhận cách đáp ứng spec, không tự đổi nghiệp vụ từ README.

### B3. Outbox recovery — R09

- Claim/lease/locked_at và reclaim PROCESSING sau crash; due-time query trước limit, exponential capped backoff, attempt audit.
- At-least-once semantics với stable event ID/idempotency cho n8n; không ảnh hưởng core khi n8n down.
- Có quan sát backlog/failure và retry quản trị cho record hết retries; n8n config được lưu/quản trị phù hợp, bảo vệ credential.

### B4. Audit, state validation, security và health — R11, R14, R15

- STATION_EVENT typed allowlist, target authorization, idempotency và transition guards; late AUDIO/RECEIVED không ghi đè DISMISSED/CANCELLED.
- DISPLAYED chỉ lúc head overlay thực sự hiển thị; received/audio timestamps theo ACK; connect/disconnect log có station ID.
- Structured error logging, rollback, config before/after audit, không chứa token/password; DB down xử lý ổn định.
- Production fail-fast secret/database/CORS/demo policy; `.env.example` đầy đủ DEMO_MODE=false và INITIAL_ADMIN_PASSWORD; seed idempotent, production không tự tạo tài khoản demo/khoa cứng.
- Validation enum/length/bounds/FK/color/local audio path, update null đúng, lỗi client trả 4xx.
- Audio upload server-generated filename/path containment/content and size validation; audio_sequence dùng local assets hợp lệ.
- Bảo đảm query device/JWT credentials không bị ghi Nginx/Uvicorn log; đổi auth handshake hoặc redaction phù hợp.
- Health/liveness/readiness phản ánh DB/background tasks và recovery; n8n degraded không khiến core failed.

### B5. Reports và triển khai — R16

- Date filter theo Asia/Ho_Chi_Minh quy đổi UTC, invalid/reversed range trả 4xx; UI hiển thị timezone explicit.
- Tổng hợp theo ngày/tháng/type/department, per-station offline count/duration và average presentation/ack khi dữ liệu đủ; không giả số liệu thiếu.
- SQL aggregation/pagination, XLSX detail sheet per station đầy đủ timestamps/error; xử lý spreadsheet formula từ text input.
- Docker image build frontend tái lập từ checkout sạch, không dựa dist sẵn; external PG network cấu hình rõ; healthchecks/restart/audio persistence.
- Hướng dẫn backup + restore DB/audio và kiểm chứng round trip; ghi rõ single-worker constraint nếu còn dùng WS in-memory.

## Batch C — UI và kiểm thử nghiệm thu

1. Đưa UI về Clinical Control Interface: typography/phân cấp mạnh, ít cards/shadows, bỏ glass/blur trang trí và animation liên tục; giữ full-screen alarm rõ loại/khoa/location/note/dismiss.
2. Responsive với nội dung dài và màn hình Android nhỏ, nút dismiss luôn tiếp cận được, API timeout/loading/errors có thông báo.
3. Thêm meaningful regression tests cho các findings, đặc biệt browser queue/audio/activation/cancel/lifecycle; không chỉ mock assertions trùng implementation.
4. Chạy 50+ rồi 100 kết nối WebSocket thật qua Nginx trên PostgreSQL, có group-in/out, heartbeat, simultaneous alarms, slow/unresponsive client, reconnect và server restart. Ghi latency end-to-end p50/p95/max, lost/duplicate count; mục tiêu LAN bình thường dưới 1 giây theo spec.
5. Test n8n down/crash-retry, DB restart, container restart, audio/config persistence, backup restore, token log scan và acceptance tests 01–25.
6. Test PC và Android/loa thực: boot unattended, autoplay, mất mạng/refresh/reboot, volume/mute/screen sleep. Nếu không có môi trường/thiết bị, ghi BLOCKED cùng bước tái hiện; không ghi PASS từ mock hoặc README.

## Cách bàn giao bắt buộc

Tạo `REDCODE_IMPLEMENTATION_RESULTS.md` gồm:

- Từng finding R01–R16: FIXED/PARTIAL/BLOCKED, file thay đổi và bằng chứng nghiệm thu.
- Commands thực chạy, môi trường Python/browser/PostgreSQL/Docker, số test pass/fail, lỗi còn tồn tại.
- Ma trận acceptance 01–25 với PASS/FAIL/BLOCKED và bằng chứng.
- Hướng dẫn fresh deployment/upgrade/rollback/backup restore; migration bảo toàn dữ liệu.
- Giới hạn vận hành đã kiểm chứng, đặc biệt Android unattended và số worker.

Không kết luận production-ready khi P0/P1 còn lỗi hoặc các acceptance test thiết yếu chưa có bằng chứng. Hoàn thiện theo batch, ưu tiên core trước, không dùng việc build/test mock pass để đóng các mục chưa kiểm thử thực tế.
