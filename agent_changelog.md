# REDCODE — Agent changelog

Lịch sử thay đổi và kiểm chứng. Đặc tả hiện hành duy nhất: `project.md`. Các entry cũ phản ánh thời điểm thực thi, không được coi là yêu cầu hiện hành nếu đã bị thay thế.

## Quy tắc ghi nhận

Sau mỗi đợt thay đổi, bổ sung ngày, yêu cầu, phạm vi/file chính, migration, commands và kết quả thực chạy, giới hạn và việc còn lại. Không ghi PASS nếu chưa chạy; giữ lịch sử cũ. Commit hash của entry mới có thể bổ sung ở đợt sau, không amend commit chỉ để thêm hash.

## 2026-10-06 — Hợp nhất tài liệu

- Chuyển baseline thành `project.md`, bổ sung requirements sau review và quyết định mới của user, cập nhật repository/role/station/expiry/report scope.
- Hai spec cũ có cùng SHA-256 `5B9FA88166A3D0A358708225F7E982767DA053C3F00A69C400B0B55539279482`; giữ một bản baseline, loại bản trùng.
- Hợp nhất kết quả thực thi vào `agent_changelog.md`, giữ finding IDs/trạng thái và bằng chứng; review findings được tóm tắt bên dưới, yêu cầu sửa được đưa vào project.
- Thay thế 5 đường dẫn REDCODE_*: rename spec gốc và implementation results thành hai tài liệu hợp nhất; xóa bản spec trùng, review và execution request sau khi hợp nhất. README được rút gọn và đồng bộ luồng vận hành.
- Kiểm tra tài liệu/tham chiếu và `git diff --check`; không đổi implementation trong đợt hợp nhất.

## Lịch sử Git trước hợp nhất

| Commit | Thay đổi |
|---|---|
| `6ac539b` | Khởi tạo hệ thống: FastAPI/React, auth, stations, alarm, audio, reporting và Docker. |
| `0b59f93` | Permission, idempotency, sync, audit lifecycle và mock concurrent/load tests. |
| `b22c9f0` | Bổ sung station states, notification outbox, sequence/migration và security tests; README mô tả V3 nhưng chưa có spec V3 riêng. |
| `34135ad` | Sửa migration/runtime, transaction/delivery, cancel, audio/reconnect/kiosk, outbox/history/security/report/deployment; thêm regression và review docs. |
| `cfa231a` | Xác nhận receiver bởi Admin, bỏ Viewer, report Admin-only, local diagnostics, hiệu lực alarm và late sync; sửa proxy preview. |

## 2026-10-06 — Review độc lập với implementation ban đầu

- Đối chiếu baseline với source: build PASS, 29 backend tests PASS trên SQLite tạm; Alembic-created DB truy vấn User FAIL `no such column: users.last_login_at`.
- Phát hiện R01 schema mismatch/startup create_all; R02 hai giao dịch alarm; R03 FIFO/audio restart; R04 cancel không tới trạm và gửi n8n ngoài scope; R05 timeout socket sống mất routing; R06 audio readiness/success sai.
- R07 kiosk cần JWT; R08 reconnect/dismiss chưa bền; R09 abandoned PROCESSING; R10 permission hai nguồn/idempotency; R11 timestamp/state/audit; R12 edit group mất membership; R13 hard delete history; R14 production/upload/credential log; R15 health DB error; R16 report/UI/deployment thiếu.
- Docker CLI có, engine không chạy; 50/100 load tests dùng mock socket, không chứng minh tải LAN. Review chi tiết cũ có thể xem trong Git tại `34135ad`; yêu cầu khắc phục hiện nằm trong mục 45 của project.

## 2026-10-06 — Thực thi sửa lỗi (34135ad)

Chi tiết scope và kết quả được giữ dưới đây. Sau đợt này nhiều findings vẫn PARTIAL, chưa production-ready.

## Cập nhật theo yêu cầu: xác nhận thiết bị và thời hạn báo động

Đợt tiếp theo: commit `cfa231a`; yêu cầu user mới được ưu tiên hơn baseline cũ.

- Màn hình trạm bỏ nhập credential thủ công. Admin chọn trạm và xác nhận thiết bị, server tự rotate credential, thu hồi kết nối cũ, trình duyệt lưu identity tự động. Credential vẫn tồn tại nội bộ để kiosk tự khởi động, không hiển thị cho người dùng.
- Chỉ ADMIN/OPERATOR được tạo user/đăng nhập. Viewer cũ bị disable qua migration và startup; history giữ lại. Operator xem alarm log, không truy cập API/UI báo cáo hoặc XLSX.
- Trạm có TEST LOA (âm thanh local), TEST HIỂN THỊ (overlay thử không tạo alarm), TEST KẾT NỐI (WebSocket PING/PONG RTT, timeout 5s). Test bị khóa khi có alarm thật; thực hiện được bằng user khoa trên thiết bị đã Admin xác nhận.
- Alarm type có validity_seconds, mặc định 300, range 10–86400 giây. Mỗi alarm snapshot expires_at; đổi setting không đổi thời hạn alarm đã phát. EXPIRED biểu diễn “CẢNH BÁO ĐÃ PHÁT”, khác CANCELLED. Hết hạn lưu audit, không gửi n8n kết thúc; overlay/audio hết hiệu lực được dừng.
- Trạm đã thuộc target nhưng offline/login sau nhận alarm còn hiệu lực bằng active sync, kèm audio/expiry. Alarm hết hạn hoặc đã dismiss không phát lại.
- Migration `20261006_validity`, backend tests **35 passed**, JS audio tests **3 passed**, build **PASS**. Regression gồm admin-only device confirmation, revoke old token, operator report/XLSX deny nhưng log allow, late station sync, expiry/audit once, validity snapshot, reject VIEWER.
- Database preview riêng đã nâng cấp, giữ dữ liệu demo; không sửa database dự án. Browser/device thực chưa được tự động nghiệm thu.

## Phạm vi đã thực thi

Đã chỉnh backend/frontend/migration/deployment và thêm kiểm tra hồi quy. Chưa hoàn thành toàn bộ Definition of Done production.

## Trạng thái findings

| Finding | Trạng thái | Thực thi và phần còn lại |
|---|---|---|
| R01 Migration | PARTIAL | Migration forward `20261006_runtime` đồng bộ cột ORM, sequence reset theo dữ liệu; Docker chạy Alembic trước Uvicorn. Schema column test và SQLite migrated smoke pass. Cần PostgreSQL thực và đường adoption DB create_all cũ. |
| R02 Atomic alarm | PARTIAL | Flush thay commit sớm; alarm/states/audit/outbox commit cùng nhau; fault injection chứng minh không còn alarm mồ côi. Heartbeat phát SYNC_REQUIRED cho target chưa ACK, giúp phục hồi missed delivery. Recovery chưa bảo đảm deadline dưới 1 giây sau mọi crash. |
| R03 FIFO/audio | PARTIAL | Client dedup/sort server_sequence, effect theo head ID, stale callback generation guard. Cần browser integration và ordering concurrent commit/dispatch server. |
| R04 Cancel | FIXED ở code/test | Gửi ALARM_CANCELLED tới target station và dashboard, cancel idempotent, không enqueue n8n cancellation. API regression xác nhận target gửi và outbox chỉ created. Cần browser/device confirmation. |
| R05 Heartbeat | PARTIAL | Timeout đóng socket và dùng identity; heartbeat socket cũ bị từ chối; startup reset trạng thái persisted; client ACK watchdog. Chưa có network race/restart test thực. |
| R06 Audio | PARTIAL | Reject không báo successful start/completion; session guard; remote tone test không ngắt alarm; resume awaited; local test nghe được; unlock retry head. 3 JS tests pass. Chưa có admin test-result ACK/UNKNOWN enum và thiết bị thực. |
| R07 Kiosk | FIXED ở code/API | POST activate bằng station credential, nhập station code trực tiếp, không bắt user JWT/list station; station 401 không redirect login. API regression pass. Cần browser boot/refresh. |
| R08 Reconnect/dismiss | PARTIAL | Auth token là dependency socket, cleanup guards, watchdog; pending dismiss lưu localStorage/retry lúc sync; dismissed/cancel tombstones. Cần browser integration, revoke dashboard socket ngay, identity-specific pending action cleanup. |
| R09 Outbox | PARTIAL | locked_at lease, reclaim abandoned PROCESSING, SQL due filter, exponential capped retry, stable Idempotency-Key, audit failed attempt. Regression reclaim pass. Còn multi-worker locking, admin retry/backlog/config DB. |
| R10 Permission/idempotency | PARTIAL | API effective types, viewer empty, backend missing permission deny; admin khoa checkboxes; conflict khi key khác actor/payload; frontend giữ request key retry. Còn user-specific permissions, DB key scoped và migration JSON legacy. |
| R11 Audit/state | PARTIAL | Typed allowlist/target/current socket/active alarm/terminal guard, timestamp ACK, station ID connect logs; configuration action audit không chứa body secrets. Còn before/after transactional config audit, lỗi hệ thống đầy đủ, audio-test ACK. |
| R12 Groups | PARTIAL | Edit tên omit station_ids thay vì gửi []; sync/dismiss dựa persisted target snapshot. Chưa có membership editor/read API đầy đủ. |
| R13 History | PARTIAL | DELETE user/department/station/group/alarm type soft-disable; state/history giữ lại; station disable/token update đóng socket. Còn revoke token khi register lại và UI bật/tắt đầy đủ. |
| R14 Production/security | PARTIAL | Fail-fast production secret/PostgreSQL/demo/CORS; production seed chỉ bootstrap admin; .env example thêm demo/admin; enum/repeat/local audio validation; upload UUID + 20MB + extension; WS Nginx access log off, Uvicorn access log off. Còn content MIME sniffing, toàn bộ FK/null/bounds và log-scan thật. |
| R15 Health | PARTIAL | DB check lỗi không tiếp tục count trên DB lỗi; còn task readiness/cached integration probe. |
| R16 Report/UI/deploy | PARTIAL | Ngày Việt Nam→UTC, invalid/reversed range 422, day/month totals, XLSX station detail timestamps/error/formula escaping; multi-line sequence editor không truncate; overlay scroll và bỏ blur; Nginx image build frontend, không mount dist; dockerignore. Còn SQL aggregates, duration/average, n8n admin config, clinical polish, backup restore và PG external network config. |

## Commands và bằng chứng

Môi trường local: Windows, Python 3.14 trong `venv`, SQLite test database riêng dưới `C:/Users/Admin/AppData/Local/Temp/opencode/`, Node test runner, Vite 5.4.21. Không chạy test phá hủy trên `redcode.db` của dự án.

- `python -m pytest tests -q -p no:cacheprovider`: **33 passed**, 3 dependency/config deprecation warnings, 25.90 giây (trước điều chỉnh cuối guard state và dashboard send timeout; kiểm tra targeted bổ sung sau đó).
- `npm test`: **3 passed** — autoplay rejection, callback cũ sau stop, test không interrupt alarm.
- `npm run build`: **PASS**.
- `alembic upgrade head` → `python tests/migration_smoke.py` với startup create_all tắt: **PASS** login/create alarm/XLSX trên schema migrate.
- Migration regression kiểm tra mọi cột mapped ORM tồn tại trên schema Alembic: **PASS**.
- Fault injection trước commit: **PASS**, không còn record alarm theo key injected.
- Activation/cancel/history: **PASS**, activation không JWT, cancel gửi target đúng contract, không n8n cancel, soft-delete station giữ state.
- Abandoned outbox recovery: **PASS**.
- Sau điều chỉnh cuối, targeted migration/regression: **5 passed**, 2 warnings, 2.18 giây. Lần chạy lại trên DB có backlog phát hiện test giả định item mới phải được xử lý ngay trong batch 20; đã sửa assertion kiểm tra recovery độc lập với vị trí backlog, không thay cơ chế worker để chiều test.
- `git diff --check`: **PASS**.

## Giới hạn môi trường / nghiệm thu

Docker CLI có nhưng Docker engine chưa hoạt động trong lượt review; chưa chạy được Nginx/PostgreSQL/container restart end-to-end. Chưa có Android/loa thực hoặc browser automation evidence. Các test tải 50/100 hiện hữu vẫn mock, không được dùng làm bằng chứng acceptance 03 hay latency LAN.

| Acceptance | Trạng thái hiện tại |
|---|---|
| 01–02, 15–17, 21–22 | PASS mức API regression/SQLite cho các trường hợp hiện có; cần production integration |
| 04–05, 09–10, 14, 20, 23 | PARTIAL: code có sửa/test một phần; chưa bằng chứng end-to-end đầy đủ |
| 03, 07–08, 11–13, 18–19, 24–25 | BLOCKED/PENDING kiểm thử mạng/container/browser/device thực |
| 06 | PARTIAL: queue sort/head-only audio và unit tests; chưa concurrent browser FIFO |

## Triển khai và nâng cấp

1. Backup database PostgreSQL bằng pg_dump và copy/archive audio volume trước upgrade; test restore vào database test riêng trước production. Chưa thực hiện restore trên môi trường hiện tại.
2. Cấu hình `.env`: ENVIRONMENT=production, DEMO_MODE=false, PostgreSQL URL đúng, SECRET_KEY riêng >=32 ký tự, origin allowlist cụ thể; fresh install cần INITIAL_ADMIN_PASSWORD.
3. Kết nối backend container vào Docker network của PostgreSQL hiện có (cấu hình external network theo README/Compose). Không tạo PostgreSQL production container mới.
4. `docker compose build` và `docker compose up -d`. Backend image tự chạy `alembic upgrade head`, một worker Uvicorn; Nginx build bundle trong image.
5. Fresh production bootstrap chỉ tạo admin; cấu hình khoa/nhóm/alarm/permission/audio/station từ Admin/API, không dùng demo accounts.
6. Database dev cũ tạo bằng create_all chưa có alembic_version cần được kiểm tra schema trước adoption: nếu đúng runtime ORM, backup rồi stamp revision gốc và chạy forward alignment trên bản sao trước. Không chạy initial migration tạo bảng lên DB có bảng sẵn. Adoption automation còn pending.
7. Migration alignment forward-only; không downgrade bằng drop table. Rollback bằng khôi phục DB/audio backup đã kiểm chứng và image cũ tương ứng.

Không kết luận production-ready. Các phần PARTIAL/PENDING trên cần tiếp tục hoàn thiện và nghiệm thu trước sử dụng production.
