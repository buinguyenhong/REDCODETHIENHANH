# REDCODE — Runbook triển khai production thực tế

Ngày cập nhật: 2026-10-07. Áp dụng cho code từ `9b01d4a`, schema head `20261007_permissions`. Đặc tả: [project.md](../project.md). Nghiệm thu: [testing_guide.md](testing_guide.md).

**Bắt đầu tại [Sơ đồ triển khai từng bước](production_deployment_flow.md)** để xem luồng tổng thể, 12 bước triển khai, provisioning trạm và nhánh upgrade/rollback.

## Cập nhật: chế độ cài đặt PostgreSQL sau và n8n Admin

Head hiện tại `20261007_integrations`. Nếu `DATABASE_URL=` trong Docker, launcher phục vụ trang thiết lập thay vì main API: lấy mã `docker compose exec backend cat /app/config/setup-token`, nhập PostgreSQL URL và mật khẩu Admin trên browser; wizard kiểm tra, migrate, seed rồi chuyển ứng dụng. Network/user/database vẫn do IT chuẩn bị. Runtime config/secret lưu volume `redcode_runtime_config`, cần backup bảo mật cùng deployment secrets; bootstrap không dùng cho đổi DB hiện có.

n8n hiện quản lý trong `/admin/settings`, mặc định tắt sau migration kể cả env webhook cũ. Bật/test/lưu trên UI không cần restart. Khi tắt không tạo outbox mới; lần bật đầu không replay backlog trước cutoff. Các hướng dẫn N8N_* env bên dưới là cấu hình legacy, không còn là source runtime. Header/schema tham chiếu release cũ bên dưới chỉ dùng cho quy trình nền, kiểm tra `alembic current` theo release mới.

## 1. Mô hình triển khai

```text
PC/Android trên LAN → Nginx :80 (hoặc reverse proxy HTTPS nội bộ)
                          ├─ React/static/audio
                          └─ /api, /ws → FastAPI :8000 (không public)
                                           ├─ PostgreSQL hiện có
                                           └─ n8n webhook (không chặn alarm)
```

Compose hiện có chỉ tạo backend và nginx; không tạo PostgreSQL production. Backend chạy **1 Uvicorn worker**, vì WebSocket manager in-memory. PostgreSQL và audio phải persistent. Không tăng replicas/workers trước khi có thiết kế chia sẻ connection/routing được nghiệm thu.

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

Không chạy CREATE DATABASE khi nâng cấp DB đã có. User migration cần quyền tạo/alter bảng/index/sequence trong schema ứng dụng. Kiểm tra quyền schema theo chính sách PostgreSQL của đơn vị.

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

## 4. Cấu hình production

```bash
cp .env.example .env
chmod 600 .env
```

Chỉnh `.env` bằng trình soạn thảo trên server:

```dotenv
ENVIRONMENT=production
DEMO_MODE=false
DATABASE_URL=postgresql+asyncpg://redcode_app:<url-encoded-password>@<postgres-alias>:5432/redcode
SECRET_KEY=<secret-ngau-nhien-rieng-it-nhat-32-ky-tu>
INITIAL_ADMIN_PASSWORD=<mat-khau-khoi-tao-admin-rieng>
ALLOWED_ORIGINS=https://redcode.<internal-domain>
ACCESS_TOKEN_EXPIRE_MINUTES=1440
HEARTBEAT_INTERVAL_SECONDS=5
STATION_OFFLINE_THRESHOLD_SECONDS=15
N8N_WEBHOOK_URL=http://<integration-host>:5678/webhook/redcode/alarm
N8N_TIMEOUT_SECONDS=4
N8N_MAX_RETRIES=3
```

- Origin phải trùng scheme/host/port người dùng truy cập; không wildcard. HTTP LAN dùng origin `http://<ip-hoac-dns>` tương ứng.
- URL-encode ký tự đặc biệt trong password của database URL.
- Không dùng secret mẫu; có thể sinh bằng `openssl rand -hex 32` rồi lưu vào `.env`.
- Fresh production bootstrap chỉ tạo Admin; không có khoa/alarm/audio/trạm demo. `INITIAL_ADMIN_PASSWORD` cần cho lần khởi tạo đầu; sau bootstrap có thể bỏ giá trị và recreate backend. Biến này không đổi mật khẩu tài khoản đã tồn tại.
- n8n không dùng thì để `N8N_WEBHOOK_URL=`; outbox chưa gửi được giữ trong DB. Khi bật lại, theo dõi backlog.
- Compose hiện ép ENVIRONMENT=production. Thay `.env` cần recreate container, không chỉ restart.
- Giữ `.env` ngoài Git; không chia sẻ output `docker compose config` đã interpolate secret hoặc URL WebSocket có token.

### HTTPS nội bộ

Nginx repository hiện **listen HTTP 80**, chưa có TLS certificate/config. Nếu bệnh viện dùng HTTPS, TLS terminate tại reverse proxy nội bộ hiện có hoặc cấu hình Nginx/certificate trong deployment. Forward `/api`, `/assets/audio` và `/ws` cùng origin; proxy phải hỗ trợ Upgrade/WebSocket, timeout dài. Browser chọn `wss` theo scheme trang. Tắt/redact query credentials trong access logs tại **mọi** proxy; Nginx `/ws` và Uvicorn trong repo đã tắt access logs.

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

Head dự kiến `20261007_permissions` cho release này. Image backend cũng tự chạy `alembic upgrade head` trước Uvicorn; chạy migration thủ công ở trên giúp phát hiện lỗi trước mở API. Production không dùng `Base.metadata.create_all()` thay Alembic. Nginx build frontend trong image, không phụ thuộc dist có sẵn.

Không khởi động API nếu migration thất bại. Nếu port 80 đã do proxy khác dùng, chỉnh mapping Nginx hoặc routing proxy hiện có trước `up`.

## 6. Cấu hình nghiệp vụ và provisioning

1. Mở `/login`, đăng nhập Admin bootstrap; mở `/admin`.
2. Tạo khoa và users ADMIN/OPERATOR; chỉ ADMIN truy cập reports/export.
3. Upload audio local (WAV/MP3/OGG), dưới 20MB và chừa dung lượng multipart. Nginx body limit 20M nên file sát 20MB có thể bị 413; dùng file nhỏ hơn giới hạn này. Kiểm tra từng URL audio trả HTTP 200 và phát thực trên loa.
4. Tạo receiver groups, stations và memberships. Kiểm tra group-in/group-out bằng alarm thử; nếu UI thiếu thao tác membership, dùng API có sẵn ở `/api/docs`, không sửa DB tùy tiện.
5. Tạo alarm types: màu, audio sequence theo thứ tự, repeat/interval, validity mặc định 300 giây (range 10–86400), permission theo khoa. Alarm type không receiver group nhắm mọi trạm enabled.
6. Trên **từng máy nhận**, đăng nhập Admin → `/kiosk` → chọn trạm → XÁC NHẬN THIẾT BỊ. Browser tự lưu credential; không nhập/copy token. Xác nhận lại rotate token và ngắt máy dùng credential cũ.
7. Đăng xuất Admin nếu máy chỉ chạy receiver; mở `/kiosk` bằng profile browser cố định. Không xóa localStorage/profile sau provisioning. Đổi origin/profile cần xác nhận lại.
8. Chạy TEST LOA, TEST HIỂN THỊ, TEST KẾT NỐI; xác nhận nghe được vật lý, không chỉ READY trên UI.
9. Cấu hình kiosk auto-launch, volume/mute, power/screen sleep và thử reboot thiết bị. Ví dụ Windows launcher:

```cmd
chrome.exe --kiosk "https://redcode.<internal-domain>/kiosk" --autoplay-policy=no-user-gesture-required
```

Android cần kiosk browser autoplay được cấu hình hoặc WebView policy phù hợp. Nghiệm thu theo thiết bị/version thực; flag không thay bằng chứng loa.

## 7. Theo dõi sau triển khai

- `/api/health`: DB/core và n8n degraded; `/api/health/db`, `/api/health/websocket` để chẩn đoán. Health HTTP 200 **không đủ**: đọc JSON status/database, đối chiếu device monitor và heartbeat thật.
- Admin monitor: ONLINE/OFFLINE/audio/last seen; kiểm tra kết nối đúng trạm. HEARTBEAT mặc định 5s, offline threshold 15s, monitor tick 5s.
- Audit: CREATED, RECEIVED, DISPLAYED, audio, DISMISSED, ALARM_CANCELLED, EXPIRED, DEVICE_CONNECTED/DISCONNECTED và n8n attempts.
- Outbox lease stale 5 phút, retry capped exponential; n8n cần dedup stable Idempotency-Key. Job hết max attempts giữ FAILED; chưa có đầy đủ Admin retry UI, chuyển quy trình xử lý backlog cho người vận hành, không reset hàng loạt attempt tùy tiện.
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
5. Kiểm tra Alembic revision, counts alarms/events/station states, login, reports/XLSX, audio hashes/HTTP và alarm thử trên receiver test. Credential DB đã restore có thể tồn tại nhưng browser test phải được provisioning riêng; không nối máy production vào stack restore.
6. Ghi thời gian restore, RPO/RTO thực, chênh lệch counts/hash và evidence. Xóa môi trường drill sau khi hoàn tất theo quy trình lưu evidence.

## 10. Nâng cấp và rollback

### Upgrade

1. Nghiệm thu release trên staging với DB/audio bản sao; đọc migration/changelog.
2. Thông báo cửa sổ bảo trì và quy trình liên lạc thay thế; hoàn tất backup đã kiểm chứng.
3. `docker compose stop backend`; checkout release mới, build images; migrate như mục 5 khi API chưa chạy.
4. `docker compose up -d`; kiểm tra health/revision/login/station reconnect, alarm thử/cancel/dismiss/expiry/audio/report.
5. Theo dõi outbox backlog, audit/device và lưu evidence nghiệm thu trước bàn giao.

### DB dev cũ tạo bằng create_all

Không chạy initial migration lên DB có bảng; không stamp head để bỏ qua schema thiếu. Đường adoption tự động chưa có. DBA phải inventory schema/columns/FK/index/sequence, so sánh với migrations và thử trên bản sao. Chỉ chốt stamp/forward procedure khi đã chứng minh bảo toàn dữ liệu và alignment; ghi procedure theo DB thực tế.

### Rollback

Migration forward-only; **không** `alembic downgrade` hoặc xóa bảng. Khi cần rollback schema: dừng backend, phục hồi DB và audio từ cùng backup đã kiểm chứng, chạy đúng image/release tương ứng rồi smoke test/re-provision nếu cần. DBA chọn restore vào DB riêng và đổi DATABASE_URL hoặc quy trình restore được kiểm soát. Ghi rõ dữ liệu sau backup có thể không nằm trong bản phục hồi; giữ bản lỗi phục vụ đối soát.

## 11. Chẩn đoán nhanh

| Triệu chứng | Kiểm tra/hành động |
|---|---|
| Backend không start | Logs migration/config; PostgreSQL alias/network/quyền/secret/demo/origin; không dùng create_all sửa production |
| Nginx 502 | Backend status/log; migration chưa xong; proxy backend:8000 reachable |
| WS không kết nối | Proxy Upgrade, ws/wss/origin, credential rotated, station enabled; không paste URL token vào ticket |
| ONLINE nhưng không có alarm | Target snapshot/membership, permission, expiry, sync/dismiss tại trạm, đúng origin/profile |
| Visual có, audio lỗi | Local asset HTTP 200, browser error/autoplay, volume/mute/loa; thực hiện retry trên trạm |
| Audio upload 413 | Nginx body 20M tính cả multipart; giảm file size |
| n8n degraded | Core tiếp tục; xem webhook/network/attempt/backoff; workflow dedup; không xóa outbox |
| Report lệch ngày | Filter theo hospital local day, thời gian DB UTC, NTP/timezone; interval [start,next day) |

## 12. Bàn giao vận hành

Ghi: release hash/image, Alembic revision, topology/network/entry origin, inventory trạm/browser/loa, config/permissions/group mapping, backup/restore evidence, người trực và quy trình sự cố. Hoàn tất ma trận [kiểm thử](testing_guide.md). Những case chưa thực hiện ghi BLOCKED/PENDING; trạng thái local unit/live test không tự chứng nhận production-ready.
