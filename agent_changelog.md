# REDCODE — Agent changelog

Lịch sử thay đổi và kiểm chứng. Đặc tả hiện hành duy nhất: `project.md`. Các entry cũ phản ánh thời điểm thực thi, không được coi là yêu cầu hiện hành nếu đã bị thay thế.

## Quy tắc ghi nhận

Sau mỗi đợt thay đổi, bổ sung ngày, yêu cầu, phạm vi/file chính, migration, commands và kết quả thực chạy, giới hạn và việc còn lại. Không ghi PASS nếu chưa chạy; giữ lịch sử cũ. Commit hash của entry mới có thể bổ sung ở đợt sau, không amend commit chỉ để thêm hash.

## 2026-10-13 — Chốt URL webhook n8n thành `http://n8n:5678/webhook/redcode`

Yêu cầu: "tạm thời bỏ qua chưa cần test n8n, định hướng: khi có sự kiện cần thông báo, call tới url `http://n8n:5678/webhook/redcode` để gửi thông tin".

Đợt này **chỉ đổi cấu hình và tài liệu**, không đổi logic: code đã đọc `settings.N8N_WEBHOOK_URL` sẵn và gửi payload thật từ trước, nên chỉ cần chốt giá trị URL. Không đổi schema, không migration, không thêm dependency.

### Thay đổi

- **`backend/app/config.py`** — giá trị mặc định của `N8N_WEBHOOK_URL` đổi từ `http://localhost:5678/webhook/redcode/alarm` sang `http://n8n:5678/webhook/redcode`. Kèm chú thích nêu hai điều dễ sai: `localhost` trong container là chính backend (không phải n8n), và path phải khớp path của Webhook node trong workflow n8n — lệch path trả 404, mà 404 bị tính là một lần gửi thất bại nên thông báo sẽ retry rồi cạn lượt trong im lặng.
- **`.env.example`** — `N8N_WEBHOOK_URL` từ để trống thành `http://n8n:5678/webhook/redcode`, kèm chú thích về hostname container và network.
- **`.env`** (không commit — gitignore) — cập nhật cùng giá trị để môi trường dev khớp tài liệu.
- **`docker-compose.yml`** — thêm khối chú thích giải thích backend phải phân giải được hostname `n8n`, tức phải cùng Docker network với container n8n; thêm mẫu `n8n_network` (external) ở cuối file cạnh mẫu PostgreSQL đã có. Vẫn **không tạo container n8n** và **không tạo container PostgreSQL mới** — chỉ là chỗ để IT khai báo network có sẵn.
- **`project.md`** §27 — URL chốt thành `http://n8n:5678/webhook/redcode`, nêu rõ `n8n` là hostname container trên Docker network, không phải `localhost`, và path phải khớp Webhook node.
- **`README.md`**, **`docs/production_deployment.md`**, **`docs/production_deployment_flow.md`** — thay mọi ví dụ `<n8n-host>`/`<integration-host>` và path `/webhook/redcode/alarm` bằng giá trị thật; bổ sung cảnh báo lỗi DNS khi backend không cùng network, và cách tách hai nguyên nhân rất khác nhau của "n8n degraded": **sai cấu hình/mạng** (không phân giải được `n8n`, hoặc lệch path nên 404) so với **n8n chết thật** — dùng `GET /api/health/n8n` để phân biệt.

Đã grep toàn repo xác nhận không còn tham chiếu nào tới path cũ `/webhook/redcode/alarm` hay placeholder `<n8n-host>`/`<integration-host>`.

### Bằng chứng thực chạy

```bash
cd backend
../venv/Scripts/python.exe -c "from app.config import settings; print(settings.N8N_WEBHOOK_URL)"
# → http://n8n:5678/webhook/redcode

DATABASE_URL="sqlite+aiosqlite:///$TEMP/rc_n8n.db" \
  ../venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
# → 81 passed, 4 warnings in 69.45s

# Cú pháp Compose
./venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('docker-compose.yml',encoding='utf-8')); print(d['services']['backend']['networks'], list(d['networks'].keys()))"
# → YAML OK / ['redcode_net'] ['redcode_net']
```

### Giới hạn

- **Chưa gọi thử tới n8n thật** — theo yêu cầu "tạm thời bỏ qua chưa cần test n8n". Đợt này chỉ chốt cấu hình; chưa có bằng chứng backend phân giải được hostname `n8n`, chưa xác nhận Webhook node trong workflow n8n dùng đúng path `/webhook/redcode`, và chưa xác nhận payload tới được n8n.
- **Chưa dựng stack Docker** trong đợt này (Docker Desktop hiện không chạy: `docker ps` lỗi `dockerDesktopLinuxEngine` không tồn tại), nên `docker compose config` chưa chạy — chỉ kiểm cú pháp YAML bằng `yaml.safe_load`.
- **`n8n_network` mới chỉ là mẫu comment**, chưa bật. Muốn backend gọi được `http://n8n:5678` thì còn một bước thủ công: bật network đó trong Compose và điền đúng tên network thật chứa n8n.

## 2026-10-11 — Sửa 4 phát hiện rà soát đợt hai (2 P1 + 2 P2) về race trạng thái trạm, ngắt do quá hạn, outbox và health

Yêu cầu: người dùng dán danh sách 4 phát hiện từ đợt rà soát thứ hai (2 P1, 2 P2) và yêu cầu xác minh/sửa. Đã đọc lại code thật cho từng phát hiện trước khi sửa; **cả 4 đều đúng** với code hiện tại.

Điểm chung của cả 4: đợt sửa trước đã đúng hướng nhưng dừng ở mức "kiểm tra rồi hành động", và mức đó vẫn để lọt một khe giữa lúc kiểm và lúc hành động. Đợt này chuyển sang **quyết định và thi hành trong cùng một bước**, và nguyên tắc "ghi sự thật hiện tại, không ghi ý định của người gọi".

### Phát hiện và cách sửa

**P1 — `backend/app/core/websocket_manager.py`: hai lượt ghi ONLINE/OFFLINE của cùng một trạm không được tuần tự hoá.** Phát hiện đúng. `_lock` chỉ bảo vệ sổ trong bộ nhớ; mỗi lượt ghi mở phiên DB riêng và `commit` là I/O, nên sau khi `_lock` được thả, một lượt ghi connect và một lượt ghi disconnect chạy song song và **lượt nào commit sau sẽ thắng**, bất kể cũ hay mới. Một phiên cũ hoàn toàn có thể commit OFFLINE *sau* khi phiên mới đã commit ONLINE, để lại database báo OFFLINE trong khi socket mới đang hoạt động — đúng lời nói dối nguy hiểm nhất với hệ thống này, vì bảng giám sát hiện một khoa đã tắt báo động trong lúc khoa đó đang nhận báo động bình thường.

Sửa theo hai vế:

1. **Ghi "sự thật đang đúng", không ghi "trạng thái tôi định đặt".** Hàm mới `_sync_station_db_status(station_code, event, readiness, seen_at)` đọc lại sổ phiên ngay trước khi ghi và ghi đúng giá trị vừa đọc, rồi **trả về** giá trị đó để lời gọi broadcast đi cùng một sự thật với bản ghi DB. Lượt ghi cuối cùng vì thế luôn là lượt đọc sự thật muộn nhất, nên database hội tụ về đúng trạng thái của bộ nhớ bất kể thứ tự hoàn thành giao dịch.
2. **Tuần tự hoá theo từng trạm.** Thêm `_presence_locks` (một `asyncio.Lock` cho mỗi mã trạm, tạo lười qua `_presence_lock()`). Không dùng `_lock` cho việc này vì `_lock` không được giữ qua I/O mạng/database; cũng không dùng một lock toàn cục vì nhịp tim của 100 trạm ghi vài giây một lần sẽ xếp hàng sau nhau vô ích.

Kèm theo, một hệ quả về kiểm toán: `_update_station_db_status` chỉ ghi `SystemEvent` khi **hành động của phiên khớp với trạng thái thật sự đã ghi** (`event == matched_event`). Một lượt ngắt bị phiên mới kế chỗ không phải là "trạm mất kết nối"; ghi audit như vậy khiến người đọc log tưởng một khoa vừa rơi khỏi hệ thống trong khi nó đang online. Ba đường dẫn cùng ghi trạng thái (kết nối, ngắt, cắt do quá hạn) nay dùng chung `_sync_station_db_status` + `_broadcast_station_status` + `_finalize_disconnect`, nên không còn tự dựng thông điệp riêng và lệch nhau.

**P1 — `_enforce_timeouts()`: còn khe giữa "đã kiểm xong" và "đã đóng".** Phát hiện đúng. Code cũ kiểm lại nhịp tim dưới lock rồi **thả lock trước khi gọi `ws.close()`**; một nhịp tim hợp lệ vẫn có thể đến trong khe đó. Sửa: **rút phiên khỏi `active_stations`/`last_heartbeats` ngay trong cùng khối lock chứa lần kiểm cuối**, rồi mới đóng socket ngoài lock. Từ thời điểm rút, `update_heartbeat` và `touch_station` đều từ chối trạm không còn socket, nên nhịp tim tới muộn không thể làm sống lại phiên đã bị kết luận quá hạn — trạng thái và socket không còn cơ hội mâu thuẫn. Việc đóng socket (network I/O, có thể treo với kết nối half-open) vẫn nằm **ngoài** lock, đúng yêu cầu không giữ lock qua I/O mạng.

Ghi thẳng giới hạn còn lại trong docstring thay vì tuyên bố đã loại bỏ hoàn toàn: **không có cách nào biết trước một nhịp tim sẽ tới ngay sau thời điểm quyết định** — đó là bản chất của mọi ngưỡng thời gian, không phải khe đồng bộ. Thứ được loại bỏ ở đây là **sự mâu thuẫn** (trạng thái nói ONLINE trong khi phiên đã bị cắt), không phải khả năng cắt muộn một nhịp.

**P2 — `backend/app/api/system.py`: `POST /outbox/requeue-exhausted` phát lại toàn bộ lịch sử lỗi.** Phát hiện đúng: endpoint chuyển **mọi** bản ghi `EXHAUSTED` về `PENDING` trong một lần gọi, không trần số lượng, không trả về phạm vi còn lại. Sửa đúng theo đề xuất "có xác nhận số lượng và giới hạn phạm vi, không cần thêm module quản lý n8n phức tạp":

- `?limit=` mặc định **50**, tối đa **200** (`ge=1, le=200` → vượt trần là 422). Trần là chủ ý: một lần gọi không giới hạn đẩy cả lịch sử lỗi nhiều tuần vào hàng đợi cùng lúc, và n8n vừa hồi phục sẽ nhận một đợt dội ngay lập tức.
- `?ids=1&ids=2` để chỉ phát lại đúng các bản ghi đã xem trong `exhausted_recent` ở `GET /api/system/status`.
- Phản hồi trả `requeued`, `limit`, `remaining_exhausted`, `has_more` — gọi lặp theo `has_more` khi cần nhiều hơn.
- Chọn theo `created_at` tăng dần (cũ nhất trước, đúng thứ tự hàng đợi) và chốt danh sách trước khi ghi, để con số trả về đúng bằng số bản ghi đã chạm.

**P2 — `backend/app/api/health.py`: health chính còn gọi HTTP sang n8n.** Phát hiện đúng: khi `N8N_ENABLED=true`, mỗi lần đọc `/api/health` có thể chờ tới 1,5 giây để hỏi `/healthz`. Hai vấn đề: một probe hạ tầng gọi endpoint này vài giây một lần sẽ dồn request vào đó, và **độ trễ của một hệ thống phụ quyết định độ trễ phép đo sức khoẻ hệ thống chính**. Sửa: `/api/health` **không gọi ra mạng ngoài**; trường `n8n` chỉ phản ánh **cấu hình** (`enabled`/`disabled`). Kiểm tra n8n sống hay không tách sang endpoint riêng `GET /api/health/n8n` (yêu cầu **ADMIN**, trả `status`/`reachable`/`latency_ms`), và n8n chết không bao giờ kéo `status` của REDCODE xuống.

Frontend cập nhật theo: thẻ N8N ở bảng giám sát đổi từ một chữ nghe như thể đã kiểm tra kết nối sang `ĐÃ BẬT` / `CHƯA BẬT`, kèm dòng ghi rõ "báo động nội bộ không đi qua đây".

**Không cần migration.** Không đổi schema, không thêm bảng, không đổi chuỗi Alembic (head vẫn `20261007_integrations`).

### File đã sửa

- `backend/app/core/websocket_manager.py` — `_presence_locks` + `_presence_lock()`; `_sync_station_db_status()`; `_broadcast_station_status()`; `_finalize_disconnect()`; `_update_station_db_status()` ghi theo sự thật và chỉ ghi audit khi hành động khớp; `_enforce_timeouts()` rút phiên trong cùng khối lock với lần kiểm cuối; ba đường dẫn connect/disconnect/timeout dùng chung một đường ghi.
- `backend/app/api/health.py` — `/api/health` bỏ hẳn lời gọi HTTP ra ngoài; trường `n8n` là cấu hình; thêm `GET /api/health/n8n` (ADMIN).
- `backend/app/api/system.py` — `POST /outbox/requeue-exhausted` thêm `limit`/`ids`, trả `remaining_exhausted`/`has_more`; bản ghi kiểm toán ghi kèm `limit`/`explicit_ids`.
- `frontend/src/pages/AdminDashboard.jsx` — thẻ N8N hiện `ĐÃ BẬT`/`CHƯA BẬT` theo cấu hình.
- `backend/tests/test_review_round2_regressions.py` — **file mới**, 5 test.
- `docs/production_deployment.md`, `docs/production_deployment_flow.md`, `docs/testing_guide.md`, `docs/production-readiness.html` — cập nhật theo trần phát lại, endpoint `/api/health/n8n` và ngữ nghĩa "n8n = cấu hình".

### Test bổ sung

`backend/tests/test_review_round2_regressions.py` — mỗi phát hiện một test khoá hành vi đã sửa:

1. `test_presence_writes_are_serialized_and_converge_to_truth` — bọc `_update_station_db_status` để đếm số lượt ghi chạy **đồng thời** (phải bằng 1) và cho lượt ghi OFFLINE của phiên cũ ngủ 0,30s trong khi lượt ONLINE của phiên mới ngủ 0,05s, rồi chạy hai lượt bằng `asyncio.gather`. Khẳng định: không có hai lượt ghi nào chồng nhau, lượt ghi cuối trả `True`, và **database kết thúc ở `ONLINE`** dù lượt OFFLINE chậm hơn.
2. `test_superseded_disconnect_does_not_log_a_false_disconnect_event` — phiên mới đang giữ trạm rồi phiên cũ mới hoàn tất việc rời đi: trạng thái phải là `ONLINE` **và** không được có bản ghi `DEVICE_DISCONNECTED` cho trạm đó. Chiều ngược lại: ngắt thật thì phải có bản ghi kiểm toán (nếu không, log mất dấu sự kiện).
3. `test_timeout_removes_session_before_closing_socket` — socket giả ghi lại trạng thái sổ phiên **tại đúng thời điểm `close()` được gọi**: lúc đó trạm phải đã bị rút khỏi `active_stations` và `touch_station()` phải trả `False`. Khẳng định thêm mã đóng `1011` và hai dict đã sạch.
4. `test_requeue_exhausted_is_bounded_and_reports_remaining_scope` — `ids=` chỉ chạm đúng bản ghi được chọn (5 bản ghi, chọn 2 ⇒ `requeued == 2`); `limit=1` ⇒ `requeued == 1` và `has_more is True`; `limit=500` và `limit=0` ⇒ **422**; OPERATOR ⇒ 403.
5. `test_health_never_calls_n8n_and_reports_configuration_only` — bật `N8N_ENABLED=true` trỏ vào cổng không có gì lắng nghe, `patch('httpx.AsyncClient')` ném lỗi nếu bị gọi: `/api/health` phải trả 200 trong **dưới 1 giây** với `n8n == 'enabled'`. `/api/health/n8n` không token ⇒ 401; có token ADMIN ⇒ `reachable is False`. Khi tắt n8n: `n8n == 'disabled'` và endpoint riêng trả `latency_ms is None`.

### Commands/bằng chứng thực chạy

```bash
# Backend, trên DB SQLite tạm mới (KHÔNG dùng backend/redcode.db)
cd backend
DATABASE_URL="sqlite+aiosqlite:///$TEMP/rc_restored.db" \
  ../venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
# → 81 passed, 4 warnings in 69.07s
# (trước đợt này: 76 test; +5 test mới)

DATABASE_URL="sqlite+aiosqlite:///$TEMP/rc_round2.db" \
  ../venv/Scripts/python.exe -m pytest tests/test_review_round2_regressions.py -q -p no:cacheprovider
# → 5 passed in 5.41s

# Frontend
cd frontend && npm test
# → tests 19 / pass 19 / fail 0
npm run build
# → built in 6.29s; dist/assets/index-DkxAsS3X.js 282.41 kB (gzip 80.08 kB)
```

**Kiểm chứng rằng 5 test mới thật sự bắt được lỗi** (không phải test trang trí): tạm hoàn nguyên **đúng dòng code cũ** của cả bốn phát hiện (bỏ `_presence_lock` khỏi `_sync_station_db_status`, trả `event_type = event`, chuyển việc rút phiên xuống **sau** `ws.close()`, khôi phục `requeue-exhausted` không giới hạn, khôi phục lời gọi HTTP trong `/api/health`), chạy file test, rồi trả tất cả về nguyên trạng. Kết quả **5/5 đều FAIL đúng kỳ vọng**:

```text
FAILED test_presence_writes_are_serialized_and_converge_to_truth            assert True is False  (co 2 luot ghi chong nhau)
FAILED test_superseded_disconnect_does_not_log_a_false_disconnect_event     assert not True       (co ban ghi DISCONNECTED gia)
FAILED test_timeout_removes_session_before_closing_socket                   assert True is False  (phien con trong so khi close() chay)
FAILED test_requeue_exhausted_is_bounded_and_reports_remaining_scope        assert 5 == 2         (ids= bi bo qua, requeue het 5)
FAILED test_health_never_calls_n8n_and_reports_configuration_only           assert 'degraded' == 'enabled'
5 failed in 2.96s
```

Sau khi trả file về nguyên trạng, chạy lại toàn bộ suite: **81 passed** (dòng lệnh đầu ở trên) — xác nhận không sót bản hoàn nguyên nào.

### Bằng chứng CI

- Commit `980c25e`, push `main` (`6a163bb..980c25e`). Truy vấn GitHub API: run **`38125659697`** (run_number 16), head_sha `980c25eb3428b529364098b2f0828815ed289eeb`, event `push`, branch `main`, tạo `2026-10-11T08:40:53Z`, cập nhật `2026-10-11T08:42:09Z`, `status: completed`, `conclusion: success`. Đối chiếu **từng bước** — cả ba job success, **không bước nào bị skip**:
  - `frontend` (9 bước): `npm ci` / `npm test` / `npm run build` đều success.
  - `backend` (12 bước): `Initialize containers` (service PostgreSQL 16), `Create live transport database`, `alembic upgrade head`, `pytest tests -v` đều success — nghĩa là **5 test mới của đợt này cũng đã chạy trên PostgreSQL thật** trong CI, không chỉ trên SQLite ở local.
  - `docker` (6 bước): build `backend/Dockerfile` và `nginx/Dockerfile` đều success.
  - Run URL: <https://github.com/buinguyenhong/REDCODETHIENHANH/actions/runs/38125659697>
- **Không đọc được số test cụ thể trong log job backend**: endpoint log của GitHub API trả **403** vì phiên này chưa xác thực GitHub (`gh` chưa đăng nhập) — đã thử lại ở đợt này và vẫn 403. Bước `pytest tests -v` success là bằng chứng đã có; con số test trong CI để trống thay vì suy đoán. Con số **81 passed** là của lần chạy local trên SQLite ở mục trên, không phải số của CI.

### Giới hạn

- **Chưa chạy lại Docker/e2e trong đợt này.** Đợt này chỉ chạy pytest/npm; CI có **build lại cả hai Docker image** (job `docker`) nhưng **không dựng stack và không chạy e2e**. Các bằng chứng Docker/e2e trước đó vẫn là của lần chạy cùng ngày, đã ghi rõ nguồn.
- **Chưa kiểm chứng trên PostgreSQL thật của bệnh viện**: suite local của đợt này chạy trên SQLite; CI có chạy toàn bộ suite trên PostgreSQL 16 nhưng đó là service tạm trong CI, không phải instance production thật. Chưa nghiệm thu thiết bị thật (PC kiosk, tablet Android, Android TV box).
- **Race trạng thái trạm mới được kiểm ở mức logic tuần tự hoá**, không phải dưới tải 50–100 thiết bị thật. Test chứng minh hai lượt ghi của cùng một trạm không chồng nhau và lượt cuối phản ánh đúng sổ phiên; **chưa** đo dưới tải thật của một ca trực.
- **`_presence_locks` không bao giờ được dọn.** Mỗi mã trạm từng xuất hiện giữ một `asyncio.Lock` trong dict suốt vòng đời tiến trình. Với quy mô 50–100 trạm cố định của hệ thống này, đó là vài chục đối tượng — không đáng kể, và dọn chúng sẽ mở lại đúng khe race vừa bịt. Ghi ra đây để không ai đọc thành "không có rò rỉ nào".
- **`POST /api/system/outbox/requeue-exhausted` vẫn chưa được thử với một n8n thật đang sống lại** — mới kiểm bằng test tự động (trần số lượng, chọn theo `ids`, trạng thái về `PENDING`, `attempt_count` về 0). Việc n8n khử trùng đúng theo `Idempotency-Key` khi phát lại vẫn chưa có bằng chứng.
- **`GET /api/health/n8n` là endpoint mới, chưa có mặt trong bất kỳ probe nào.** Nó chưa từng được gọi từ một tiến trình thật ngoài test — nghĩa là chưa có bằng chứng nó trả đúng khi n8n **đang sống** (test hiện chỉ phủ ca n8n tắt và ca n8n không kết nối được).
- **Ba endpoint health con nay đều yêu cầu token ADMIN** (`/api/health/db`, `/api/health/websocket`, `/api/health/n8n`). Probe hạ tầng không token gọi chúng sẽ nhận 401 — cần rà lại khi triển khai.

## 2026-10-11 — Sửa 5 phát hiện rà soát (2 P1 + 3 P2) về tính trung thực của trạng thái, health và outbox

Yêu cầu: người dùng dán danh sách 5 phát hiện từ một đợt rà soát (2 P1, 3 P2) và yêu cầu xác minh/sửa. Đã đọc lại code thật cho từng phát hiện trước khi sửa; **cả 5 đều đúng** với code hiện tại. Đối chiếu thêm với `project.md` R11/R14/R15 — đặc tả vốn đã yêu cầu "Health/readiness phản ánh DB/tasks/recovery; n8n degraded không làm core failed", tức code đang thiếu so với chính spec của dự án, không phải phát sinh phạm vi mới.

### Phát hiện và cách sửa

**P1 — `backend/app/api/stations.py`: nhịp tim HTTP vẫn ghi `status = ONLINE` khi không có WebSocket.** Phát hiện đúng: endpoint đã tính đúng `ws_connected` nhưng dòng cuối vẫn luôn ghi `ONLINE`. Sửa: `station.status` giờ là `ONLINE if ws_connected else OFFLINE`; phản hồi thêm trường `device_reachable: True` để tách bạch hai câu hỏi khác nhau — *thiết bị còn gọi được API* và *thiết bị có kênh nhận báo động* — mà trước đây bị gộp làm một. `last_seen_at` vẫn được ghi, nên thông tin "thiết bị còn sống" không mất.

**P1 — `backend/app/core/websocket_manager.py`: monitor ngắt trạm theo ảnh chụp cũ (race).** Phát hiện đúng: `_check_timeouts` chụp danh sách quá hạn dưới lock rồi đóng socket ngoài lock mà không kiểm lại. Sửa: tách vòng đóng ra `_enforce_timeouts(timed_out, threshold_seconds)`; trước mỗi lần ngắt, hàm này lấy lại `self._lock` và **kiểm lại cả danh tính socket (`current_ws is ws`) lẫn mốc nhịp tim mới nhất**; bỏ qua nếu socket đã bị phiên mới thay, nếu không còn dấu vết nhịp tim, hoặc nếu nhịp tim mới hơn ngưỡng. Đây là kênh nhận báo động duy nhất, nên ngắt nhầm một trạm đang sống làm trạm đó im lặng cho tới khi tự kết nối lại.

**P2 — `backend/app/api/health.py`: health tổng thể che mất lỗi giám sát.** Phát hiện đúng: `overall_status` chỉ dựa vào database, nên `status` vẫn là `ok` khi vòng giám sát đã chết. Sửa theo đúng hai phương án phát hiện đề nghị — **tách liveness và readiness**: thêm trường `liveness` (tiến trình còn phục vụ được request) và để `status` (readiness) gộp cả database **và** vòng giám sát. Ghi nhận thêm rằng vòng monitor chết không chỉ làm mù trạng thái trạm mà còn **ngừng gọi `expire_alarms()`**, nên báo động ACTIVE hết hạn không được kết thúc — mức nghiêm trọng cao hơn mô tả trong phát hiện.

Đồng thời tách `websocket` thành **ba** giá trị thay vì hai: `ok` / `degraded` (đã bật rồi chết) / `not_started` (chưa bật, hoặc đã dừng theo lệnh). Cần ba giá trị vì "chưa từng giám sát" không phải sự cố, còn "đã giám sát rồi mất" thì có — gộp hai thứ làm một sẽ khiến mọi lần đọc health trong lúc khởi động đều báo suy giảm và làm loãng đúng ca cần phát hiện. Thêm `ConnectionManager._monitor_expected` (bật trong `start_monitor`, hạ trong `stop_monitor`).

**P2 — `backend/app/api/health.py`: health lộ thông tin không cần thiết.** Phát hiện đúng: `/api/health/db` trả nguyên văn `str(e)` của driver (thường chứa host, cổng, tên user, có khi cả chuỗi kết nối) và `/api/health/websocket` trả danh sách mã trạm đang trực; cả hai không có lớp xác thực. Sửa: cả hai endpoint nay `Depends(get_current_active_admin)`. `/api/health/db` giữ chi tiết ở log server (`logger.error(..., exc_info=True)`), phản hồi HTTP chỉ nói `status`/`latency_ms`. `/api/health` công khai vẫn giữ các trường tổng hợp để probe không xác thực dùng được.

**P2 — `backend/app/core/n8n_outbox.py`: không phân biệt được lỗi còn retry với lỗi đã hết lượt.** Phát hiện đúng. Sửa: thêm giá trị trạng thái kết thúc riêng `OutboxStatus.EXHAUSTED`. `FAILED` = lần này lỗi, còn thử lại (luôn có `next_attempt_at`); `EXHAUSTED` = đã bỏ hẳn. Trước đây muốn biết một thông báo đã bỏ hẳn phải suy từ `next_attempt_at IS NULL` — thông tin ngầm, không có truy vấn nào theo trạng thái trả lời được, và nhánh thu hồi lease hết hạn còn ghi cả hai ca thành `FAILED`.

Về **khả năng theo dõi và quy tắc khi bật lại n8n** (phần phát hiện yêu cầu kiểm tra thêm): `GET /api/system/status` (ADMIN) nay trả `notification_outbox` gồm `pending`/`processing`/`sent`/`retryable_failed`/`exhausted` và `exhausted_recent` (kèm `alarm_id`, `last_error`, `attempt_count`); thêm `POST /api/system/outbox/requeue-exhausted` (ADMIN) để phát lại. Quy tắc: worker **không tự phát lại** thông báo đã EXHAUSTED — bật lại n8n không xả một loạt thông báo cũ vào hệ thống nhận; người vận hành quyết định. Gửi lại an toàn về trùng lặp vì mỗi bản ghi giữ nguyên `Idempotency-Key: redcode-outbox-{id}`. Quy tắc này ghi trong docstring đầu `n8n_outbox.py`, trong runbook và trong T08 của hướng dẫn kiểm thử.

**Không cần migration.** `notification_outbox.status` là `String(20)`, `EXHAUSTED` (9 ký tự) vừa. Không đổi schema, không thêm bảng, không đổi chuỗi Alembic (head vẫn `20261007_integrations`).

### File đã sửa

- `backend/app/api/stations.py` — `status` theo `ws_connected`; thêm `device_reachable`.
- `backend/app/core/websocket_manager.py` — `_enforce_timeouts` kiểm lại danh tính + nhịp tim; `_monitor_expected`; `stop_monitor` hạ cờ.
- `backend/app/api/health.py` — `liveness`; `status` gộp database + giám sát; `websocket` ba giá trị; hai endpoint con yêu cầu ADMIN; bỏ `detail` thô.
- `backend/app/schemas/__init__.py` — `HealthResponse` thêm `liveness`.
- `backend/app/models/__init__.py` — `OutboxStatus.EXHAUSTED`.
- `backend/app/core/n8n_outbox.py` — dùng `EXHAUSTED`; thu hồi lease rồi chốt `EXHAUSTED` cho bản ghi đã chạm trần (bắt cả dữ liệu cũ còn nằm ở `FAILED`); docstring ghi vòng đời và quy tắc bật lại n8n.
- `backend/app/api/system.py` — `notification_outbox` trong `/system/status`; endpoint `POST /system/outbox/requeue-exhausted`.
- `frontend/src/pages/AdminDashboard.jsx` — thẻ CORE hiện `HOẠT ĐỘNG`/`SUY GIẢM`/`LỖI` kèm dòng nói rõ tình trạng giám sát nhịp tim; thẻ n8n hiện số thông báo bỏ hẳn / chờ thử lại.
- `backend/tests/test_review_findings_regressions.py` — **file mới**, 7 test.
- `backend/tests/test_p0_regressions.py` — cập nhật test health theo hành vi mới (`status` phải là `degraded`); thêm khẳng định `status == OFFLINE` và `device_reachable is True`.
- `backend/tests/test_spec_v2_features.py` — `test_health_sub_endpoints` nay kiểm cả ca 401 không token rồi gọi bằng token ADMIN.
- `docs/production_deployment.md`, `docs/production_deployment_flow.md`, `docs/testing_guide.md`, `docs/production-readiness.html` — cập nhật theo hình dạng health mới và quy tắc outbox.

### Test bổ sung

`backend/tests/test_review_findings_regressions.py` — mỗi phát hiện một test khoá hành vi đã sửa:

1. `test_http_heartbeat_without_websocket_never_reports_online` — nhịp tim HTTP không có socket ⇒ `device_reachable=true` nhưng `websocket_connected=false`, `can_receive_alarms=false`, `status=OFFLINE`, cờ audio không được ghi; có socket thật thì mới ONLINE và mới nhận cờ audio.
2. `test_timeout_enforcement_rechecks_identity_and_freshness` — ba nhánh: nhịp tim mới đến sau ảnh chụp ⇒ không ngắt; socket đã bị phiên mới thay ⇒ không ngắt phiên mới; thật sự quá hạn ⇒ ngắt đúng mã `1011` và gỡ khỏi `active_stations`/`last_heartbeats`.
3. `test_health_readiness_reflects_dead_monitor` — monitor chết ⇒ `websocket=degraded`, `status=degraded`, `liveness=ok`, `database=ok`.
4. `test_health_reports_not_started_separately_from_degraded` — chưa bật monitor ⇒ `websocket=not_started`, `status=ok`.
5. `test_health_diagnostics_require_admin` — không token ⇒ 401; OPERATOR ⇒ 403; ADMIN ⇒ 200 và không có `detail`; `/api/health` công khai không có mã trạm.
6. `test_exhausted_outbox_row_is_distinct_from_retryable_failure` — còn lượt ⇒ `FAILED` + `next_attempt_at` khác NULL; hết lượt ⇒ `EXHAUSTED` + `next_attempt_at` NULL; chạy lại `process_outbox` **không** claim lại bản ghi đã EXHAUSTED (`attempt_count` không tăng); có bản ghi kiểm toán `N8N_NOTIFICATION_FAILED`.
7. `test_admin_can_see_and_requeue_exhausted_notifications` — `/system/status` đếm và liệt kê được; OPERATOR bị 403; ADMIN requeue ⇒ về `PENDING`, `attempt_count=0`.

### Commands/bằng chứng thực chạy

```bash
# Backend, trên DB SQLite tạm mới (KHÔNG dùng backend/redcode.db)
cd backend
DATABASE_URL="sqlite+aiosqlite:///$TEMP/rc_final.db" \
  ../venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
# → 76 passed, 4 warnings in 72.78s
# (trước đợt này: 69 test; +7 test mới)

DATABASE_URL="sqlite+aiosqlite:///$TEMP/rc_collect.db" \
  ../venv/Scripts/python.exe -m pytest tests --collect-only -q
# → 76 tests collected

# Live server thật qua uvicorn (chạy hết lifespan → monitor_expected=True)
DATABASE_URL="sqlite+aiosqlite:///$TEMP/rc_live.db" \
  ../venv/Scripts/python.exe -m pytest tests/test_live_transport.py -q
# → 1 passed in 19.10s

# Frontend
cd frontend && npm test
# → tests 19 / pass 19 / fail 0
npm run build
# → built in 14.51s; dist/assets/index-ClwcZw-y.js 282.25 kB (gzip 80.03 kB)
```

**Kiểm chứng rằng 7 test mới thật sự bắt được lỗi** (không phải test trang trí): với mỗi phát hiện, tạm hoàn nguyên **đúng dòng code cũ** trong file nguồn, chạy test tương ứng, rồi trả file về nguyên trạng. Kết quả **5/5 đều FAIL đúng kỳ vọng**:

```text
[FAIL (dung ky vong)] P1-1 heartbeat HTTP ghi ONLINE khi khong co WebSocket      1 failed in 2.00s
[FAIL (dung ky vong)] P1-2 ngat tram theo anh chup cu (race voi nhip tim moi)   1 failed in 1.67s
[FAIL (dung ky vong)] P2-3 health tong the bao ok khi vong giam sat da chet     1 failed in 3.38s
[FAIL (dung ky vong)] P2-4 health chan doan cong khai, lo chi tiet noi bo       1 failed in 1.71s
[FAIL (dung ky vong)] P2-5 outbox het luot thu dung chung trang thai FAILED     1 failed in 2.11s
```

Sau khi chạy xong, `git status` xác nhận các file nguồn chỉ còn đúng các sửa đã dự định (không sót bản hoàn nguyên nào).

### Bằng chứng CI

- Commit `522a794`, push `main` (`2116c52..522a794`). Truy vấn GitHub API: run **`38122984061`**, head_sha `522a794ffd3c996c890aaecdea937c2a51c8612d`, event `push`, branch `main`, tạo `2026-10-11T07:54:59Z`, cập nhật `2026-10-11T07:56:20Z`, `status: completed`, `conclusion: success`. Đối chiếu **từng bước** — cả ba job success, **không bước nào bị skip**:
  - `frontend` (9 bước): `npm ci` / `npm test` / `npm run build` đều success.
  - `backend` (12 bước): `Initialize containers` (service PostgreSQL 16), `Create live transport database`, `alembic upgrade head`, `pytest tests -v` đều success — nghĩa là toàn bộ suite chạy trên **PostgreSQL thật** trong CI, không phải SQLite.
  - `docker` (6 bước): build `backend/Dockerfile` và `nginx/Dockerfile` đều success.
  - Run URL: <https://github.com/buinguyenhong/REDCODETHIENHANH/actions/runs/38122984061>
- **Không đọc được số test cụ thể trong log job backend**: endpoint log của GitHub API trả **403** vì phiên này chưa xác thực GitHub (`gh` chưa đăng nhập). Bước `pytest tests -v` success là bằng chứng đã có; con số test trong CI để trống thay vì suy đoán. Con số **76 passed** là của lần chạy local trên SQLite ở mục trên, không phải số của CI.

### Giới hạn

- **Chưa chạy lại Docker/e2e trong đợt này.** Các bằng chứng Docker (compose build/up, e2e 23/23, restart 8/8, Content-Type audio) trong runbook mục 13 là của lần chạy trước cùng ngày, đã ghi rõ nguồn. Đợt này chỉ chạy pytest/npm; CI có **build lại cả hai Docker image** (job `docker`) nhưng **không dựng stack và không chạy e2e**.
- **Chưa kiểm chứng trên PostgreSQL thật của bệnh viện**: suite local của đợt này chạy trên SQLite; CI có chạy toàn bộ suite trên PostgreSQL 16 nhưng đó là service tạm trong CI, không phải instance production thật. Chưa nghiệm thu thiết bị thật (PC kiosk, tablet Android, Android TV box).
- **`POST /api/system/outbox/requeue-exhausted` chưa được thử với một n8n thật đang sống lại** — mới kiểm bằng test tự động (trạng thái về `PENDING`, `attempt_count` về 0). Việc n8n khử trùng đúng theo `Idempotency-Key` khi phát lại vẫn chưa có bằng chứng.
- **Hai endpoint health con nay yêu cầu token ADMIN.** Nếu ở đâu đó có probe hạ tầng đang gọi `/api/health/db` hoặc `/api/health/websocket` không kèm token, probe đó sẽ nhận 401 — cần rà lại khi triển khai. Trong repo hiện tại không có probe nào như vậy (đã grep `docker-compose.yml`, `nginx/`, `.github/workflows/ci.yml`), và frontend gọi `getHealthDb`/`getHealthWebsocket` nhưng không component nào dùng.
- **Chuyển trạng thái dữ liệu cũ `FAILED` → `EXHAUSTED`** chạy trong `process_outbox` mỗi vòng, nên bản ghi cũ chỉ đổi trạng thái khi n8n được bật (worker thoát sớm khi `N8N_ENABLED=false`). Đây là chủ ý — không đụng dữ liệu khi tính năng đang tắt — nhưng nghĩa là một hệ thống đang tắt n8n sẽ vẫn hiện số `exhausted` cũ bằng 0 cho tới khi bật lại.

## 2026-10-11 — Tạo lại tài liệu triển khai theo hệ thống hiện tại

Yêu cầu: "tạo lại tài liệu deploy sau đó push code lại".

Đợt này **chỉ sửa tài liệu**, không đổi code, không đổi schema, không migration. Lý do phải tạo lại: tài liệu triển khai vẫn tham chiếu release `9b01d4a` và schema head `20261007_permissions` (head thật là `20261007_integrations`), và chưa phản ánh loạt sửa P0 vừa nghiệm thu — nghĩa là một người triển khai đọc tài liệu cũ sẽ không biết rằng trạng thái trạm nay chỉ ONLINE khi có WebSocket thật, rằng sau restart mọi trạm hiện OFFLINE, rằng phản hồi phát báo động có hai con số đếm trạm, hay rằng asset audio phải trả đúng `Content-Type`.

### Thay đổi

- **`docs/production_deployment.md`** — viết lại:
  - Header cập nhật: code `84ad2d6`, schema head `20261007_integrations`.
  - Mục 0 mới "Đọc trước: những gì khác so với bản runbook cũ" — bốn thay đổi hành vi mà người vận hành bắt buộc phải biết: cấu hình chỉ bằng `.env`; trạng thái trạm chỉ ONLINE khi có kênh WebSocket thật và cờ cũ bị xóa sau restart; phát báo động trả `target_station_count`/`delivered_station_count` và phát lại báo động đã kết thúc bị từ chối **409**; mã đóng WebSocket `4001`/`1008`/`1011` có nghĩa cụ thể (kèm cảnh báo không xóa profile browser để "thử lại").
  - Mục 4 bổ sung **bảng ràng buộc cấu hình** mà `app/config.py` chặn lúc khởi động, kèm thông báo lỗi thật; ghi rõ thiếu `INITIAL_ADMIN_PASSWORD` trên DB trắng làm tiến trình seed dừng **có chủ ý**.
  - Mục 5 nêu kết quả mong đợi cụ thể (`alembic current` = `20261007_integrations`, log `Station offline monitor active`, `Durable notification outbox worker active`) và thêm bước **bắt buộc** kiểm tra `Content-Type` của asset audio — sai kiểu media nghĩa là loa không kêu dù UI hiện báo động.
  - Mục 6 nêu yêu cầu alarm type phải có ≥1 tệp âm thanh (rỗng → 422) và hành vi khi sửa cấu hình trạm đang trực (đổi tên không ngắt; đổi token/mã trạm thì ngắt và phải xác nhận lại).
  - Mục 7 thêm việc đối chiếu `target_station_count` với `delivered_station_count` sau mỗi lần phát.
  - Mục 10 (upgrade) cảnh báo sau `up -d` mọi trạm hiện OFFLINE là hành vi đúng, cửa sổ bảo trì cần người xác nhận từng máy.
  - Mục 11 thêm 5 dòng chẩn đoán mới: health `websocket: degraded`, trạm ONLINE mà không có alarm, phiên bị chiếm (`4001`), dừng thử lại vĩnh viễn (`1008`), `delivered < target`, không tạo được alarm type.
  - Mục 13 mới: **bảng bằng chứng đã chạy thật** (69 backend / 19 frontend / build / compose build+up / chuỗi Alembic / health / e2e 23/23 / restart 8/8 / Content-Type / CI run `38114856575`) và **danh sách giới hạn chưa có bằng chứng** (thiết bị thật, PostgreSQL thật, diễn tập backup/restore, n8n chết ở mức thiết bị).
- **`docs/production_deployment_flow.md`** — viết lại: tham chiếu release/head mới; mục 0 mới "Ba điều phải biết trước khi bắt đầu"; sơ đồ tổng thể thêm nhánh kiểm tra MIME audio ở bước 8; bước 5 nêu rõ cấu hình sai bị chặn lúc khởi động là kết quả đúng; bước 8 liệt kê 5 điều kiện qua bước; bước 9 thêm ràng buộc alarm type có âm thanh; bước 10 thêm hành vi khi sửa cấu hình trạm đang trực; bước 11 thêm ba điểm kiểm tra riêng của release (số trạm nhận, phát lại đã kết thúc → 409, cờ cũ bị xóa sau restart); luồng upgrade thêm nhánh xác nhận lại từng máy trạm; bảng xử lý lỗi thêm 3 dòng; checklist một trang bổ sung các mục tương ứng.
- **`docs/testing_guide.md`** — cập nhật release tham chiếu `84ad2d6` / head `20261007_integrations`; dòng "kết quả gần nhất" thay số liệu cũ (49 backend, 8 JS, và chỉ số load test 100 socket chưa có bằng chứng trong đợt này) bằng số liệu chạy thật của đợt P0 (69 backend, 19 JS, build PASS, e2e 23/23, restart 8/8) kèm liên kết tới mục 13 của runbook; T02 thêm bước đối chiếu hai con số đếm trạm; T04 thêm yêu cầu phát lại báo động đã kết thúc phải bị từ chối 409; T06 thêm case nhịp tim HTTP không có WebSocket; T09 thêm yêu cầu cờ cũ phải bị xóa sau restart và kiểm tra `Content-Type` của asset audio.
- **`docs/production-readiness.html`** — mục "Stack production chưa từng được dựng": thêm cập nhật 2026-10-11 rằng stack **đã được build và chạy thật** (compose build exit 0, hai container Up, chuỗi Alembic trên DB trắng, health ok, e2e 23/23 + restart 8/8) nhưng bằng override tạm SQLite đã gỡ sạch, nên **vẫn chưa phải stack production**; giữ nguyên trạng thái "Còn thiếu" vì chưa lần nào chạy với `.env` production và PostgreSQL thật. Standfirst cập nhật ngày và thêm liên kết tới bằng chứng.

### Test bổ sung

Không thêm test mới (đợt này chỉ sửa tài liệu). Các con số ghi trong tài liệu đã được **chạy lại thật** trước khi ghi, để không lặp lại lỗi ghi số liệu cũ:

- `pytest tests --collect-only -q` → **69 tests collected** (khớp con số ghi trong tài liệu).
- `pytest tests -q -p no:cacheprovider` trên DB SQLite tạm mới → **69 passed**, 4 warnings, 64.97s.
- `npm test` (frontend) → **19 passed, 0 fail**.

### Commands/bằng chứng thực chạy

```bash
# Backend, trên DB SQLite tạm mới (không dùng backend/redcode.db)
cd backend
DATABASE_URL="sqlite+aiosqlite:///$TEMP/rc_docverify.db" ENVIRONMENT=test DEMO_MODE=true \
  ../venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
# → 69 passed, 4 warnings in 64.97s

# Frontend
cd frontend && npm test
# → tests 19 / pass 19 / fail 0
```

Kiểm tra chéo tài liệu với code (không dựa vào trí nhớ): chuỗi migration đọc từ `revision`/`down_revision` trong `backend/alembic/versions/` → `8280022f67e9 → 20261006_runtime → 20261006_validity → 20261007_permissions → 20261007_integrations`; ràng buộc production đọc từ `backend/app/config.py`; danh sách biến đọc từ `.env.example`; MIME audio đọc từ `nginx/default.conf`; mã đóng WebSocket đọc từ `backend/app/core/websocket_manager.py`.

Dọn dẹp: xóa các DB tạm `rc_*.db` trong `$TEMP` do các đợt trước để lại. `backend/redcode.db` của dự án không bị chạm tới. Không tạo container nào trong đợt này.

- Commit `385c63e`, push `main` (`84ad2d6..385c63e`). Truy vấn GitHub API: run **`38120450184`**, head_sha `385c63e`, `status: completed`, `conclusion: **success**`. Trích conclusion từng job — **cả ba job success, không step nào bị skip**:
  - `frontend`: 9 step, success, skipped `[]`
  - `backend`: 12 step, success, skipped `[]`
  - `docker`: 6 step, success, skipped `[]`

### Giới hạn

- Đợt này **không chạy lại** Docker/stack; các bằng chứng Docker và e2e trong tài liệu là của đợt P0 trước (commit `a8c74e2`), đã ghi rõ nguồn trong mục 13 của runbook.
- Các giới hạn của đợt P0 vẫn nguyên: chưa nghiệm thu thiết bị thật (PC kiosk, tablet Android, Android TV box), chưa chạy trên PostgreSQL thật, chưa diễn tập `pg_dump`/`pg_restore`, chưa kiểm chứng "n8n chết" ở mức thiết bị.
- `docs/production-readiness.html` vẫn giữ verdict "Chưa đủ điều kiện": hai chặn cứng (chưa chứng minh backup/restore; chưa chạy stack production với PostgreSQL thật) **chưa được gỡ** trong đợt này.

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
