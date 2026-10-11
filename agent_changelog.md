# REDCODE — Agent changelog

Lịch sử thay đổi và kiểm chứng. Đặc tả hiện hành duy nhất: `project.md`. Các entry cũ phản ánh thời điểm thực thi, không được coi là yêu cầu hiện hành nếu đã bị thay thế.

## Quy tắc ghi nhận

Sau mỗi đợt thay đổi, bổ sung ngày, yêu cầu, phạm vi/file chính, migration, commands và kết quả thực chạy, giới hạn và việc còn lại. Không ghi PASS nếu chưa chạy; giữ lịch sử cũ. Commit hash của entry mới có thể bổ sung ở đợt sau, không amend commit chỉ để thêm hash.

## 2026-10-11 — Sửa loạt lỗi P0 về kết nối, phục hồi và tính trung thực của trạng thái; nghiệm thu trên Docker

Yêu cầu: "đã chạy docker engine. hãy thực thi" — Docker engine đã hoạt động nên thực thi loạt sửa P0 đã rà soát và dùng Docker cho phần kiểm chứng trước đây bị chặn. Theo định hướng: "Tiếp tục bổ sung và chạy các bài kiểm thử liên quan đến những phần code đang chỉnh sửa. Không tuyên bố đã kiểm chứng thiết bị thực tế nếu mới chỉ chạy automated tests."

Không có migration mới, không đổi schema. Không tạo container PostgreSQL nào (không tồn tại container PostgreSQL trong môi trường này); stack nghiệm thu chạy trên SQLite trong volume tạm, đã gỡ sạch sau khi xong.

### Thay đổi

**Tính trung thực của trạng thái trạm** — nhóm lỗi nguy hiểm nhất vì nó khiến người trực tin một thiết bị đang sẵn sàng trong khi thiết bị đó không hú được:

- `app/api/stations.py` (nhịp tim HTTP): chỉ ghi `audio_ready`/`client_ready` khi trạm **thật sự có WebSocket**. Trước đây nhịp tim HTTP không có socket vẫn ghi `audio_ready=True` lên bảng trạm, nên dashboard hiện "AUDIO READY" cho thiết bị gửi nhịp tim bằng đường mạng khác (WiFi còn, cáp LAN đứt) — loa không hề kêu.
- `app/api/stations.py` (đăng ký lại trạm): chỉ đóng socket khi **credential thật sự đổi**. Trước đây endpoint luôn đóng 1008, nên chỉ cần admin sửa tên/vị trí một trạm là mọi thiết bị đang trực của trạm đó rơi vào trạng thái "credential bị từ chối", dừng thử lại vĩnh viễn.
- `app/api/stations.py` (`PUT /{station_id}`): ghi lại mã trạm **cũ** trước khi ghi đè, và đóng socket dưới mã cũ kèm lý do đọc được. Trước đây socket mồ côi dưới mã cũ không bao giờ nhận được báo động phát theo mã mới, nhưng vẫn được vòng giám sát coi là trạm đang sống.
- `app/api/health.py`: `websocket` phản ánh trạng thái vòng giám sát nhịp tim thay vì hằng số `"ok"`. Vòng giám sát chết nghĩa là trạm rút điện vẫn hiện ONLINE mãi mãi — đúng loại hỏng im lặng endpoint này tồn tại để phát hiện.

**Mất báo động và đá nhầm phiên**:

- `app/core/websocket_manager.py` (`connect_station`): socket cũ bị đóng bằng mã **4001 "Station session superseded"** thay vì 1000. Đóng sớm ở đây thay cho việc để handler cũ tự phát hiện, nên mã 1000 khiến client coi là đóng bình thường và thử lại sau ~1 giây — hai thiết bị mở cùng mã trạm đá nhau liên tục, mỗi vòng kèm một lượt ghi DB và broadcast. 4001 cho client biết phải chờ lâu (15 giây) và hiện cảnh báo.
- `app/core/websocket_manager.py` (`broadcast_alarm`): cleanup socket chết truyền kèm danh tính socket. Trước đây gọi `disconnect_station(code)` không danh tính, bị guard danh tính từ chối, nên xác socket nằm lại trong `active_stations` vĩnh viễn và mọi báo động sau đó lại thử gửi vào nó, tốn trọn 1 giây timeout mỗi lượt.
- `app/core/websocket_manager.py`: thêm thuộc tính `monitor_running` để `/api/health` đọc được trạng thái vòng giám sát.

**Phía frontend** (đã có từ đợt trước, ghi lại đây cho đủ): backoff có jitter + sàn 15 giây cho xung đột phiên (`utils/reconnect.js`), chỉ ACK những báo động thật sự vào hàng đợi hiển thị (`utils/alarmQueue.js`), `verifyPlayback()` chứng minh khả năng phát bằng đúng đường `<audio>` mà báo động thật dùng (`utils/soundPlayer.js`), thông báo sau khi phát phản ánh số trạm thật sự nhận (`OperatorDashboard.jsx`), và cảnh báo khi trạm bị phiên khác chiếm chỗ (`ReceiverStationView.jsx`).

**Hạ tầng phục vụ âm thanh**: `nginx/default.conf` khai báo tường minh kiểu media cho `/assets/audio/`. `mime.types` mặc định của nginx không map `.wav`, nên tệp còi được trả về dưới dạng `application/octet-stream` — trình duyệt có quyền từ chối phát một `<audio>` không có kiểu media hợp lệ, nghĩa là trạm hiện báo động mà loa không kêu.

### Test bổ sung

- `backend/tests/test_p0_regressions.py` (mới, **14 test**): mỗi test tái hiện một lỗi có thật đã sửa — nhịp tim HTTP nói dối về kênh nhận báo động, entry nhịp tim mồ côi, guard danh tính socket, socket cũ không đá được socket mới, `connect_station` không giữ lock khi đóng socket cũ, đếm số trạm đã nhận thật, phát lại báo động đã kết thúc, đóng 1008 khi đổi credential/đổi mã trạm, `/api/health` báo `degraded` khi vòng giám sát chết, và loại báo động bắt buộc có tệp âm thanh.
- `frontend/tests/reconnect.test.js` (mới, 4 test) và bổ sung vào `alarmQueue.test.js`, `soundPlayer.test.js`.

### Commands/bằng chứng thực chạy

- `python -m pytest tests -q -p no:cacheprovider` trên **DB SQLite tạm mới** (`DATABASE_URL=sqlite+aiosqlite:///$TEMP/rc_full.db`) → **69 passed**, 4 warnings, 65.42s.
- Riêng `tests/test_p0_regressions.py` → **14 passed**, 5.72s.
- `npm test` (frontend) → **19 passed, 0 fail**.
- `npm run build` → **PASS** (281.81 kB js / 29.40 kB css, 1500 modules).
- `docker compose build` → **exit 0**, cả `redcode-backend` và `redcode-nginx` build thành công.
- `docker compose up` với override tạm (ENVIRONMENT=development, SQLite trong volume tạm) → cả hai container `Up`. Log backend: **toàn bộ chuỗi Alembic chạy trên DB trắng** (`8280022f67e9 → 20261006_runtime → 20261006_validity → 20261007_permissions → 20261007_integrations`), seed demo thành công, `Station offline monitor active`, `Durable notification outbox worker active`.
- `GET /api/health` qua nginx → `{"status":"ok","database":"ok","websocket":"ok","n8n":"disabled","active_stations":0,"total_stations":5}`. `GET /` → HTTP 200 (797 B, SPA index).
- **Khói kiểm thử end-to-end qua nginx** (`$TEMP/rc_e2e_smoke.py`, script tạm chạy ngoài repo) → **23/23 đạt**: đăng nhập admin, đăng ký trạm, tạo nhóm nhận + loại báo động, WebSocket trạm kết nối, health đếm đúng trạm đang trực, phát báo động 201, `target_station_count=1`, `delivered_station_count=1`, trạm nhận `ALARM_TRIGGERED` kèm `server_sequence` và `expires_at`, gói có `audio_sequence`, phát lại cùng `idempotency_key` trả đúng báo động cũ, báo động thứ hai vào hàng đợi đúng thứ tự (5 → 6), trạm nhận báo động thứ hai, `DISPLAYED`/`AUDIO_STARTED` được ghi nhận, hủy báo động 200, trạm nhận `ALARM_CANCELLED`, phát lại sau khi kết thúc bị từ chối **409**, kết nối lại nhận `SYNC_REQUIRED`, đồng bộ trả đúng báo động còn hiệu lực, phiên trạm cũ bị đóng bằng **4001 "Station session superseded"**, nhịp tim token sai bị từ chối **401**, nhịp tim HTTP trả `websocket_connected=false`/`can_receive_alarms=false`.
- **Khói kiểm thử khởi động lại** (`$TEMP/rc_e2e_restart.py`) → **8/8 đạt**: trạm ONLINE + AUDIO READY trước khi khởi động lại; `docker compose restart backend`; server khoẻ lại; cờ `websocket_connected` và `audio_ready` cũ **đã bị xóa**; trạm hiện OFFLINE; kết nối lại nhận `SYNC_REQUIRED`; báo động còn hiệu lực vẫn đồng bộ được (`ids=[7]`); trạm kết nối lại được đánh ONLINE.
- `curl /assets/audio/red_code_1.wav` qua nginx → `status=200 type=audio/wav` (trước khi sửa: `application/octet-stream`).
- Dọn dẹp: `docker compose down -v` — đã gỡ cả hai container, network và hai volume (`redcode_audio_data`, `rc_smoke_data`). `docker ps -a` trở lại đúng trạng thái ban đầu (chỉ còn `metabase`, `c-mssql` đều `Exited`). `backend/redcode.db` của dự án không bị chạm tới.
- Commit `a8c74e2`, push `main` (`3f7cb15..a8c74e2`). Truy vấn GitHub API: run **`38114856575`**, head_sha `a8c74e2`, `status: completed`, `conclusion: **success**`. Trích conclusion từng job — **cả ba job success, không step nào bị skip**:
  - `backend`: 12 step, success, skipped `[]`
  - `frontend`: 9 step, success, skipped `[]`
  - `docker`: 6 step, success, skipped `[]`

### Giới hạn

- **Chưa nghiệm thu trên thiết bị thật.** Toàn bộ bằng chứng ở trên là automated test và container; **chưa có** PC Windows kiosk, tablet Android hay Android TV box nào chạy thử. Các tuyên bố về phát âm thanh thực tế, chặn autoplay của trình duyệt, và độ trễ trên LAN 50–100 thiết bị **vẫn chưa có bằng chứng**.
- **Chưa chạy trên PostgreSQL thật.** Không có container PostgreSQL trong môi trường này và định hướng không cho tạo mới; stack nghiệm thu chạy SQLite. Chuỗi Alembic đã chạy thật trên DB trắng nhưng trên SQLite.
- **Chưa diễn tập sao lưu/phục hồi** (`pg_dump` khứ hồi) vì không có database PostgreSQL của REDCODE để diễn tập.
- **Chưa kiểm chứng "n8n chết không ảnh hưởng báo động" ở mức thiết bị thật**; `tests/test_n8n_integration.py` chỉ kiểm tra ở mức API/outbox.
- `main.py` vẫn chạy `UPDATE users SET enabled=false WHERE role='VIEWER'` mỗi lần khởi động. Đây là dọn tài khoản VIEWER cũ đã bị khai tử (vai trò này không còn tạo được qua API — `test_station_validity.py` khẳng định trả 422), giữ nguyên có chủ ý, không phải lỗi mới.
- Nhánh `fix/lan-field-bugs-and-test-harness` vẫn còn ở local và remote (đã merge xong).

## 2026-10-11 — Gỡ wizard thiết lập database và trang Admin n8n, cấu hình chỉ bằng `.env`

Yêu cầu: tài liệu định hướng phát triển mới ("CẬP NHẬT ĐỊNH HƯỚNG PHÁT TRIỂN REDCODETHIENHANH") — PostgreSQL là DB bắt buộc, chỉ kết nối qua `DATABASE_URL`, "cấu hình kết nối một lần khi triển khai", "không cần phát triển thêm cơ chế cài đặt hoặc quản lý database phức tạp"; n8n là tích hợp bổ sung cấu hình bằng webhook URL trong `.env`, "không cần trang Admin quản lý kết nối n8n". Hai câu hỏi kiến trúc đã được xác nhận trước khi thực hiện: **gỡ hẳn wizard, chỉ dùng `.env`** và **chuyển n8n sang `.env`, bỏ trang Admin**.

Đây là thay đổi có nguy cơ phá chức năng đang chạy (đọc `runtime.json` bị gỡ → JWT ký bằng `SECRET_KEY` do wizard lưu sẽ mất hiệu lực), nên đã giải thích ngắn và **xin xác nhận trước khi thực hiện** theo mục 7 của định hướng.

### Thay đổi

- **Gỡ wizard thiết lập database**: xóa `backend/app/bootstrap.py`, `backend/app/api/settings.py`, `backend/app/core/integration_settings.py`, endpoint `/api/setup/status` trong `app/main.py`, trang `frontend/src/pages/InitialSetup.jsx` và route `/setup` trong `App.jsx`.
- **`backend/start_server.py`**: bỏ nhánh `while True` phục vụ trang thiết lập; nay chỉ chạy `alembic upgrade head` rồi `uvicorn` một worker.
- **`backend/app/config.py`**: gỡ toàn bộ khối override từ `runtime.json` (và các import `os`, `json`, `Path` nay không dùng). Thêm `N8N_ENABLED`; validator bổ sung `N8N_ENABLED=true` bắt buộc có `N8N_WEBHOOK_URL`.
- **n8n qua biến môi trường**: `alarms.py` chỉ ghi outbox khi `settings.N8N_ENABLED`; `n8n_outbox.py` thoát sớm khi tắt, dùng `N8N_MAX_RETRIES`/`N8N_TIMEOUT_SECONDS`/`N8N_WEBHOOK_URL` từ settings; `health.py` báo `disabled` khi tắt và không bao giờ để trạng thái n8n kéo trạng thái chung xuống.
- **Gỡ trang Admin n8n**: xóa `frontend/src/pages/IntegrationSettings.jsx`, route `/admin/settings` và link trong `AdminDashboard.jsx`.
- **`IntegrationSettings`** giữ lại trong `models/__init__.py` kèm docstring: bảng còn trong schema nhưng không đọc/ghi nữa, migration forward-only nên không drop.
- `docker-compose.yml`: bỏ volume `redcode_config`/`redcode_runtime_config` (không còn runtime config để giữ).
- `.env.example`, `README.md`, `docs/production_deployment.md`, `docs/production_deployment_flow.md`: cập nhật theo luồng mới.
- Test: xóa `test_optional_setup.py`, thêm `backend/tests/test_n8n_integration.py` (6 test) và viết lại `conftest.py` để bật n8n bằng cách sửa `settings` thay vì ghi bảng.

### Commands/bằng chứng thực chạy

- Baseline trước thay đổi: `git stash push -u` rồi chạy HEAD → **52 passed** (DB SQLite tạm mới).
- `python -m pytest tests -q -p no:cacheprovider` trên DB SQLite tạm mới → **55 passed**, 4 warnings, 59.32s.
- Chạy lại đúng dạng lệnh CI `pytest tests -q` → **55 passed**.
- `npm test` (frontend) → **8 passed**, 0 fail.
- `npm run build` → **PASS** (278.62 kB js / 29.11 kB css).
- `import app.main` → OK; OpenAPI có **34 path**, không còn path `setup`/`settings`/`integration` nào.
- Kiểm tra validator: production + `DATABASE_URL=""` → `ValidationError: Production requires a postgresql+asyncpg:// DATABASE_URL and DEMO_MODE=false...`; `N8N_ENABLED=true` + `N8N_WEBHOOK_URL=""` → `ValidationError: N8N_ENABLED=true requires N8N_WEBHOOK_URL`.
- `grep` xác nhận không còn import `integration_settings`/`app.bootstrap`/`api.settings` trong `app/`, `tests/`, `start_server.py`.
- Commit `80626c6`, push `main` (`6e6f60f..80626c6`). Truy vấn GitHub API: run **`38110812679`**, head_sha `80626c6f77deec93c3807679e45eb67b06200399`, `status: completed`, `conclusion: **success**`. Trích conclusion từng step — **cả ba job success, không step nào bị skip**:
  - `backend`: `Initialize containers`, `Create live transport database`, `alembic upgrade head`, `pytest tests -v`, `Stop containers` — success
  - `frontend`: `npm ci`, `npm test`, `npm run build` — success
  - `docker`: build `backend/Dockerfile` và `nginx/Dockerfile` — success
- Commit `aad7157` (bản ghi này), push `main` (`80626c6..aad7157`): run **`38110903346`**, head_sha `aad7157`, `completed success`, cả ba job `backend`/`frontend`/`docker` đều success.

### Giới hạn

- **Chưa chạy trên Docker/PostgreSQL thật** — Docker engine vẫn chưa hoạt động ở môi trường này, nên luồng `start_server.py` mới chỉ được xác nhận bằng đọc code và import, chưa bằng một lần `docker compose up` thật.
- Lỗi `no such column: alarm_types.validity_seconds` khi chạy trên `backend/redcode.db` cũ là **có trước thay đổi này** (đã chứng minh bằng cách stash và chạy HEAD trên cùng DB cũ → lỗi y hệt). Suite cần DB sạch.
- Bảng `integration_settings` vẫn nằm trong schema; dữ liệu cấu hình n8n cũ trong đó nay không còn được đọc.
- Định hướng mới yêu cầu **không mở rộng n8n thành hệ thống quản lý tích hợp riêng** — việc gỡ trang Admin là bước đi theo hướng đó; phần kiểm chứng "n8n chết không ảnh hưởng báo động" ở mức thiết bị thật vẫn chưa có.
- Không thay đổi schema, không migration mới.
- **CI xanh không thay thế nghiệm thu Docker thật**: job `docker` chỉ *build* image, không `docker compose up` với `.env` production, nên đường `start_server.py` mới vẫn chưa chạy thật lần nào.

## 2026-10-11 — Merge nhánh sửa lỗi vào `main`, `main` xanh trở lại

Yêu cầu: "merge vào main". `main` trước đó **đang đỏ**: hai lần chạy Actions gần nhất trên `main` (`9b01d4a`, `d214577`) đều `failure`. Đợt này đưa toàn bộ đợt sửa lỗi LAN + hạ tầng test vào `main` và xác nhận `main` xanh trở lại.

### Thay đổi

- Không sửa file. Merge thuần túy.
- `git checkout main` → `git merge --ff-only fix/lan-field-bugs-and-test-harness`: **fast-forward**, nhánh đi trước 4 commit và không tụt lại (`0 4`), nên không xung đột và không sinh merge commit.
- `git push origin main`: `d214577..deaac54`. `main` và nhánh nay cùng trỏ `deaac54`.
- 13 file vào `main`, trong đó 5 file mới: `backend/pytest.ini`, `backend/tests/live_server.py`, `backend/tests/ws_reject_probe.py`, `docs/production-readiness.html`, `frontend/src/utils/uuid.js`.

### Commands/bằng chứng thực chạy

- `git merge --ff-only` → fast-forward, 13 files changed, 1409 insertions(+), 43 deletions(-).
- `git status --short` sau merge → sạch.
- Truy vấn GitHub API: run **`38104084659`**, branch `main`, head_sha `deaac544`, `status: completed`, `conclusion: **success**`.
- Trích conclusion từng step — **cả ba job success**, không step nào bị skip:
  - `backend`: `Initialize containers`, `Create live transport database`, `alembic upgrade head`, `pytest tests -v`, `Stop containers` — success
  - `frontend`: `npm ci`, `npm test`, `npm run build` — success
  - `docker`: build `backend/Dockerfile` và `nginx/Dockerfile` — success

### Giới hạn

- Vẫn **chưa tải được log chi tiết job** (`gh` chưa đăng nhập) — kết luận từ trạng thái từng step qua API công khai.
- Nhánh `fix/lan-field-bugs-and-test-harness` **vẫn còn** trên local và remote (chưa xoá) — có thể xoá nếu không cần giữ.
- Chưa có PR: merge trực tiếp bằng fast-forward theo yêu cầu, không qua review.
- Không thay đổi schema, không migration mới.

## 2026-10-09 — Push nhánh và xác nhận CI xanh trên GitHub Actions

Yêu cầu: "push code cho tôi". Đợt này **không sửa code sản phẩm lẫn hạ tầng test** — chỉ push nhánh đã commit và ghi nhận bằng chứng Actions, mục đích là gỡ chặn cứng "CI chưa có bằng chứng chạy thật" của Cổng 1 (mọi bằng chứng trước đó đều là chạy tay mô phỏng đúng lệnh CI).

### Thay đổi

- Không có thay đổi file. Nội dung push là các commit đã ghi ở hai entry dưới: `f778ab2` (harness test), `e4c6dee` (lỗi LAN thực địa), `fadb30f` (tài liệu).

### Commands/bằng chứng thực chạy

- `git push -u origin fix/lan-field-bugs-and-test-harness` → thành công; remote trả link mở PR `https://github.com/buinguyenhong/REDCODETHIENHANH/pull/new/fix/lan-field-bugs-and-test-harness`.
- `gh auth status` → **chưa đăng nhập host GitHub nào**, nên không dùng được `gh run view`.
- Truy vấn GitHub API công khai: `total_count: 3`, run id **`37915373273`**, name `Redcode CI`, head_branch `fix/lan-field-bugs-and-test-harness`, head_sha **`fadb30fa56cefaf2275228865874fef725ac803b`**; poll tới khi kết thúc → **`completed success`**.
- Tải `jobs` JSON và trích conclusion từng step — **cả ba job success**:
  - `frontend`: `npm ci`, `npm test`, `npm run build` — success
  - `docker`: `docker build -f backend/Dockerfile -t redcode-api:ci .`, `docker build -f nginx/Dockerfile -t redcode-nginx:ci .` — success
  - `backend`: `Create live transport database`, `alembic upgrade head`, `pytest tests -v` — success

### Giới hạn

- **Chưa tải được log chi tiết của job**: endpoint `/actions/jobs/<id>/logs` đòi xác thực, mà `gh` chưa đăng nhập, nên **số test in trong log Actions chưa đối chiếu được**. Kết luận ở trên lấy từ trạng thái từng step qua API công khai, không phải từ nội dung log.
- **Chưa merge vào `main`** — nhánh vẫn đứng riêng, chờ quyết định.
  - *Cập nhật 2026-10-11:* đã merge fast-forward vào `main`; xem entry "Merge nhánh sửa lỗi vào `main`, `main` xanh trở lại" ở đầu file.
- Không thay đổi schema, không migration mới, không ảnh hưởng code sản phẩm.

## 2026-10-09 — Tổng hợp phiên: từ lỗi thực địa LAN tới hạ tầng kiểm thử

Phiên này bắt đầu bằng việc chạy thử LAN nhiều thiết bị và kết thúc ở hạ tầng kiểm thử. Bốn đợt dưới đây đi theo đúng trình tự đó; mục này tóm tắt mạch xử lý để đọc liền lạc.

**Bối cảnh.** Chạy hệ thống ở dev mode (`uvicorn` + Vite) để nhiều thiết bị cùng LAN đăng nhập thử. Hai lỗi lộ ra chỉ vì truy cập từ máy khác qua `http://<LAN-IP>:5173`, không phải `localhost`.

**Đợt 1 — lỗi thực địa.** `crypto.randomUUID()` chỉ tồn tại trong secure context (HTTPS hoặc `localhost`), nên mọi máy trạm thật gặp `crypto.randomUUID is not a function`; thay bằng `randomId()` có fallback. Cùng lúc, WS gateway từ chối credential bằng `close()` trước `accept()` khiến ASGI trả HTTP 403 và trình duyệt quy về mã đóng 1006 không kèm lý do — credential sai **không phân biệt được** với mất mạng, nên trạm thử lại vô hạn trong im lặng. Sửa thành `accept()` rồi `close(1008, reason)`, và phía client dừng vòng retry để báo rõ. Bằng chứng trước/sau trên uvicorn thật: **0/5 → 5/5** đường từ chối trả 1008 kèm lý do.

**Đợt 2 — kiểm chứng PostgreSQL thật.** Dựng PostgreSQL 16.15 bằng Docker để gỡ caveat "toàn bộ test mới chỉ chạy trên SQLite". `alembic upgrade head` chạy **5/5 migration** trên schema sạch (lần đầu tiên trên PostgreSQL) và toàn bộ suite **52 passed**. Phát hiện kèm theo: harness test không chạy nổi trên PostgreSQL pool thật — **12 failed / 10 passed / 30 errors** — vì `TestClient` và pytest-asyncio dùng event loop khác nhau, khiến connection dùng chéo loop.

**Đợt 3 — vá harness và gỡ lỗi chặn CI.** Sửa tận gốc bằng `pytest.ini` (ghim loop ở mức session) và chuyển hai test WebSocket sang uvicorn thật. Trong lúc kiểm chứng, phát hiện thêm một lỗi **có từ trước**: CI gọi `pytest tests -v`, cách gọi này không thêm thư mục hiện hành vào `sys.path` nên job backend chết ngay ở `ModuleNotFoundError: No module named 'app'` — **chưa từng chạy được test nào**. CI nay chạy trên PostgreSQL, và cả ba job đã được chạy tay xác nhận xanh.

**Đợt 4 — push và xác nhận CI trên GitHub Actions.** Push nhánh lên remote, Actions chạy run `37915373273` trên head `fadb30f`: **cả ba job success**. Chặn cứng "CI chưa có bằng chứng chạy thật" nay **đã gỡ** — xem entry trên cùng.

**Còn lại.** Hai chặn cứng của Cổng 1 chưa gỡ: chưa chứng minh backup/restore, chưa dựng stack production bằng `docker compose up`. Chi tiết từng đợt ở các entry dưới.

## 2026-10-09 — Vá harness test: chạy được trên PostgreSQL và gỡ lỗi chặn CI

Tiếp nối đợt kiểm chứng PostgreSQL ngay dưới. Đợt đó phát hiện harness test không chạy nổi trên PostgreSQL pool thật; đợt này sửa tận gốc và tìm thêm một lỗi khiến job CI **chưa từng** chạy được.

### Thay đổi

- `backend/pytest.ini` (mới) — ba dòng, mỗi dòng gỡ một lỗi thật:
  - `pythonpath = .`: CI gọi `pytest tests -v`, cách gọi này **không** thêm thư mục hiện hành vào `sys.path` (khác `python -m pytest`). Thiếu dòng này, `tests/conftest.py` chết ngay khi import: `ModuleNotFoundError: No module named 'app'` → job backend không chạy được test nào. Lỗi này **có từ trước**, chỉ không lộ ra vì mọi lần chạy cục bộ đều dùng `python -m pytest`.
  - `asyncio_default_fixture_loop_scope` / `asyncio_default_test_loop_scope = session`: pytest-asyncio 1.x mặc định tạo event loop mới cho mỗi test function; connection PostgreSQL nằm lại trong pool thuộc loop cũ → `got Future attached to a different loop`, `/api/health` trả `database:error` dù DB khoẻ.
- `backend/tests/live_server.py` (mới): context manager chạy **uvicorn thật** trên một database riêng (lấy `LIVE_TEST_DATABASE_URL` nếu có, không thì SQLite tạm). Bắt buộc phải là server thật vì `TestClient` tự dựng event loop riêng qua `anyio.from_thread.BlockingPortal` — chính là nguồn xung đột loop — và vì mã đóng 1008 so với HTTP 403 do ASGI server quyết định.
- `tests/test_production_lifecycle.py::test_station_ws_rejects_missing_wrong_credentials` và `tests/test_spec_v3_all.py::test_sec_2_dashboard_ws_auth_validation`: chuyển từ `TestClient` sang uvicorn thật + client `websockets`. Vẫn khẳng định đúng `code == 1008` và có `reason`.
- `.github/workflows/ci.yml`: `DATABASE_URL` chuyển từ SQLite sang **PostgreSQL** (cùng engine với production), thêm bước tạo database `redcode_live` riêng cho live transport để không tranh chấp với phần còn lại của suite.

### Commands/bằng chứng thực chạy

PostgreSQL 16.15 thật (container tạm, **đã xoá sau khi đo**); `metabase`/`c-mssql` không bị đụng.

- `pytest tests -v` — **đúng lệnh CI**, chạy trên PostgreSQL với pool thật, có `pytest.ini`: **52 passed** (48.31s).
- `pytest tests/` trên SQLite: **52 passed** (61.22s) — không regression.
- `LIVE_TEST_DATABASE_URL` trỏ database riêng: **1 passed**, log `Live transport: 100 sockets x 10 alarms; lost=0 duplicate=0; batch latency p50=0.069s p95=2.002s max=2.002s`.
- Frontend: `npm test` **8 passed**; `npm run build` **PASS** (283.35 kB js / 29.14 kB css).
- Job `docker` của CI (lần đầu được kiểm chứng): `docker build -f backend/Dockerfile` **PASS**, `docker build -f nginx/Dockerfile` **PASS**. Image `redcode-api:ci` và `redcode-nginx:ci` đã xoá sau khi build.
- Trước khi sửa, cùng lệnh `pytest tests -v` trên PostgreSQL cho **12 failed / 10 passed / 30 errors**; và `pytest.exe tests` (không qua `python -m`) chết ở conftest với `ModuleNotFoundError: No module named 'app'`.

### Giới hạn

- **Chưa có lần chạy nào trên GitHub Actions.** Toàn bộ bằng chứng trên là chạy tay mô phỏng đúng lệnh CI. Cổng 1 blocker "CI chưa có bằng chứng chạy thật" **vẫn mở**.
  - *Cập nhật cùng ngày:* blocker này **đã gỡ** — xem entry "Push nhánh và xác nhận CI xanh trên GitHub Actions" ở đầu file.
- Hai test WebSocket giờ khởi động một uvicorn riêng nên chậm hơn (2 test ~12s thay vì tức thời).
- `test_live_transport.py` vẫn dùng biến `LIVE_TEST_DATABASE_URL`; nếu biến này trỏ vào cùng database với `DATABASE_URL` thì server con có thể tranh chấp với suite — CI đã tách bằng database `redcode_live`.
- Không thay đổi schema, không có migration mới. Ảnh hưởng duy nhất tới code sản phẩm là **không có** — toàn bộ thay đổi nằm ở hạ tầng test.

## 2026-10-09 — Kiểm chứng PostgreSQL thật: Alembic, schema alignment và toàn bộ 52 test

Đợt này **không sửa code ứng dụng**. Mục đích: gỡ caveat "toàn bộ test mới chỉ chạy trên SQLite" và lấy bằng chứng migration chạy được trên PostgreSQL — hai blocker của Cổng 1 trong `docs/production-readiness.html`.

### Thực hiện

- Trước đợt này Docker engine **chưa chạy** trên máy (`docker info` báo `dockerDesktopLinuxEngine: The system cannot find the file specified`), là một chặn cứng của Cổng 1. Trong phiên engine đã lên: Server Docker Desktop 4.50.0, Engine 28.5.1, `docker info` thành công, Compose v2.40.3-desktop.1 → **chặn cứng đó được gỡ**, thay bằng việc "dựng stack production" ở mức còn-thiếu.
- Container **tạm** `redcode-pgtest` (`postgres:16-alpine`, PostgreSQL **16.15**), cổng **5433** (1433 đã bị `c-mssql` chiếm), không dùng named volume; **đã xoá container sau khi đo xong**. `metabase` và `c-mssql` không bị đụng tới.
- Cấu hình truyền qua biến môi trường `DATABASE_URL` trong từng lệnh; **không** sửa `.env`, không sửa file nào của dự án.

### Commands/bằng chứng thực chạy

- `alembic upgrade head` trên schema PostgreSQL sạch: **5/5 migration PASS** (`8280022f67e9` → `20261006_runtime` → `20261006_validity` → `20261007_permissions` → `20261007_integrations`), log `Context impl PostgresqlImpl` + `Will assume transactional DDL`.
- `pytest tests/` trên PostgreSQL: **52 passed** (67.76s). Trong đó `test_alembic_upgrade_and_schema_alignment` khẳng định mọi cột ORM đều tồn tại trong schema PG thật → **schema alignment đã được xác minh trên PostgreSQL**, không chỉ SQLite.
- `test_outbox_claim_crash_recovery_and_duplicate_claim` — test từng fail vì `sqlite3.OperationalError: database is locked` khi chạy gộp — **PASS trên PostgreSQL**.

### Phát hiện: harness test không chạy được trên PostgreSQL pool thật

Chạy thẳng `pytest tests/` với `app/database.py` nguyên trạng (PostgreSQL dùng pool thật `pool_size=25`) cho **12 failed, 10 passed, 30 errors**. Nguyên nhân **không phải** code ứng dụng:

- `tests/conftest.py` và fixture trong `tests/test_redcode_core.py` khai báo `scope="module"`, nhưng **pytest-asyncio 1.4.0** mặc định tạo **event loop mới cho mỗi test function**. Với SQLite, `NullPool` không giữ connection nên vô hại; với PostgreSQL, connection nằm lại trong pool thuộc loop cũ → `RuntimeError: ... got Future ... attached to a different loop`, khiến `/api/health` trả `database: "error"`.
- **Chứng minh bằng thí nghiệm tách biệt:** ép `NullPool` cho PostgreSQL (sửa tạm `app/database.py`, **đã revert — `git status` xác nhận `database.py` sạch**) → **52 passed**. Vậy code ứng dụng tương thích PostgreSQL hoàn toàn; chỉ harness vướng.
- **Bản sửa khả thi đã kiểm chứng (không sửa file nào):** `pytest -o asyncio_default_fixture_loop_scope=session -o asyncio_default_test_loop_scope=session` → **50 passed**, hết toàn bộ 30 errors. Hai test còn lại (`test_station_ws_rejects_missing_wrong_credentials`, `test_sec_2_dashboard_ws_auth_validation`) fail vì dùng `TestClient` đồng bộ, vốn mở event loop riêng qua `anyio.from_thread.BlockingPortal` → vẫn lỗi loop.

### Giới hạn

- Bản sửa harness **chưa áp dụng vào repo** — mới kiểm chứng bằng tuỳ chọn dòng lệnh. Việc thêm `pytest.ini` / chuyển hai test WebSocket sang `httpx.AsyncClient` + `ASGITransport` là thay đổi riêng, chưa làm.
- Container test đã xoá; image `postgres:16-alpine` (419MB) giữ lại, dùng được cho triển khai thật.
- Đây **chưa phải** bằng chứng CI: chưa có pipeline nào chạy, mới là lần chạy tay trên PostgreSQL → Cổng 1 blocker #3 vẫn mở.
- Chưa test backup/restore trên PostgreSQL → Cổng 1 blocker #2 vẫn mở.

## 2026-10-09 — Sửa lỗi LAN thực địa: secure-context UUID và credential trạm bị từ chối

Phát hiện trong đợt chạy thử LAN nhiều thiết bị (dev mode, `uvicorn` + Vite, máy khác truy cập `http://<LAN-IP>:5173`). Hai lỗi đều chỉ xuất hiện ngoài `localhost`, nên không lộ ra trong test trước đó.

### Thay đổi

- `frontend/src/utils/uuid.js` (mới) + `pages/OperatorDashboard.jsx` + `context/WebSocketContext.jsx`: `crypto.randomUUID()` chỉ tồn tại trong secure context (HTTPS hoặc `localhost`). Deployment LAN theo tài liệu là HTTP thuần nên **mọi máy trạm thật** sẽ gặp `crypto.randomUUID is not a function`. Thay bằng `randomId()` có fallback RFC 4122 v4 (`crypto.getRandomValues`, và `Math.random` khi không có Web Crypto). Hai điểm gọi: phát báo động (idempotency key) và TEST KẾT NỐI.
- `app/main.py`: WS gateway từ chối credential bằng `close()` **trước** `accept()` khiến ASGI trả HTTP 403 cho gói nâng cấp; trình duyệt quy về mã đóng **1006** không kèm lý do, nên credential sai **không phân biệt được** với mất mạng. Thêm `reject_websocket()`: `accept()` rồi `close(1008, reason)` cho toàn bộ đường từ chối (station thiếu/sai token, dashboard thiếu/sai/hết hạn token, user không hợp lệ, client type lạ).
- `app/main.py`: socket trạm bị thay thế (thiết bị xác nhận lại) đóng bằng `4001 "Station session superseded"` thay vì `1008` — tránh việc UI mới báo "cần xác nhận lại thiết bị" ngay sau khi vừa xác nhận thành công.
- `context/WebSocketContext.jsx`: `ws.onclose` đọc `event.code`; gặp `1008` thì **dừng vòng retry** và đặt `activationError` (tách `station` / `dashboard`), thay vì thử lại vô hạn trong im lặng. Thêm `retryConnection()` để thử lại thủ công sau khi xác nhận lại thiết bị hoặc đăng nhập lại; `connect()` và `synchronize()` dừng khi đang bị chặn; `onopen` xóa lỗi. `testConnection()` trả thông báo thật thay cho "Trạm chưa kết nối WebSocket".
- `pages/ReceiverStationView.jsx`: hiển thị khối lỗi kích hoạt (lý do server trả về + cách xử lý + nút THỬ LẠI), tự mở lại phần chọn trạm, và dòng trạng thái phân biệt "BỊ MÁY CHỦ TỪ CHỐI" với "OFFLINE".

### Commands/bằng chứng thực chạy

Windows 11, Python 3.14 `venv`, Node 24; mọi test chạy trên DB SQLite tạm trong `%TEMP%`, **không** đụng `backend/redcode.db` của dự án.

- Probe trên **uvicorn thật** (`tests/ws_reject_probe.py`, WebSocket client `websockets` 17.2): **5/5** đường từ chối trả `1008` kèm lý do đọc được. Cùng probe chạy trên `main.py` của `HEAD` (stash bản sửa) cho **0/5** — tất cả `HTTP 403`. Đây là bằng chứng trước/sau.
- Backend: từng suite chạy riêng trên DB tạm sạch — `test_production_lifecycle` **12 passed**, `test_spec_v3_all` **13**, `test_redcode_core` **8**, `test_spec_v2_features` **4**, `test_review_regressions` **4**, `test_optional_setup` **3**, `test_station_validity` **2**, `test_alembic_migrations` **2**, `test_live_transport` **1**, `test_50_concurrent_clients` **2**, `test_100_stations_load` **1**. Tổng **52 passed**.
- Hai test cũ đã siết lại: `test_station_ws_rejects_missing_wrong_credentials` và `test_sec_2_dashboard_ws_auth_validation` giờ khẳng định `code == 1008` **và** có `reason`, thay vì chỉ khẳng định có disconnect.
- Frontend `npm test`: **8 passed**. `npm run build`: **PASS**.

### Giới hạn

- Lỗi `database is locked` khi chạy **gộp nhiều suite trong một tiến trình** trên SQLite (xảy ra ở `test_outbox_claim_crash_recovery_and_duplicate_claim`, suite này chạy riêng thì PASS). Đây là giới hạn SQLite đa kết nối, không phải regression của đợt này; CI dùng PostgreSQL nên không gặp. **Cập nhật 2026-10-09:** caveat này nay đã được kiểm chứng lại trên PostgreSQL thật — xem entry phía trên.
- Chưa có browser/thiết bị thật tự động nghiệm thu; luồng "xác nhận lại thiết bị → tự kết nối lại" mới được kiểm ở mức code + probe giao thức.
- Không thay đổi schema, không có migration mới. Finding R07/R08 phần "station 401 hiển thị lỗi activation" nay đã có code và test; các phần còn lại của R07/R08 giữ nguyên PARTIAL.

## 2026-10-07 — Cài trước/kết nối DB sau và optional n8n

- Docker launcher `start_server.py` chọn bootstrap app độc lập DB khi DATABASE_URL trống; setup token lấy tại server, API test/complete yêu cầu token, PostgreSQL-only. Complete chạy Alembic + production Admin seed trước lưu runtime config atomic mode 0600 rồi chuyển app. Setup endpoint không còn hoạt động khi cấu hình đã hoàn tất.
- Volume `redcode_runtime_config` lưu config/secret; wizard không thay external network hay cài PostgreSQL. PostgreSQL chưa cấu hình không có nghiệp vụ alarm. Có env DB vẫn migrate trước startup bình thường.
- Migration `20261007_integrations` và Admin `/admin/settings` lưu enabled/webhook/timeout/retries trong DB, test event riêng, audit không URL. Disabled không enqueue alarm mới; first-enable cutoff bỏ backlog cũ; outage khi enabled vẫn durable retry. Upgrade mặc định integration disabled, cần Admin bật lại.
- Backend full suite cuối **52 passed**, gồm live transport và setup/token/permission/disabled→enabled/cutoff regression. Legacy suites dùng integration fixture enabled để giữ test crash/outbox meaningful. End-to-end wizard trên PostgreSQL/container thực cần môi trường Docker/PG; không coi mocked validation là nghiệm thu deployment.
- Frontend **8 tests PASS**, build **PASS**; Alembic upgrade head và targeted setup/schema tests **PASS**. Bổ sung cutoff legacy backlog regression để kiểm tra không gửi history trước first enable.

## 2026-10-07 — Sơ đồ flow triển khai production

- Thêm `docs/production_deployment_flow.md`: Mermaid topology/tổng thể/nghiệp vụ/provisioning/upgrade/rollback, 12 bước với thao tác và điều kiện chuyển bước, phiếu cấu hình, nhánh xử lý lỗi và checklist bàn giao.
- Liên kết từ README và runbook production. Các flow hướng dẫn thực thi theo release hiện tại, không là bằng chứng đã nghiệm thu site.

## 2026-10-07 — Runbooks kiểm thử và production

- Thêm `docs/testing_guide.md`: fixture staging/site, commands, T01–T13 covering auth/lifecycle/audio/expiry/permission/reconnect/outbox/restart/load/report/migration/PC/Android, mapping acceptance 01–25 và mẫu evidence.
- Thêm `docs/production_deployment.md`: fresh PostgreSQL hiện có/external network/env/TLS/build/Alembic, Admin provisioning/audio/kiosk, health/outbox, backup/restore drill, forward-only upgrade/rollback và xử lý DB create_all cũ.
- Liên kết hai tài liệu từ README; đối chiếu commands/API/config với release `9b01d4a`. Đây là hướng dẫn thực hiện tại site, không ghi nhận các bước deployment/physical acceptance đã chạy. Đợt này chỉ thay tài liệu.

## 2026-10-07 — Lifecycle, permission, recovery và CI

### Thay đổi

- `core/station_lifecycle.py` và WS gateway: RECEIVED chuyển PENDING → DELIVERED, predecessor guards, row lock/CAS, idempotent ACK/audit, timestamps server. DISPLAYED/audio success không được nhảy cóc; FAILED cho phép explicit successful audio retry, giữ error/history. Local dismiss khóa/CAS, không đổi global status.
- `alarm_lifecycle.py`, alarms/WS manager: terminal ACTIVE → CANCELLED/EXPIRED với lock/CAS, expired cancel trả 409, cancellation retry idempotent. Mọi đường expiry API/monitor broadcast dashboard và target snapshot, giữ audit; không outbox end/cancel. Station sends có timeout.
- Reports summary/offline/XLSX: half-open hospital midnight range, UTC normalization; naive datetime theo Asia/Ho_Chi_Minh.
- Permission source duy nhất normalized table; ORM bỏ cột JSON, API field tương thích là projection. Create/update config và permissions trong cùng transaction, validate department IDs, cập nhật row có sẵn giữ identity và phản hồi mới nhất.
- Idempotency giữ DB UNIQUE, sửa fingerprint default location/note/source department. Production vẫn dùng PostgreSQL nextval; không đổi kiến trúc sequence.
- Outbox claim CAS từng item trước I/O, persist attempt/lease trước crash, stale reclaim commit kể cả queue không có due item, chỉ lease owner finalize; SENT xóa retry/lock. Stable Idempotency-Key at-least-once cần n8n dedup; không tuyên bố exactly-once.
- Startup create_all chỉ development/test, production không schema mutation; startup audit disconnect cho connection tồn từ restart. Manual seed cũng guard production. Register rotate credential đóng socket cũ.
- Frontend queue helper regression dedup/FIFO/sync race/terminal tombstone; sync HTTP lỗi retry trên connection hiện hành. Đổi station dọn pending dismiss/stop audio; hiển thị lỗi audio ở overlay và receiver. Dashboard cập nhật cancel/expiry ngay khi có event.
- SoundPlayer chỉ onStart sau play resolve, failed session invalidate stale callbacks, không completion cho empty audio; audible unlock tone không phụ thuộc WAV demo trong production.
- Thêm `.github/workflows/ci.yml`: pytest/Alembic, PostgreSQL 16 test service cho live transport, frontend tests/build, Docker image builds; không tự deploy.

### Migration

`20261007_permissions` sau `20261006_validity`: import valid legacy JSON department IDs chỉ cho normalized pairs chưa tồn tại; explicit normalized deny/grant giữ nguyên; bỏ JSON column; repair PENDING có received_at thành DELIVERED. Có regression upgrade preserving history/deny/invalid IDs. Test đổi tên `test_alembic_upgrade_and_schema_alignment`; validity downgrade từ chối theo forward-only policy.

### Commands/bằng chứng thực chạy

Windows/Python 3.14, DB test riêng trong thư mục temp; không đổi DB dự án/production.

- `python -m alembic upgrade head`: PASS fresh SQLite đến `20261007_permissions`.
- `python -m pytest tests -q -s -p no:cacheprovider` (PYTHONIOENCODING=utf-8): **49 passed**, 5 dependency/config warnings, 59.10s. Bao gồm upgrade/schema/DB unique, legacy migration, production no-create_all, toàn bộ auth/state/permission/date/outbox/idempotency regressions.
- `npm test`: **8 passed**. `npm run build`: **PASS**. Package không có lint/typecheck script.
- Live Uvicorn TCP/WebSocket test: reconnect alarm A/B + cancel offline sync exclusion, socket replacement race, process restart/active recovery, n8n connection refused; **100 real sockets × 10 alarms**, lost=0, duplicate=0, batch p50=0.069s, p95/max=0.369s. Localhost/SQLite, không qua Nginx/PostgreSQL và không đo physical audio.
- Lượt test đầu phát hiện stale permission response/identity map và sửa update rows + populate_existing; lượt Windows console encoding cũ sửa bằng UTF-8 env; live test cleanup sửa taskkill process tree để không giữ DB handle bởi venv child interpreter. Full suite cuối PASS.

### Scenario acceptance hiện tại

- A/B/C: PASS API/state/transport; audio success ACK trong transport mô phỏng protocol, không nghiệm thu browser/loa.
- D/G: PASS live disconnect/missed ACTIVE/cancel exclusion/reconnect/process restart; expiry exclusion cũng có API regression và queue tests.
- E: PASS JS play rejection/stale callback + backend FAILED/error/no successful start regression; thiết bị thực còn pending.
- F: PASS core live khi n8n refused, outbox retry/crash/stale recovery regression.
- H: PASS local real TCP 100 × 10, FIFO sequential batch/no duplicate; còn Nginx/PostgreSQL/LAN/concurrent browser acceptance.

### Giới hạn

Docker engine không chạy (`docker info` FAIL missing dockerDesktopLinuxEngine); PostgreSQL/Nginx container build/restart/backup restore chưa chạy local. CI workflow đã tạo nhưng chưa có remote run evidence; `gh auth status` chưa đăng nhập nên chưa xác minh Actions. PC/Android/loa và browser end-to-end chưa nghiệm thu. Các phần còn PARTIAL trong lịch sử (admin outbox controls, readiness/config/audit/report completeness, legacy create_all adoption) chưa thể kết luận production-ready.

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
| R07 Kiosk | FIXED ở code/API | POST activate bằng station credential, nhập station code trực tiếp, không bắt user JWT/list station; station 401 không redirect login. API regression pass. **2026-10-09**: credential bị từ chối nay đóng bằng 1008 kèm lý do (trước là HTTP 403 → trình duyệt thấy 1006), client dừng retry và hiển thị lỗi activation; probe uvicorn thật 5/5 PASS. Cần browser boot/refresh. |
| R08 Reconnect/dismiss | PARTIAL | Auth token là dependency socket, cleanup guards, watchdog; pending dismiss lưu localStorage/retry lúc sync; dismissed/cancel tombstones. **2026-10-09**: client phân biệt được từ chối credential với mất mạng nên hết retry vô hạn; socket bị thay thế đóng bằng 4001 tách khỏi 1008. Cần browser integration, revoke dashboard socket ngay, identity-specific pending action cleanup. |
| R09 Outbox | PARTIAL | locked_at lease, reclaim abandoned PROCESSING, SQL due filter, exponential capped retry, stable Idempotency-Key, audit failed attempt. Regression reclaim pass. Còn multi-worker locking, admin retry/backlog. (2026-10-11: cấu hình n8n nay bằng biến môi trường, không còn mục "config DB".) |
| R10 Permission/idempotency | PARTIAL | API effective types, viewer empty, backend missing permission deny; admin khoa checkboxes; conflict khi key khác actor/payload; frontend giữ request key retry. Còn user-specific permissions, DB key scoped và migration JSON legacy. |
| R11 Audit/state | PARTIAL | Typed allowlist/target/current socket/active alarm/terminal guard, timestamp ACK, station ID connect logs; configuration action audit không chứa body secrets. Còn before/after transactional config audit, lỗi hệ thống đầy đủ, audio-test ACK. |
| R12 Groups | PARTIAL | Edit tên omit station_ids thay vì gửi []; sync/dismiss dựa persisted target snapshot. Chưa có membership editor/read API đầy đủ. |
| R13 History | PARTIAL | DELETE user/department/station/group/alarm type soft-disable; state/history giữ lại; station disable/token update đóng socket. Còn revoke token khi register lại và UI bật/tắt đầy đủ. |
| R14 Production/security | PARTIAL | Fail-fast production secret/PostgreSQL/demo/CORS; production seed chỉ bootstrap admin; .env example thêm demo/admin; enum/repeat/local audio validation; upload UUID + 20MB + extension; WS Nginx access log off, Uvicorn access log off. Còn content MIME sniffing, toàn bộ FK/null/bounds và log-scan thật. |
| R15 Health | PARTIAL | DB check lỗi không tiếp tục count trên DB lỗi; còn task readiness/cached integration probe. |
| R16 Report/UI/deploy | PARTIAL | Ngày Việt Nam→UTC, invalid/reversed range 422, day/month totals, XLSX station detail timestamps/error/formula escaping; multi-line sequence editor không truncate; overlay scroll và bỏ blur; Nginx image build frontend, không mount dist; dockerignore. Còn SQL aggregates, duration/average, clinical polish, backup restore và PG external network config. (2026-10-11: mục "n8n admin config" không còn — n8n cấu hình bằng `.env`.) |

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
