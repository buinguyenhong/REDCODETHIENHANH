# REDCODE — Runbook triển khai production

Ngày cập nhật: 2026-10-11. Áp dụng cho code từ `84ad2d6`, schema head `20261007_integrations`. Đặc tả: [project.md](../project.md). Nghiệm thu: [testing_guide.md](testing_guide.md). Luồng từng bước: [Sơ đồ triển khai](production_deployment_flow.md).

## 0. Đọc trước: những gì khác so với bản runbook cũ

Nếu bạn từng triển khai REDCODE theo tài liệu trước đây, bốn thay đổi dưới đây ảnh hưởng trực tiếp tới thao tác vận hành:

1. **Cấu hình chỉ bằng `.env`.** Chế độ cài đặt database trong ứng dụng (wizard) và trang Admin quản lý n8n đã bị gỡ. Không còn `/setup`, không còn `setup-token`, không còn `/admin/settings`, không còn volume `redcode_runtime_config` để backup. PostgreSQL phải do IT dựng sẵn; REDCODE chỉ kết nối.
2. **Trạng thái trạm nay trung thực hơn, nên có thể *khác* những gì bạn quen thấy.** Một trạm chỉ được đánh `ONLINE`/`AUDIO READY` khi nó **thật sự có kênh WebSocket**. Nhịp tim HTTP không có socket không còn ghi `audio_ready`/`client_ready` (trước đây dashboard hiện "AUDIO READY" cho thiết bị không hú được). Khởi động lại máy chủ **xóa** toàn bộ cờ cũ: sau restart mọi trạm hiện `OFFLINE` cho tới khi kết nối lại. Trạm nào vẫn hiện ONLINE mà không có socket là lỗi, không phải bình thường.
3. **Báo cáo phát báo động nói rõ số trạm thật sự nhận.** Phản hồi tạo báo động có `target_station_count` (số trạm đích) và `delivered_station_count` (số trạm đã gửi thành công). Người trực phải đọc cả hai. Phát lại một báo động **đã kết thúc** (CANCELLED/EXPIRED) trả **409** thay vì trả lại bản ghi cũ với 201 — trước đây thao tác này khiến người trực tưởng vừa phát được báo động trong khi không còi nào hú.
4. **Mã đóng WebSocket có nghĩa cụ thể.** `4001` = phiên trạm bị thiết bị khác chiếm chỗ (client chờ 15 giây rồi mới thử lại); `1008` = credential bị từ chối (client **dừng thử lại vĩnh viễn**, phải xác nhận lại thiết bị); `1011` = hết nhịp tim. Đừng xóa `localStorage`/profile browser của máy trạm để "thử lại" — làm vậy mất credential và phải provisioning lại.

Hai điểm hạ tầng đi kèm: `/api/health` trả `websocket: "degraded"` **và `status: "degraded"`** khi vòng giám sát nhịp tim chết (trạm rút điện sẽ hiện ONLINE mãi mãi, và báo động hết hạn không còn được chuyển sang EXPIRED), và `nginx/default.conf` nay khai báo tường minh kiểu media cho `/assets/audio/` — trước đây tệp `.wav` được trả về dạng `application/octet-stream` và trình duyệt có quyền từ chối phát.

Hai endpoint chẩn đoán `/api/health/db` và `/api/health/websocket` nay **yêu cầu đăng nhập ADMIN**. `/api/health` công khai vẫn trả các trường tổng hợp nhưng không có mã trạm và không có thông báo lỗi thô. Nếu có probe hạ tầng đang đọc hai endpoint con, phải cấp token ADMIN cho probe đó hoặc bỏ probe đi.

Bảng `integration_settings` vẫn nằm trong schema (migration forward-only, không drop) nhưng **không còn được đọc/ghi**; cấu hình n8n nay chỉ đến từ `.env`.

## 1. Mô hình triển khai

```text
PC/Android trên LAN → Nginx :80 (hoặc reverse proxy HTTPS nội bộ)
                          ├─ React/static/audio
                          └─ /api, /ws → FastAPI :8000 (không public)
                                           ├─ PostgreSQL hiện có
                                           └─ n8n webhook (không chặn alarm)
```

Compose trong repo chỉ tạo **backend** và **nginx**; không tạo PostgreSQL production. Backend chạy **1 Uvicorn worker** (`--workers 1`) vì WebSocket manager là in-memory — tăng worker/replica sẽ làm trạm kết nối vào worker này mà không nhận được báo động phát từ worker khác. PostgreSQL và audio phải persistent. Không tăng replicas/workers trước khi có thiết kế chia sẻ connection/routing được nghiệm thu.

## 2. Chuẩn bị môi trường

| Thành phần | Thông tin cần chốt tại bệnh viện |
|---|---|
| Server | Ubuntu/Linux, Docker Engine + Compose plugin, disk/backup/UPS đủ cho dữ liệu lưu dài hạn |
| PostgreSQL | Container/host hiện có, version, network/alias, user DB riêng, DB `redcode` |
| LAN | IP/DNS ổn định, VLAN/routing tới các khoa; entry point 80 hoặc 443; không expose 8000/5432 tới clients |
| Thời gian | Server/DB/PC/Android đồng bộ NTP; UI/report Asia/Ho_Chi_Minh, DB timestamps UTC |
| Thiết bị | PC/Android, browser version, launcher kiosk, loa/volume/mute/sleep policy |
| n8n | URL backend truy cập được, timeout/retries, workflow dedup theo Idempotency-Key |
| Backup | Nơi lưu DB/audio/release/config, retention, người vận hành và mục tiêu RPO/RTO |

Các lệnh dưới đây dùng **Bash trên Linux server**, tại root checkout trừ khi ghi khác. Thay placeholders trước khi chạy; không đưa credentials thật vào báo cáo.

```bash
git clone https://github.com/buinguyenhong/REDCODETHIENHANH.git
cd REDCODETHIENHANH
git checkout <release-commit-da-nghiem-thu>
docker info
docker compose version
git rev-parse HEAD
```

Nếu server không có Internet: chuẩn bị source release và images tại máy build có kết nối, `docker save`/`docker load`, chuyển qua kênh nội bộ. Runtime không tải CDN/audio từ Internet. Build và cài dependency vẫn cần registry/package cache hoặc images đã chuẩn bị.

## 3. Database và network

### 3.1 Fresh install

DBA tạo database/user riêng trên **PostgreSQL hiện có**, bằng công cụ quản trị được sử dụng tại bệnh viện. Ví dụ SQL, chạy dưới tài khoản quản trị DB:

```sql
CREATE ROLE redcode_app LOGIN PASSWORD '<mat-khau-rieng>';
CREATE DATABASE redcode OWNER redcode_app;
```

Không chạy `CREATE DATABASE` khi nâng cấp DB đã có. User migration cần quyền tạo/alter bảng/index/sequence trong schema ứng dụng. Kiểm tra quyền schema theo chính sách PostgreSQL của đơn vị.

### 3.2 External Docker network

Trong `docker-compose.yml`, bật network cho **backend** và khai báo cuối file:

```yaml
services:
  backend:
    networks:
      - redcode_net
      - existing_postgres_network
networks:
  redcode_net:
    driver: bridge
  existing_postgres_network:
    external: true
    name: <network-thuc-te-cua-postgresql>
```

Đây là đoạn chỉnh sửa vào file có sẵn, không thay cả Compose. PostgreSQL phải thuộc network đó; `DATABASE_URL` dùng hostname/alias của PostgreSQL trên network, **không dùng localhost** trong backend container. n8n ở network khác cần hostname LAN reachable hoặc network attachment phù hợp.

```bash
docker network inspect <network-thuc-te-cua-postgresql>
```

## 4. Cấu hình production bằng `.env`

```bash
cp .env.example .env
chmod 600 .env
```

`.env.example` là danh sách biến đầy đủ. Giá trị production tối thiểu:

```dotenv
ENVIRONMENT=production
DEMO_MODE=false
INITIAL_ADMIN_PASSWORD=<mat-khau-khoi-tao-admin-rieng>
DATABASE_URL=postgresql+asyncpg://redcode_app:<url-encoded-password>@<postgres-alias>:5432/redcode
SECRET_KEY=<secret-ngau-nhien-rieng-it-nhat-32-ky-tu>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
HEARTBEAT_INTERVAL_SECONDS=5
STATION_OFFLINE_THRESHOLD_SECONDS=15
N8N_ENABLED=true
N8N_WEBHOOK_URL=http://<integration-host>:5678/webhook/redcode/alarm
N8N_TIMEOUT_SECONDS=4
N8N_MAX_RETRIES=3
ALLOWED_ORIGINS=https://redcode.<internal-domain>
PORT=8000
HOST=0.0.0.0
```

Ràng buộc mà `app/config.py` **chặn ngay lúc khởi động** khi `ENVIRONMENT=production` (không có cách vượt qua từ UI):

| Ràng buộc | Thông báo khi vi phạm |
|---|---|
| `DATABASE_URL` phải là `postgresql+asyncpg://` | Production requires a postgresql+asyncpg:// DATABASE_URL |
| `DEMO_MODE` phải là `false` | (cùng thông báo trên) |
| `SECRET_KEY` ≥ 32 ký tự, không bắt đầu bằng `redcode-secret`/`change-this` | Production requires a unique SECRET_KEY of at least 32 characters |
| `ALLOWED_ORIGINS` không được chứa `*` | Production requires an explicit origin allowlist |
| `N8N_ENABLED=true` thì `N8N_WEBHOOK_URL` không được rỗng | N8N_ENABLED=true requires N8N_WEBHOOK_URL |

Ghi chú vận hành:

- Origin phải trùng scheme/host/port người dùng truy cập. HTTP LAN dùng origin `http://<ip-hoac-dns>` tương ứng.
- URL-encode ký tự đặc biệt trong password của database URL.
- Không dùng secret mẫu; sinh bằng `openssl rand -hex 32` rồi lưu vào `.env`.
- **Fresh production bootstrap chỉ tạo tài khoản Admin**, không có khoa/alarm/audio/trạm demo. Thiếu `INITIAL_ADMIN_PASSWORD` trên DB trắng thì tiến trình seed **dừng với lỗi** — đây là chủ ý, không phải sự cố. Biến này không đổi mật khẩu của tài khoản admin đã tồn tại; sau bootstrap có thể bỏ giá trị và recreate backend.
- n8n không dùng thì để `N8N_ENABLED=false`; hệ thống báo động nội bộ chạy bình thường và không tạo bản ghi outbox nào.
- Compose **ép** `ENVIRONMENT=production` và đọc `DATABASE_URL`/`SECRET_KEY` từ chính `.env` của thư mục dự án. Sửa `.env` cần **recreate** container (`up -d`), restart đơn thuần không nạp env mới.
- Giữ `.env` ngoài Git; không chia sẻ output `docker compose config` đã interpolate secret hoặc URL WebSocket có token.

### HTTPS nội bộ

Nginx trong repo **listen HTTP 80**, chưa có TLS certificate/config. Nếu bệnh viện dùng HTTPS, TLS terminate tại reverse proxy nội bộ hiện có hoặc cấu hình Nginx/certificate trong deployment. Forward `/api`, `/assets/audio` và `/ws` cùng origin; proxy phải hỗ trợ Upgrade/WebSocket, timeout dài. Browser chọn `wss` theo scheme trang. Tắt/redact query credentials trong access logs tại **mọi** proxy; Nginx `/ws` và Uvicorn trong repo đã tắt access logs.

## 5. Build, migration và startup

```bash
docker compose config --quiet
docker compose build
# Fresh install hoặc upgrade đã backup: migrate khi API chưa chạy.
docker compose run --rm --no-deps backend alembic upgrade head
docker compose up -d
docker compose ps
docker compose exec -T backend alembic current
docker compose exec -T nginx nginx -t
curl --fail --silent --show-error http://127.0.0.1/api/health
docker compose logs --tail=100 backend nginx
```

Kết quả mong đợi:

- `alembic current` → **`20261007_integrations (head)`** cho release này. Chuỗi đầy đủ khi migrate DB trắng: `8280022f67e9 → 20261006_runtime → 20261006_validity → 20261007_permissions → 20261007_integrations`.
- `/api/health` → HTTP 200 với `{"status":"ok","liveness":"ok","database":"ok","websocket":"ok",...}`. `websocket` phải là `ok`. Ba giá trị có thể gặp và ý nghĩa:
  - `ok` — vòng giám sát nhịp tim đang chạy.
  - `degraded` — **đã bật rồi chết**. `status` cũng thành `degraded`: không trạm nào được đánh offline nữa và báo động hết hạn không được kết thúc. Dừng triển khai, xem log backend.
  - `not_started` — chưa chạy tới bước bật monitor (app đang khởi động, hoặc đã dừng theo lệnh). Không phải sự cố, nhưng nếu đứng yên ở giá trị này sau khi log đã báo `Station offline monitor active` thì là lỗi.
  `status` là readiness (database **và** vòng giám sát); `liveness` là "tiến trình còn phục vụ được request". Liveness hỏng thì restart; readiness `degraded` thì sửa thành phần đang suy giảm.
- Log backend phải có `Station offline monitor active` và `Durable notification outbox worker active`.

Image backend cũng tự chạy `alembic upgrade head` trước Uvicorn; chạy migration thủ công ở trên giúp phát hiện lỗi trước khi mở API. Production không dùng `Base.metadata.create_all()` thay Alembic. Nginx build frontend trong image, không phụ thuộc dist có sẵn.

Không khởi động API nếu migration thất bại. Nếu port 80 đã do proxy khác dùng, chỉnh mapping Nginx hoặc routing proxy hiện có trước `up`.

### Kiểm tra đường phục vụ âm thanh (bắt buộc, không bỏ qua)

```bash
curl -sI http://127.0.0.1/assets/audio/<ten-tep-coi>.wav | grep -i content-type
```

Phải trả `Content-Type: audio/wav` (mp3 → `audio/mpeg`). Nếu thấy `application/octet-stream`, Nginx đang chạy config cũ: trình duyệt có quyền từ chối phát `<audio>`, nghĩa là trạm hiện báo động trên màn hình mà loa không kêu.

## 6. Cấu hình nghiệp vụ và provisioning

1. Mở `/login`, đăng nhập Admin bootstrap; mở `/admin`.
2. Tạo khoa và users ADMIN/OPERATOR; chỉ ADMIN truy cập reports/export.
3. Upload audio local (WAV/MP3/OGG), dưới 20MB và chừa dung lượng multipart. Nginx body limit 20M nên file sát 20MB có thể bị 413; dùng file nhỏ hơn giới hạn này. Kiểm tra từng URL audio trả HTTP 200 **và đúng `Content-Type`** (mục 5).
4. Tạo receiver groups, stations và memberships. Kiểm tra group-in/group-out bằng alarm thử; nếu UI thiếu thao tác membership, dùng API có sẵn ở `/api/docs`, không sửa DB tùy tiện.
5. Tạo alarm types: màu, audio sequence theo thứ tự, repeat/interval, validity mặc định 300 giây (range 10–86400), permission theo khoa. **Mỗi alarm type bắt buộc có ít nhất một tệp âm thanh** — tạo hoặc cập nhật với `audio_sequence` rỗng bị từ chối 422 (trước đây tạo được một mã báo động câm). Alarm type không receiver group nhắm mọi trạm enabled.
6. Trên **từng máy nhận**, đăng nhập Admin → `/kiosk` → chọn trạm → XÁC NHẬN THIẾT BỊ. Browser tự lưu credential; không nhập/copy token. Xác nhận lại rotate token và ngắt máy dùng credential cũ (đóng bằng `1008` kèm lý do).
7. Đăng xuất Admin nếu máy chỉ chạy receiver; mở `/kiosk` bằng profile browser cố định. Không xóa localStorage/profile sau provisioning. Đổi origin/profile cần xác nhận lại.
8. Chạy TEST LOA, TEST HIỂN THỊ, TEST KẾT NỐI; xác nhận nghe được vật lý, không chỉ READY trên UI.
9. Cấu hình kiosk auto-launch, volume/mute, power/screen sleep và thử reboot thiết bị. Ví dụ Windows launcher:

```cmd
chrome.exe --kiosk "https://redcode.<internal-domain>/kiosk" --autoplay-policy=no-user-gesture-required
```

Android cần kiosk browser autoplay được cấu hình hoặc WebView policy phù hợp. Nghiệm thu theo thiết bị/version thực; flag không thay bằng chứng loa.

Khi sửa cấu hình một trạm đang trực: đổi **tên/vị trí/nhóm nhận** không ngắt thiết bị (credential giữ nguyên). Đổi **token** hoặc **mã trạm** sẽ đóng socket cũ kèm lý do đọc được — thiết bị đó cần được xác nhận lại tại chỗ.

## 7. Theo dõi sau triển khai

- `/api/health`: đọc **từng trường**, không chỉ HTTP 200. `status` (readiness), `liveness`, `database`, `websocket` (`degraded` = vòng giám sát nhịp tim đã chết; `not_started` = chưa bật), `n8n`, `active_stations`/`total_stations`. **Trường `n8n` ở đây là cấu hình** (`enabled`/`disabled`), không phải khả năng kết nối: endpoint này không gọi ra mạng ngoài, nên nó không biết n8n còn sống hay không — và cũng không được để độ trễ của n8n quyết định độ trễ phép đo sức khoẻ hệ thống chính. Muốn biết n8n có sống, gọi riêng `GET /api/health/n8n` (token **ADMIN**, trả `status`/`reachable`/`latency_ms`). Chẩn đoán sâu cần **token ADMIN**: `/api/health/db` (kèm latency), `/api/health/websocket` (danh sách mã trạm đang kết nối, `monitor_running`).
- Admin monitor: ONLINE/OFFLINE/audio/last seen. `ONLINE` nghĩa là có WebSocket thật; `AUDIO READY` chỉ có giá trị khi trạm đang ONLINE. HEARTBEAT mặc định 5s, offline threshold 15s, monitor tick 5s.
- Sau mỗi lần phát báo động, đối chiếu `target_station_count` với `delivered_station_count`. Lệch nhau nghĩa là có trạm đích chưa nhận được — xử lý theo mục 11, không coi là "đã phát xong".
- Audit: CREATED, RECEIVED, DISPLAYED, audio, DISMISSED, ALARM_CANCELLED, EXPIRED, DEVICE_CONNECTED/DISCONNECTED và n8n attempts.
- Outbox lease stale 5 phút, retry capped exponential; n8n cần dedup stable Idempotency-Key. Vòng đời bản ghi nay tường minh: `PENDING → PROCESSING → SENT` (xong), hoặc `FAILED` + `next_attempt_at` (còn thử lại), hoặc `EXHAUSTED` (đã bỏ hẳn). Đếm và xem danh sách `EXHAUSTED` ở `GET /api/system/status` → `notification_outbox`; phát lại bằng `POST /api/system/outbox/requeue-exhausted` (ADMIN). **Bật lại n8n không tự phát lại** các thông báo đã bỏ hẳn — đó là chủ ý, tránh dội một loạt thông báo cũ vào hệ thống nhận; người vận hành phải quyết định. **Lệnh phát lại có trần**: `?limit=` mặc định 50, tối đa 200 mỗi lần gọi, hoặc `?ids=1&ids=2` để chỉ phát lại đúng các bản ghi đã chọn theo `exhausted_recent`. Phản hồi trả `requeued`, `limit`, `remaining_exhausted`, `has_more` — gọi lặp theo `has_more` khi cần phát lại nhiều hơn. Trần này là chủ ý: một lần gọi không giới hạn sẽ đẩy cả lịch sử lỗi nhiều tuần vào hàng đợi cùng lúc, và n8n vừa hồi phục sẽ nhận một đợt dội ngay lập tức. Gửi lại an toàn về trùng lặp vì mỗi bản ghi giữ nguyên `Idempotency-Key: redcode-outbox-{id}`.
- Theo dõi disk DB/audio/logs, backup completion/restore drill và clocks. Không xóa audit/history để giảm dung lượng.

## 8. Backup DB + audio + release

Thực hiện trong cửa sổ bảo trì: dừng phát alarm và cấu hình/upload. Dừng backend để DB và audio snapshot nhất quán. Biến shell dưới đây dùng tên thực tế, không chứa password:

```bash
export PG_CONTAINER='<postgres-container-hien-co>'
export PG_USER='<backup-role>'
export PG_DATABASE='redcode'
export BACKUP_DIR='/srv/redcode-backups/<timestamp>'
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
git rev-parse HEAD > "$BACKUP_DIR/release-commit.txt"
docker compose stop backend
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DATABASE" -Fc > "$BACKUP_DIR/redcode.dump"
test -s "$BACKUP_DIR/redcode.dump"
docker run --rm --mount type=volume,src=redcode_audio_data,dst=/audio,readonly \
  --mount "type=bind,src=$BACKUP_DIR,dst=/backup" alpine:3.20 \
  tar -czf /backup/audio.tar.gz -C /audio .
sha256sum "$BACKUP_DIR/redcode.dump" "$BACKUP_DIR/audio.tar.gz" > "$BACKUP_DIR/SHA256SUMS"
docker compose start backend
```

Chuẩn bị helper image `alpine:3.20` trước nếu môi trường offline. `pg_dump` cần authentication DB theo phương thức DBA thiết lập; dùng secret/pgpass được bảo vệ, không truyền password thật trong command/history. Nếu bất kỳ command FAIL, không ghi backup thành công; khôi phục dịch vụ theo tình trạng thực và xử lý lỗi.

Lưu thêm deployment Compose/TLS config, `.env` trong **kho backup secrets có kiểm soát truy cập**, image/release tags và version PostgreSQL. `.env` không để cùng evidence báo cáo thông thường. Backup file không phải bằng chứng restore.

## 9. Restore drill trên môi trường riêng

1. DBA tạo DB **test restore riêng** trên PostgreSQL hiện có, không ghi vào DB production.
2. Restore dump vào DB test:

```bash
docker exec -i "$PG_CONTAINER" pg_restore -U "$PG_USER" -d '<database-restore-test-trong>' \
  --no-owner --no-privileges --exit-on-error < "$BACKUP_DIR/redcode.dump"
```

3. Tạo audio volume **riêng**, restore archive bằng helper:

```bash
docker volume create redcode_restore_audio
docker run --rm --mount type=volume,src=redcode_restore_audio,dst=/audio \
  --mount "type=bind,src=$BACKUP_DIR,dst=/backup,readonly" alpine:3.20 \
  tar -xzf /backup/audio.tar.gz -C /audio
```

4. Checkout đúng release, chạy stack restore **riêng** với Compose copy/override: container names riêng, port khác, volume name `redcode_restore_audio`, DATABASE_URL trỏ DB test, secret riêng, n8n tắt hoặc endpoint test. Compose gốc có fixed container names/audio volume nên chỉ `-p` **không đủ** để cách ly.
5. Kiểm tra Alembic revision, counts alarms/events/station states, login, reports/XLSX, audio hashes/HTTP (kèm `Content-Type`) và alarm thử trên receiver test. Credential DB đã restore có thể tồn tại nhưng browser test phải được provisioning riêng; không nối máy production vào stack restore.
6. Ghi thời gian restore, RPO/RTO thực, chênh lệch counts/hash và evidence. Xóa môi trường drill sau khi hoàn tất theo quy trình lưu evidence.

## 10. Nâng cấp và rollback

### Upgrade

1. Nghiệm thu release trên staging với DB/audio bản sao; đọc migration/changelog.
2. Thông báo cửa sổ bảo trì và quy trình liên lạc thay thế; hoàn tất backup đã kiểm chứng.
3. `docker compose stop backend`; checkout release mới, build images; migrate như mục 5 khi API chưa chạy.
4. `docker compose up -d`; kiểm tra health/revision/login/station reconnect, alarm thử/cancel/dismiss/expiry/audio/report.
5. Theo dõi outbox backlog, audit/device và lưu evidence nghiệm thu trước bàn giao.

Lưu ý khi upgrade lên release này: sau `up -d`, mọi trạm hiện `OFFLINE` cho tới khi thiết bị kết nối lại — đây là hành vi đúng (cờ cũ bị xóa), không phải sự cố. Cửa sổ bảo trì nên có người xác nhận từng máy trạm trở lại ONLINE.

### DB dev cũ tạo bằng create_all

Không chạy initial migration lên DB có bảng; không stamp head để bỏ qua schema thiếu. Đường adoption tự động chưa có. DBA phải inventory schema/columns/FK/index/sequence, so sánh với migrations và thử trên bản sao. Chỉ chốt stamp/forward procedure khi đã chứng minh bảo toàn dữ liệu và alignment; ghi procedure theo DB thực tế.

### Rollback

Migration forward-only; **không** `alembic downgrade` hoặc xóa bảng. Khi cần rollback schema: dừng backend, phục hồi DB và audio từ cùng backup đã kiểm chứng, chạy đúng image/release tương ứng rồi smoke test/re-provision nếu cần. DBA chọn restore vào DB riêng và đổi DATABASE_URL hoặc quy trình restore được kiểm soát. Ghi rõ dữ liệu sau backup có thể không nằm trong bản phục hồi; giữ bản lỗi phục vụ đối soát.

## 11. Chẩn đoán nhanh

| Triệu chứng | Kiểm tra/hành động |
|---|---|
| Backend không start | Log migration/config; PostgreSQL alias/network/quyền/secret/demo/origin; không dùng create_all sửa production. Lỗi `Fresh production installation requires INITIAL_ADMIN_PASSWORD` là thiếu biến, không phải lỗi DB |
| `/api/health` trả `websocket: degraded` | Vòng giám sát nhịp tim đã chết — không trạm nào được đánh offline nữa và báo động hết hạn không được kết thúc. `status` cũng là `degraded`. Restart backend và kiểm tra log; coi mọi trạng thái ONLINE hiện tại là không đáng tin |
| `/api/health` trả `websocket: not_started` | Chưa chạy tới bước bật monitor. Bình thường trong vài giây đầu khi khởi động; nếu đứng yên thì app không chạy hết lifespan — xem log có dòng `Station offline monitor active` chưa |
| `/api/health/db` hoặc `/api/health/websocket` trả 401/403 | Đúng thiết kế: hai endpoint chẩn đoán yêu cầu token **ADMIN** (trước đây công khai và lộ chi tiết hạ tầng). Dùng token ADMIN, hoặc đọc các trường tổng hợp ở `/api/health` công khai |
| Trạm hiện ONLINE nhưng không nhận alarm | Kiểm tra `/api/health/websocket` (token ADMIN) xem mã trạm có trong `active_station_codes` không. Nếu không có, dashboard đang hiện trạng thái cũ: cho thiết bị kết nối lại |
| n8n có thông báo không gửi được | `GET /api/system/status` → `notification_outbox`: `retryable_failed` là còn thử lại, `exhausted` là đã bỏ hẳn. Xem `exhausted_recent` để biết `alarm_id` và `last_error`. Xác nhận n8n đã sống lại bằng `GET /api/health/n8n` (token ADMIN) **trước khi** phát lại — nếu chưa sống thì phát lại chỉ đẩy chúng về `EXHAUSTED` lần nữa. Rồi phát lại bằng `POST /api/system/outbox/requeue-exhausted`, có trần `?limit=` (mặc định 50) hoặc `?ids=` cho từng bản ghi; đọc `remaining_exhausted`/`has_more` trong phản hồi để biết còn lại bao nhiêu |
| Trạm không kết nối được, UI báo phiên bị chiếm | Đang có thiết bị khác mở cùng mã trạm (đóng `4001`). Tìm máy thứ hai, không xóa profile để "thử lại" |
| Trạm dừng thử lại vĩnh viễn | Credential bị từ chối (`1008`). Đọc lý do trong log/console; nếu do thu hồi token hoặc đổi mã trạm thì phải XÁC NHẬN THIẾT BỊ lại tại chỗ |
| Nginx 502 | Backend status/log; migration chưa xong; proxy backend:8000 reachable |
| WS không kết nối | Proxy Upgrade, ws/wss/origin, credential rotated, station enabled; không paste URL token vào ticket |
| ONLINE nhưng không có alarm | Target snapshot/membership, permission, expiry, sync/dismiss tại trạm, đúng origin/profile |
| `delivered_station_count` < `target_station_count` | Có trạm đích chưa nhận: xem `active_station_codes`, thiết bị mất mạng, hoặc socket chết vừa bị dọn. Phát lại sau khi xử lý (cùng `idempotency_key` trả lại báo động đang hiệu lực; nếu đã kết thúc sẽ bị từ chối **409** — phát báo động mới) |
| Visual có, audio lỗi | `curl -sI` kiểm tra `Content-Type` của asset; browser error/autoplay, volume/mute/loa; thực hiện retry trên trạm |
| Audio upload 413 | Nginx body 20M tính cả multipart; giảm file size |
| Không tạo được alarm type | `audio_sequence` rỗng bị từ chối 422 — mỗi loại báo động phải có ít nhất một tệp âm thanh |
| n8n degraded | Core tiếp tục; xem webhook/network/attempt/backoff; workflow dedup; không xóa outbox |
| Report lệch ngày | Filter theo hospital local day, thời gian DB UTC, NTP/timezone; interval [start,next day) |

## 12. Bàn giao vận hành

Ghi: release hash/image, Alembic revision, topology/network/entry origin, inventory trạm/browser/loa, config/permissions/group mapping, backup/restore evidence, người trực và quy trình sự cố. Hoàn tất ma trận [kiểm thử](testing_guide.md). Những case chưa thực hiện ghi BLOCKED/PENDING; trạng thái local unit/live test không tự chứng nhận production-ready.

## 13. Bằng chứng đã có và giới hạn

**Chạy lại trong đợt rà soát 5 phát hiện (2026-10-11, sau commit của đợt này):**

| Hạng mục | Kết quả |
|---|---|
| Bộ test backend | **76 passed** trên DB SQLite tạm mới (`DATABASE_URL` trỏ file tạm, không dùng `backend/redcode.db`) |
| Bộ test frontend (`npm test`) | **19 passed, 0 fail** |
| `npm run build` | PASS (282.25 kB js / 29.40 kB css) |
| Test live qua uvicorn thật (`tests/test_live_transport.py`) | **1 passed** — server thật chạy hết lifespan, `/api/health` trả 200 |
| 5 test mới bắt được lỗi cũ | **5/5** — mỗi test chạy lại trên code đã hoàn nguyên đúng dòng lỗi cũ và **fail**; sau đó trả file về nguyên trạng |

**Từ đợt nghiệm thu Docker trước đó cùng ngày (không chạy lại trong đợt này):**

| Hạng mục | Kết quả |
|---|---|
| `docker compose build` / `up` | PASS; cả hai container `Up` |
| Chuỗi Alembic trên DB trắng | PASS toàn bộ `8280022f67e9 → 20261007_integrations`, seed thành công |
| `/api/health` qua Nginx | `{"status":"ok","database":"ok","websocket":"ok","n8n":"disabled",...}` |
| Khói end-to-end qua Nginx | **23/23 đạt** (đăng nhập, trạm WS, phát báo động, đếm trạm nhận, phát lại, hủy, `SYNC_REQUIRED`, đóng `4001`, nhịp tim sai token `401`) |
| Khói khởi động lại | **8/8 đạt** (cờ cũ bị xóa, trạm OFFLINE, kết nối lại nhận `SYNC_REQUIRED` và đồng bộ đúng báo động còn hiệu lực) |
| `curl -I /assets/audio/red_code_1.wav` | `200` + `Content-Type: audio/wav` |
| CI GitHub Actions | run `38114856575` trên `a8c74e2`: `completed/success`, cả ba job backend/frontend/docker success, không step nào bị skip |

**Chưa có bằng chứng — không được coi là đã nghiệm thu:**

- **Thiết bị thật**: chưa có PC Windows kiosk, tablet Android hay Android TV box nào chạy thử. Phát âm thanh thực tế, chính sách autoplay của trình duyệt, và độ trễ trên LAN 50–100 thiết bị **chưa được kiểm chứng**.
- **PostgreSQL thật của REDCODE**: chuỗi Alembic và toàn bộ suite có chạy thật trên PostgreSQL 16 trong CI (service tạm), nhưng **chưa** chạy trên instance PostgreSQL production của bệnh viện.
- **Sao lưu/phục hồi**: chưa diễn tập `pg_dump`/`pg_restore` khứ hồi (mục 8–9) vì chưa có DB PostgreSQL của REDCODE.
- **n8n chết không ảnh hưởng báo động**: mới kiểm ở mức API/outbox, chưa ở mức thiết bị thật.
- **Phát lại thông báo n8n đã bỏ hẳn**: `POST /api/system/outbox/requeue-exhausted` đã được kiểm bằng test tự động (giới hạn số lượng, chọn theo `ids`, đưa bản ghi về `PENDING`, `attempt_count` về 0, trả `remaining_exhausted`); **chưa** chạy với một n8n thật đang sống lại để xác nhận n8n khử trùng đúng theo `Idempotency-Key`.
