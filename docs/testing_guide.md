# REDCODE — Hướng dẫn kiểm thử và nghiệm thu thực tế

Ngày cập nhật: 2026-10-07. Release tham chiếu `9b01d4a`. Triển khai staging/production theo [production_deployment.md](production_deployment.md); yêu cầu chính thức [project.md](../project.md).

## 1. Các lớp kiểm thử

| Lớp | Chứng minh | Không thay thế |
|---|---|---|
| Backend/JS regression | Authorization, transitions, idempotency, queue logic, error handling | Browser/loa thực |
| Migration trên DB riêng | Fresh/upgrade/history/schema alignment | Restore production nếu chưa drill |
| Live TCP test | Real Uvicorn/WebSocket reconnect/restart/100 clients | Nginx/VLAN/Android/audio physical |
| Staging thực | PostgreSQL + Nginx + browsers + n8n test + network faults | Nghiệm thu inventory thiết bị chưa được thử |
| Site acceptance | PC/Android/loa, boot/refresh/sleep và routing LAN thực | Case còn BLOCKED/PENDING |

Kết quả gần nhất: 49 backend PASS, 8 JS PASS, build PASS; live localhost/SQLite 100 sockets × 10 alarms, lost=0 duplicate=0, p50 0,069s/max 0,369s. Đây là evidence baseline, không phải kết quả của lần chạy tại bệnh viện.

## 2. Chuẩn bị test fixture thực tế

- Stack staging riêng: PostgreSQL DB test riêng trên instance hiện có, audio volume riêng, origin/ports/container names riêng, n8n test hoặc tắt.
- Admin test, Operator khoa A có quyền loại X, Operator khoa B không có quyền X.
- Receiver S1/S2 trong group X; S3 ngoài group X. PC và Android có loa vật lý; ghi browser/OS/version/model.
- Hai loại alarm có audio rõ phân biệt, repeat/interval đã chốt; validity 30–60 giây cho expiry test, 300 giây hoặc đủ lâu cho reconnect/load. Restore lại cấu hình sau test.
- Đồng bộ clocks. Ghi screen/video và server timestamps khi đo latency; không lấy clock không đồng bộ làm bằng chứng.
- Alarm thử dùng note `KIỂM THỬ — KHÔNG PHẢI SỰ CỐ THẬT`, chỉ receiver/group test. Thử gián đoạn production chỉ trong cửa sổ bảo trì có phương án liên lạc thay thế đã thống nhất.
- Evidence che token/password/credential/query WS. Không dùng DB thực cho test destructive.

## 3. Chạy test tự động

### Linux tại root checkout

```bash
python3 -m venv .venv-test
. .venv-test/bin/activate
pip install -r backend/requirements.txt
cd backend
export ENVIRONMENT=test
export DEMO_MODE=true
export DATABASE_URL="sqlite+aiosqlite:///$PWD/ci-unit.db"
export PYTHONIOENCODING=utf-8
alembic upgrade head
pytest tests -v
cd ../frontend
npm ci
npm test
npm run build
```

Chạy trong checkout/test directory riêng; `ci-unit.db` là DB riêng mới, không dùng redcode.db hoặc production URL. Không commit DB tạo ra. Có thể chạy riêng live test:

```bash
cd ../backend
# Chỉ trỏ đến database test RIÊNG. Live test seed/ghi dữ liệu.
export LIVE_TEST_DATABASE_URL='postgresql+asyncpg://<test-user>:<encoded-password>@<host>:5432/<live-test-db>'
pytest tests/test_live_transport.py -v -s
```

Full suite mặc định dùng SQLite unit DB; live test dùng DB tạm nếu không có LIVE_TEST_DATABASE_URL. Với PostgreSQL live test, chuẩn bị DB trống/migratable riêng, không dùng lại dữ liệu lẫn các lần thử. Không set toàn bộ unit suite DATABASE_URL production; một số fixtures sử dụng create_all cho test.

### Windows PowerShell tại backend

```powershell
$env:ENVIRONMENT = 'test'
$env:DEMO_MODE = 'true'
$env:PYTHONIOENCODING = 'utf-8'
$env:DATABASE_URL = 'sqlite+aiosqlite:///C:/Users/Admin/AppData/Local/Temp/opencode/redcode-acceptance-test.db'
..\venv\Scripts\python.exe -m alembic upgrade head
..\venv\Scripts\python.exe -m pytest tests -v
```

Đường dẫn Python/temp phải thay theo máy kiểm thử; parent thư mục phải tồn tại. Chạy frontend commands trong `frontend`. Repo chưa có lint/typecheck script.

### CI

Workflow `.github/workflows/ci.yml` chạy backend/migration, live PostgreSQL 16, frontend test/build và Docker builds. Lưu run URL + commit + kết quả từng job. Workflow tồn tại không đồng nghĩa CI PASS; chưa có run evidence thì ghi PENDING.

## 4. Quan sát trạng thái và audit

- Dashboard Operator: alarm history/global status; Admin: device monitor/audit; `/reports` chỉ Admin.
- Read-only SQL dưới đây chạy bằng DB client của DBA trên test DB; thay ID thật:

```sql
SELECT id, status, server_sequence, created_at, expires_at, cancelled_at
FROM alarms WHERE id = <alarm_id>;

SELECT station_id, state, received_at, displayed_at, audio_started_at,
       audio_completed_at, failed_at, error_message, dismissed_at
FROM alarm_station_states WHERE alarm_id = <alarm_id> ORDER BY station_id;

SELECT station_id, event_type, event_time, metadata
FROM alarm_events WHERE alarm_id = <alarm_id> ORDER BY id;

SELECT id, alarm_id, status, attempt_count, next_attempt_at, locked_at, last_error
FROM notification_outbox WHERE alarm_id = <alarm_id>;
```

State và audit dùng server time. Phát audio trên test script là protocol simulation; nghe thấy loa hoặc browser play evidence mới đóng physical audio acceptance.

## 5. Test cases bắt buộc tại staging/site

### T01 — Authentication và permission

1. Không login gọi API alarms/register: bị từ chối; Operator register/confirm-device: 403.
2. Dashboard WS thiếu/sai/expired JWT, station WS thiếu/sai token: không được chấp nhận; valid credentials kết nối được.
3. Admin xác nhận lại S1: credential cũ bị thu hồi/socket cũ đóng; S1 mới kết nối.
4. Operator khoa A trigger X thành công. Khoa B bị deny; missing permission cũng deny. Admin bỏ/cấp lại quyền A, kết quả đổi tương ứng.
5. Gửi source_department_id của khoa khác bằng API: alarm Operator vẫn gắn khoa của tài khoản.
6. Dismiss thiếu/sai token hoặc S3 ngoài target: 401/403; không thay state/history của S1/S2.
7. Operator reports/XLSX bị 403; Admin truy cập được. VIEWER không tạo/login được.

**PASS:** không có unauthorized alarm/config/state mutation; normalized permissions đúng. Evidence status code, actor IDs và audit (che credentials).

### T02 — Scenario A: nhận/hiển thị/audio

1. S1/S2 đã connected, audio thật enabled; Operator phát X.
2. Kiểm tra tạo station targets ở PENDING với received_at NULL trước ACK (regression/fault-controlled test quan sát được bước rất ngắn này).
3. Browser ACK: RECEIVED → DELIVERED; DISPLAYED → DISPLAYED; play resolve → AUDIO_STARTED; sequence/repeats kết thúc → AUDIO_COMPLETED.
4. Replay mỗi event; gửi RECEIVED/DISPLAYED cũ sau completion: không lùi state, không audit/timestamp duplicate.
5. Gửi AUDIO_COMPLETED trước start trong test protocol: backend không nhận transition nhảy cóc.

**PASS:** timestamps phù hợp sự kiện thực, âm thanh nghe đúng sequence/repeat/interval; không PENDING + received_at non-null; không báo started trước play thành công. Chụp DB sau mỗi bước bằng regression/protocol test, video browser để xác nhận playback thật.

### T03 — Scenario B: local dismiss

Phát X tới S1/S2. S1 dismiss khi audio đang phát và khi đã hoàn tất. S1 dừng overlay/audio; S2 vẫn tiếp tục, global ACTIVE nếu chưa hết hạn. Dismiss lặp không thêm audit lặp. Refresh S1 không replay alarm đã dismiss. Thử S1 mất mạng rồi dismiss: local dừng ngay, reconnect gửi pending action, không replay. Có thể dismiss ở mọi presentation stage, không bắt buộc chờ audio complete.

### T04 — Scenario C: global cancel

Phát A/B trong FIFO; cancel head A: tất cả target dừng A và tiến B. Cancel pending B: chỉ bỏ B, không restart head. Dashboard nhận ALARM_CANCELLED; global CANCELLED, có audit actor. Cancel lặp idempotent. Sau deadline vẫn CANCELLED, không EXPIRED. Outbox chỉ notification created, không end/cancel.

### T05 — Global expiry

Đặt validity 30–60s, phát X. Ghi expires_at snapshot; đổi setting sau tạo không đổi deadline alarm đã phát. Đến deadline: global EXPIRED, UI “CẢNH BÁO ĐÃ PHÁT”, target dừng visual/audio, dashboard được cập nhật; audit EXPIRED đúng một lần. Cancel expired trả 409, không đổi status. Kiểm tra cả monitor expiry và API-triggered expiry; station timer loại alarm hết hiệu lực. Không có n8n end/expiry.

Monitor quét mỗi 5s nên server status/broadcast có thể muộn đến một tick; đo và ghi độ trễ thực. Frontend dùng server offset và quét local queue khoảng 0,5s; lệch clocks phải được ghi/khắc phục.

### T06 — Scenario D: missed alarm/reconnect

1. S1 online nhận A, ngắt mạng S1 (không ngắt server).
2. Phát B khi S1 offline; cancel A. Phát C validity ngắn rồi để C expire.
3. Kết nối lại S1: tự reconnect, active sync lấy B đúng target/FIFO; không A/C, không duplicate B.
4. S3 ngoài group không nhận B. Dismiss B ở S1 rồi refresh: không replay B.
5. Trong staging chặn tạm active-sync HTTP nhưng WS sống, bỏ chặn: sync retry phải nhận ACTIVE còn thiếu.
6. Mở/reload profile S1 để socket B thay A: cleanup A không đánh dấu socket mới offline; heartbeat/alarm mới vẫn tới.

**PASS:** không mất ACTIVE, không phát lại CANCELLED/EXPIRED/DISMISSED; Admin OFFLINE/ONLINE đúng. Offline phát hiện thường sau threshold 15s + monitor tick tối đa 5s; ghi elapsed, không yêu cầu chính xác 15,000s.

### T07 — Scenario E: audio failure và retry

Trên browser profile thử, chặn autoplay hoặc dùng audio path test bị 404. Phát X: visual vẫn xuất hiện; UI báo error, state FAILED có error/server timestamp, không successful start nếu play reject, không completion giả. Cho phép autoplay/sửa asset và thử bật audio: chỉ successful start sau play resolve, kết thúc mới complete; giữ failure audit. Test stale callbacks không tiến queue/restart alarm khác.

Thử mute/loa rút dây riêng: browser có thể báo play success dù không nghe loa. Ghi **FAIL physical audio**; không dùng READY để kết luận loa hoạt động.

### T08 — Scenario F: n8n down/retry/crash

1. Endpoint n8n test ngừng hoặc trả 500/timeout; trigger/display/audio core vẫn hoạt động.
2. Outbox lưu attempt/error/next_attempt_at; retry 2s/4s… theo attempt (worker poll khoảng 2s), hết max retries giữ FAILED.
3. Fault-injection trên test worker tại claim sau persist PROCESSING/locked_at nhưng trước I/O: kill process, restart. Sau lease timeout 5 phút, item quay queue hoặc FAILED nếu exhausted; không PROCESSING mãi.
4. n8n nhận thành công: SENT, sent_at có, locked_at/next_attempt_at cleared.
5. Simulate server chết sau n8n nhận nhưng trước SENT commit: retry có cùng Idempotency-Key; workflow n8n dedup side effect.

Repo tự động test claim/crash/recovery; để tái hiện live cần test harness/pause tại điểm claim, không kill ngẫu nhiên rồi coi đã chứng minh đúng điểm lỗi. Semantics at-least-once, không tuyên bố exactly-once. Case crash ở attempt cuối có thể exhausted FAILED, cần quy trình xử lý backlog.

### T09 — Scenario G: restart và dữ liệu bền vững

Trên staging: phát ACTIVE validity đủ lâu, ghi state/audit/outbox, restart backend. Stations reconnect/sync ACTIVE; startup reconcile ONLINE cũ, outbox tiếp tục; local dismissed/cancelled/expired không replay. Restart Nginx/container stack; kiểm tra audio/config/history vẫn giữ. Restart PostgreSQL trong cửa sổ test riêng: server phục hồi DB, không mất dữ liệu hoặc tạo duplicate do retry. Restore drill DB/audio theo runbook deployment và đối chiếu counts/hashes.

### T10 — Scenario H: tải 50/100 trạm và FIFO

- Chạy auto live test trước; tiếp theo test qua **Nginx entrypoint thực** với PostgreSQL staging, 50 rồi 100 real sockets. Test có sẵn boot Uvicorn trực tiếp; không tự nhận nó là Nginx test. Harness LAN cần kết nối URL entrypoint và provision 100 stations test bằng Admin API, không dùng token dự đoán.
- 10 alarm liên tiếp, cả simultaneous requests; group-in/out; một slow/unresponsive client, heartbeat, reconnect, cancel/expiry trong lúc offline.
- Mỗi receiver ghi alarm IDs/sequences, ACK/queue position; đo thời điểm server nhận request đến receiver event và visual/audio thật trên mẫu PC/Android. Ghi p50/p95/max, lost/duplicate, latency theo từng client.
- Queue presentation FIFO theo server_sequence; alarm mới enqueue không restart head, không audio overlap. Concurrent commit/delivery cần browser evidence, không chỉ sort array unit test.

**PASS:** target routing đúng, không lost ACTIVE/duplicate presentation, không lùi state; LAN bình thường mục tiêu event delivery dưới 1 giây. Ghi thất bại/ngoại lệ slow clients riêng, không loại bỏ khỏi báo cáo.

### T11 — Report/date/XLSX

Trên DB test, tạo records có server timestamps quy đổi từ giờ bệnh viện: ngay trước ngày đầu, đúng 00:00:00, 23:59:59.123456 ngày cuối, đúng 00:00:00 ngày kế. Chạy cùng ngày, nhiều ngày, 31/10→01/11 và 31/12→01/01. Summary/offline events/XLSX phải lấy [ngày đầu 00:00, ngày kế sau ngày cuối 00:00), không lấy boundary ngày kế. Kiểm tra invalid/reversed range 422, timestamps UTC/local rõ, station detail/error và text bắt đầu `= + - @` không thành công thức Excel.

### T12 — Migration/startup/security logs

Fresh test PostgreSQL `alembic upgrade head` → login/provision/trigger/dismiss/report. Upgrade bản sao DB release cũ giữ counts/history/permissions; normalized explicit deny không bị legacy JSON override; invalid JSON IDs không mở quyền. Kiểm tra Alembic current/schema/unique idempotency/PostgreSQL sequence, concurrent retry một alarm. Production startup không tự create_all. Scan Nginx/Uvicorn/upstream proxy logs: không JWT/device credentials/password thật. Không chạy downgrade giả; rollback thử bằng backup.

### T13 — PC/Android unattended

Trên từng model/profile: reboot/auto-launch `/kiosk`, refresh, mất mạng/reconnect, server restart, Internet disconnected nhưng LAN còn, volume/mute/loa, screen sleep/lock. Alarm phải rõ/touch dismiss dễ với note dài, không che nút; audio local nghe đúng. Ghi thời gian từ power-on đến ready. Lưu credential qua reboot nhưng không lộ UI/log. Chạy soak test qua ca trực thực tế theo thời lượng đơn vị chốt; ghi reconnect/errors/CPU browser/disk server nếu có triệu chứng.

## 6. Ma trận baseline acceptance 01–25

| Baseline | Case runbook |
|---|---|
| 01–02 Permission | T01 |
| 03 50+ connections | T10 |
| 04–05 Receiver routing | T01/T06/T10 |
| 06 FIFO | T02/T04/T10 |
| 07–08 Network/server reconnect | T06/T09 |
| 09–10 n8n down/log | T08 |
| 11–12 Offline/online monitor | T06/T09 |
| 13 Offline Internet audio | T13 |
| 14 Admin audio test | T13: remote audio-test và test tại trạm, người tại loa xác nhận |
| 15–16 Local dismiss/history | T03 |
| 17 XLSX | T11 |
| 18–19 DB/container persistence | T09 |
| 20 Browser refresh identity | T06/T13 |
| 21 Duplicate requests | T12 và backend concurrency regression |
| 22–23 Unauthorized/log secrets | T01/T12 |
| 24–25 PC/touch Android UI | T13 |

## 7. Mẫu biên bản kiểm thử

```text
Release commit / image tags:
Alembic revision:
Ngày / người thực hiện:
Topology: server / PG version / Nginx / VLAN / origin:
Thiết bị: OS / model / browser / loa / launcher:
Case ID / Scenario:
Preconditions và fixture IDs:
Steps thực chạy:
Expected:
Actual:
Result: PASS / FAIL / BLOCKED / PENDING
Alarm IDs / station IDs / server timestamps:
Latency p50 / p95 / max; lost / duplicate:
Evidence files / CI run URL (đã che secrets):
Lỗi / cách tái hiện / owner / hạn xử lý:
Cleanup / config đã phục hồi:
```

Không ghi PASS nếu chỉ có README/build/mock. Bất kỳ delivery/audio/routing/data integrity blocker hoặc case thiết yếu BLOCKED phải giữ trong danh sách việc còn lại; quyết định bàn giao dựa trên evidence thực của môi trường bệnh viện, không suy từ test local.
