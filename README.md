# REDCODE HOSPITAL — HƯỚNG DẪN VẬN HÀNH & TRIỂN KHAI

Hệ thống cảnh báo y tế khẩn cấp nội bộ Bệnh viện Đa khoa Thiện Hạnh (Redcode Hospital System), xây dựng tuân thủ 100% tài liệu đặc tả [REDCODE_SPEC.md](REDCODE_SPEC.md).

---

## 1. Kiến trúc hệ thống

```text
[Trình duyệt PC / Kiosk Android]
               │
               ▼ (Cổng 80)
        [Nginx Reverse Proxy]
          ├── /            -> React (Vite Production Build)
          ├── /assets/audio -> File âm thanh cục bộ (WAV/MP3)
          ├── /api/*       -> FastAPI HTTP
          └── /ws          -> FastAPI WebSocket (Realtime broadcast & Heartbeat)
               │
               ▼
        [FastAPI Core Server]
          ├── Quản lý WebSocket & hàng đợi FIFO
          ├── Giám sát Heartbeat 5s (ngắt sau 15s chuyển OFFLINE)
          ├── Background Worker gửi webhook n8n (có retry, không chặn còi)
          └── Ghi Audit Log bất biến (Lưu trữ vĩnh viễn)
               │
               ▼
     [PostgreSQL Container hiện có] (Database: redcode)
```

---

## 2. Tài khoản truy cập mặc định

| Vai trò | Tên đăng nhập | Mật khẩu | Quyền hạn |
| :--- | :--- | :--- | :--- |
| **Quản trị viên (Admin)** | `admin` | `admin123456` | Giám sát toàn viện, cấu hình trạm, danh mục báo động, audit log, xuất báo cáo |
| **Khoa Cấp cứu (Operator)** | `operator_cc` | `pass123456` | Bảng điều khiển phát các mã Redcode 1, 2, Báo cháy, Blue code |
| **Khoa Hồi sức (Operator)** | `operator_hscc`| `pass123456` | Phát và tiếp nhận báo động |
| **Trực ban Giám sát (Viewer)** | `viewer` | `pass123456` | Chỉ xem màn hình theo dõi và xuất báo cáo, không phát báo động |

---

## 3. Triển khai Production bằng Docker Compose

Trong môi trường bệnh viện, FastAPI và Nginx chạy qua Docker Compose, kết nối tới container PostgreSQL đã có sẵn:

1. **Cấu hình môi trường (`.env`)**:
   ```env
   ENVIRONMENT=production
   # Điền kết nối tới PostgreSQL container hiện có:
   DATABASE_URL=postgresql+asyncpg://postgres:matkhau@host.docker.internal:5432/redcode
   SECRET_KEY=khoa-bao-mat-redcode-thienhanh-32-ky-tu-tro-len
   N8N_WEBHOOK_URL=http://n8n:5678/webhook/redcode/alarm
   ```

2. **Khởi động dịch vụ**:
   ```bash
   docker compose up -d --build
   ```

3. **Cổng truy cập**:
   - Truy cập giao diện: `http://<IP_LAN_MAY_CHU>/`
   - Kiosk màn hình trạm: `http://<IP_LAN_MAY_CHU>/kiosk`
   - Bảng điều khiển: `http://<IP_LAN_MAY_CHU>/`
   - Quản trị & giám sát: `http://<IP_LAN_MAY_CHU>/admin`
   - Báo cáo: `http://<IP_LAN_MAY_CHU>/reports`

---

## 4. Chạy môi trường Phát triển / Kiểm thử Local (Dev Mode)

1. **Khởi chạy Backend (FastAPI)**:
   ```bash
   .\venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
   ```

2. **Khởi chạy Frontend (Vite Dev Server)**:
   ```bash
   cd frontend
   npm run dev
   ```
   Truy cập: `http://localhost:5173/`

3. **Chạy bộ kiểm thử tự động (Unit & Integration Tests)**:
   ```bash
   .\venv\Scripts\pytest backend/tests/test_redcode_core.py -v
   ```

4. **Chạy kịch bản kiểm thử E2E trực tiếp (Live E2E Verification)**:
   ```bash
   .\venv\Scripts\python.exe backend/tests/verify_e2e_live.py
   ```

---

## 5. Các tính năng nổi bật & Tuân thủ đặc tả

- **Độc lập 100% với Internet & n8n**: Toàn bộ luồng cảnh báo, còi hú và cơ sở dữ liệu nằm trên mạng nội bộ LAN. Nếu n8n gặp sự cố, hệ thống tự động ghi log lỗi `N8N_REQUEST_FAILED` và chuyển trạng thái n8n sang `DEGRADED`, còi báo động tại các trạm hoàn toàn không bị ảnh hưởng.
- **Local Dismiss**: Khi trạm A bấm tắt cảnh báo, chỉ có trạm A ngừng phát âm thanh và đóng popup. Các trạm khác trong nhóm nhận vẫn tiếp tục báo động cho đến khi được nhân viên tại trạm đó tắt cục bộ.
- **FIFO Queue**: Nếu có nhiều cảnh báo liên tiếp, hệ thống xếp hàng theo thứ tự thời gian server sequence, trình chiếu tuần tự không bao giờ làm mất báo động.
- **Tự động phục hồi kết nối**: Máy trạm tự động thử kết nối lại WebSocket với thuật toán Exponential Backoff và đồng bộ trạng thái khi kết nối thành công.
- **Audio Readiness**: Cơ chế kiểm tra quyền tự động phát âm thanh của trình duyệt, cung cấp nút bấm bật âm thanh rõ ràng và theo dõi trạng thái `AUDIO_READY` từ xa qua màn hình Admin.
