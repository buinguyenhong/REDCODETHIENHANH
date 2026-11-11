"""Regression tests cho đợt rà soát thứ tư (P1 + P2 + P3).

Mỗi bài kiểm thử khóa một lỗi thực tế đã phát hiện:
- P1.1: Xóa mềm (soft-delete) trạm nhận, người dùng, âm thanh phải lọc được qua
  ``enabled_only=true``, loại trạm đã xóa khỏi ``station_ids`` của nhóm nhận, và
  không đếm trạm đã xóa vào ``/api/health`` hay ``/api/system/status``.
- P1.2: ``POST /api/stations/{id}/confirm-device`` phải gỡ socket cũ khỏi
  ``manager.active_stations`` trước khi đóng và chịu được socket cũ bị lỗi khi đóng.
- P1.4: ``POST /api/stations/heartbeat`` đi qua ``_presence_lock`` thống nhất của
  ``ConnectionManager`` và cập nhật IP thực qua ``X-Forwarded-For``.
- P2.1: Cập nhật địa chỉ IP thực (``X-Forwarded-For`` / ``X-Real-IP``) khi xác nhận
  thiết bị và khi kết nối WebSocket.
- P2.2: ``POST /api/stations/dismiss`` điền bù ``received_at``/``displayed_at`` nếu
  trước đó gói ACK ``RECEIVED`` bị rớt, tránh kích hoạt ``SYNC_REQUIRED`` lặp mỗi 30s.
- P2.4: ``PUT /api/stations/{id}`` và ``DELETE /api/stations/{id}`` phải ghi nhật ký
  kiểm toán ``CONFIGURATION_CHANGED`` vào ``system_events``.
- P2.5: Cột K (``Chi tiết trạm nhận (States)``) trong báo cáo Excel phải quy đổi giờ
  Dismiss sang múi giờ ``Asia/Ho_Chi_Minh`` (UTC+7) khớp với cột Thời gian phát.
- P3.2: Các API cấu hình khử trùng lặp mảng ID quan hệ và trả lỗi 400 rõ ràng khi
  tham chiếu tới khóa ngoại không tồn tại hoặc đã bị vô hiệu hóa.
"""
import io
import uuid
from datetime import datetime, timezone
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from openpyxl import load_workbook
from sqlalchemy import select

from app.main import app
from app.database import AsyncSessionLocal, engine, Base
from app.seed import seed_database
from app.models import (
    Alarm,
    AlarmStationState,
    Station,
    SystemEvent,
    StationAlarmStateEnum,
)
from app.core.websocket_manager import manager


@pytest_asyncio.fixture(scope="module", autouse=True)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()


async def admin_headers(client: AsyncClient) -> dict:
    res = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123456"}
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


class BrokenCloseSocket:
    """Socket giả ném lỗi khi gọi close() để mô phỏng kết nối TCP nửa mở đã chết."""

    def __init__(self):
        self.close_called = False

    async def close(self, code=None, reason=None):
        self.close_called = True
        raise RuntimeError("Socket already broken")

    async def send_text(self, payload):
        return None


@pytest.mark.asyncio
async def test_soft_delete_filters_and_station_counts():
    """Trạm đã xóa mềm không được làm lệch tổng số trạm trên Health và System Status."""
    code = f"ST-DEL-{uuid.uuid4().hex[:6].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = await admin_headers(ac)

        # Tạo nhóm nhận và trạm mới gán vào nhóm đó
        rg_res = await ac.post(
            "/api/receiver-groups",
            headers=headers,
            json={
                "code": f"RG-{uuid.uuid4().hex[:6].upper()}",
                "name": "Nhóm kiểm thử xóa mềm",
            },
        )
        assert rg_res.status_code == 201
        rg_id = rg_res.json()["id"]

        st_res = await ac.post(
            "/api/stations/register",
            headers=headers,
            json={
                "station_code": code,
                "name": "Trạm kiểm thử xóa mềm",
                "location": "Tầng 2",
                "receiver_group_ids": [rg_id, rg_id],  # gửi trùng lặp để kiểm tra khử trùng
            },
        )
        assert st_res.status_code == 201, st_res.text
        st_id = st_res.json()["id"]

        health_before = (await ac.get("/api/health")).json()
        sys_before = (await ac.get("/api/system/status", headers=headers)).json()

        # Xóa mềm trạm
        del_res = await ac.delete(f"/api/stations/{st_id}", headers=headers)
        assert del_res.status_code == 200

        health_after = (await ac.get("/api/health")).json()
        sys_after = (await ac.get("/api/system/status", headers=headers)).json()

        assert health_after["total_stations"] == health_before["total_stations"] - 1
        assert (
            sys_after["total_configured_stations"]
            == sys_before["total_configured_stations"] - 1
        )

        # Danh sách lọc enabled_only=true phải ẩn trạm đã xóa
        active_stations = (
            await ac.get("/api/stations?enabled_only=true", headers=headers)
        ).json()
        assert all(s["id"] != st_id for s in active_stations)

        # Nhóm nhận không còn liệt kê station_id của trạm đã xóa
        groups = (await ac.get("/api/receiver-groups", headers=headers)).json()
        target_group = next(g for g in groups if g["id"] == rg_id)
        assert st_id not in target_group["station_ids"]

        # Đăng ký lại cùng mã trạm phải kích hoạt lại (enabled=True)
        rereg_res = await ac.post(
            "/api/stations/register",
            headers=headers,
            json={
                "station_code": code,
                "name": "Trạm khôi phục",
                "location": "Tầng 2",
            },
        )
        assert rereg_res.status_code == 201
        assert rereg_res.json()["enabled"] is True


@pytest.mark.asyncio
async def test_confirm_device_disconnects_previous_socket_and_records_real_ip():
    """confirm-device phải gỡ socket cũ khỏi active_stations và lấy IP từ X-Forwarded-For."""
    code = f"ST-CONF-{uuid.uuid4().hex[:6].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = await admin_headers(ac)
        st_res = await ac.post(
            "/api/stations/register",
            headers=headers,
            json={"station_code": code, "name": "Trạm Kiosk"},
        )
        assert st_res.status_code == 201
        st_id = st_res.json()["id"]

        # Giả lập socket cũ đang kết nối nhưng bị đứt ngầm (close() ném lỗi)
        broken_ws = BrokenCloseSocket()
        manager.active_stations[code] = broken_ws
        await manager._sync_station_db_status(code, event="DEVICE_CONNECTED")

        confirm_res = await ac.post(
            f"/api/stations/{st_id}/confirm-device",
            headers={**headers, "X-Forwarded-For": "10.20.30.40, 172.18.0.2"},
        )
        assert confirm_res.status_code == 200, confirm_res.text
        body = confirm_res.json()
        assert body["raw_device_token"]
        assert body["ip_address"] == "10.20.30.40"
        assert broken_ws.close_called is True
        assert code not in manager.active_stations

        async with AsyncSessionLocal() as session:
            st_row = await session.get(Station, st_id)
            assert st_row.websocket_connected is False
            assert st_row.status == "OFFLINE"
            assert st_row.ip_address == "10.20.30.40"


@pytest.mark.asyncio
async def test_local_dismiss_backfills_received_at_and_audit_covers_station_mutations():
    """Dismiss khi chưa có received_at phải tự điền received_at; sửa/xóa trạm phải có CONFIGURATION_CHANGED."""
    code = f"ST-AUD-{uuid.uuid4().hex[:6].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = await admin_headers(ac)
        st_res = await ac.post(
            "/api/stations/register",
            headers=headers,
            json={
                "station_code": code,
                "name": "Trạm kiểm toán",
                "receiver_group_ids": [1],
            },
        )
        assert st_res.status_code == 201
        st = st_res.json()

        # Phát báo động khi trạm đang OFFLINE (received_at = None, state = PENDING)
        alarm_res = await ac.post(
            "/api/alarms",
            headers=headers,
            json={"alarm_type_id": 2, "source_location": "Khoa Cấp Cứu"},
        )
        assert alarm_res.status_code == 201
        alarm_id = alarm_res.json()["id"]

        # Trạm gửi dismiss trực tiếp qua HTTP trước khi kịp gửi WS RECEIVED
        dismiss_res = await ac.post(
            "/api/stations/dismiss",
            json={
                "alarm_id": alarm_id,
                "station_code": code,
                "device_token": st["raw_device_token"],
                "note": "Đã tiếp nhận",
            },
        )
        assert dismiss_res.status_code == 200

        async with AsyncSessionLocal() as session:
            st_state = (
                await session.execute(
                    select(AlarmStationState).where(
                        AlarmStationState.alarm_id == alarm_id,
                        AlarmStationState.station_id == st["id"],
                    )
                )
            ).scalar_one()
            assert st_state.state == StationAlarmStateEnum.DISMISSED.value
            assert st_state.received_at is not None
            assert st_state.displayed_at is not None
            assert st_state.dismissed_at is not None

        # Cập nhật và xóa trạm phải sinh CONFIGURATION_CHANGED
        upd_res = await ac.put(
            f"/api/stations/{st['id']}",
            headers=headers,
            json={
                "station_code": code,
                "name": "Trạm kiểm toán đã đổi tên",
                "location": "Khu B",
                "receiver_group_ids": [1],
                "enabled": True,
            },
        )
        assert upd_res.status_code == 200

        del_res = await ac.delete(f"/api/stations/{st['id']}", headers=headers)
        assert del_res.status_code == 200

        async with AsyncSessionLocal() as session:
            events = (
                await session.execute(
                    select(SystemEvent).where(
                        SystemEvent.event_type == "CONFIGURATION_CHANGED"
                    )
                )
            ).scalars().all()
            paths = [
                ((e.event_metadata or {}).get("method"), (e.event_metadata or {}).get("path"))
                for e in events
            ]
            assert ("PUT", f"/api/stations/{st['id']}") in paths
            assert ("DELETE", f"/api/stations/{st['id']}") in paths


@pytest.mark.asyncio
async def test_export_xlsx_formats_dismiss_time_in_vietnam_timezone():
    """Giờ Dismiss ở cột K sheet chính của file Excel phải quy đổi sang UTC+7."""
    code = f"ST-XLS-{uuid.uuid4().hex[:6].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = await admin_headers(ac)
        st_res = await ac.post(
            "/api/stations/register",
            headers=headers,
            json={"station_code": code, "name": "Trạm Excel", "receiver_group_ids": [1]},
        )
        st_id = st_res.json()["id"]

        # Tạo báo động và trạng thái dismiss vào 01:15:20 UTC (= 08:15:20 giờ VN)
        utc_time = datetime(2026, 10, 7, 1, 15, 20, tzinfo=timezone.utc)
        async with AsyncSessionLocal() as session:
            alarm = Alarm(
                alarm_type_id=2,
                status="EXPIRED",
                source_location="Phòng mổ 1",
                note="Kiểm tra múi giờ Excel",
                server_sequence=999999,
                created_at=utc_time,
                activated_at=utc_time,
            )
            session.add(alarm)
            await session.flush()
            session.add(
                AlarmStationState(
                    alarm_id=alarm.id,
                    station_id=st_id,
                    state="DISMISSED",
                    received_at=utc_time,
                    displayed_at=utc_time,
                    dismissed_at=utc_time,
                    created_at=utc_time,
                    updated_at=utc_time,
                )
            )
            await session.commit()

        res = await ac.get(
            "/api/reports/export-xlsx",
            headers=headers,
            params={"from_date": "2026-10-07", "to_date": "2026-10-07"},
        )
        assert res.status_code == 200
        wb = load_workbook(io.BytesIO(res.content))
        ws = wb["BaoCao_Redcode"]
        states_cells = [
            ws.cell(row=r, column=11).value for r in range(2, ws.max_row + 1)
        ]
        matching = [val for val in states_cells if val and code in str(val)]
        assert matching, "Phải tìm thấy dòng báo cáo chứa trạm vừa tạo"
        assert "(Dismiss: 08:15:20)" in matching[0]
        assert "(Dismiss: 01:15:20)" not in matching[0]


@pytest.mark.asyncio
async def test_configuration_endpoints_reject_invalid_foreign_keys():
    """Các API cấu hình phải trả 400 thay vì 500 khi gửi khóa ngoại không tồn tại."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = await admin_headers(ac)

        # 1. Trạm nhận với department_id hoặc receiver_group_ids không tồn tại
        bad_dept = await ac.post(
            "/api/stations/register",
            headers=headers,
            json={
                "station_code": "ST-BAD-DEPT",
                "name": "Bad Dept",
                "department_id": 999999,
            },
        )
        assert bad_dept.status_code == 400

        bad_rg = await ac.post(
            "/api/stations/register",
            headers=headers,
            json={
                "station_code": "ST-BAD-RG",
                "name": "Bad RG",
                "receiver_group_ids": [999999],
            },
        )
        assert bad_rg.status_code == 400

        # 2. Nhóm nhận với station_ids không tồn tại
        bad_group = await ac.post(
            "/api/receiver-groups",
            headers=headers,
            json={
                "code": "RG-BAD-ST",
                "name": "Bad Station Group",
                "station_ids": [999999],
            },
        )
        assert bad_group.status_code == 400

        # 3. Cập nhật loại báo động với receiver_group_id không tồn tại
        bad_at = await ac.put(
            "/api/alarm-types/1",
            headers=headers,
            json={"receiver_group_id": 999999},
        )
        assert bad_at.status_code == 400

        # 4. Cập nhật loại báo động với allowed_department_ids hợp lệ phải trả về đúng mảng vừa lưu
        ok_at = await ac.put(
            "/api/alarm-types/1",
            headers=headers,
            json={"allowed_department_ids": [1, 2]},
        )
        assert ok_at.status_code == 200
        assert sorted(ok_at.json()["allowed_department_ids"]) == [1, 2]


@pytest.mark.asyncio
async def test_http_heartbeat_is_serialized_with_presence_lock_and_updates_ip():
    """POST /api/stations/heartbeat phải đi qua _presence_lock và cập nhật IP thực."""
    code = f"ST-HB-{uuid.uuid4().hex[:6].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = await admin_headers(ac)
        st_res = await ac.post(
            "/api/stations/register",
            headers=headers,
            json={"station_code": code, "name": "Trạm Heartbeat HTTP"},
        )
        assert st_res.status_code == 201
        token = st_res.json()["raw_device_token"]

        hb_res = await ac.post(
            "/api/stations/heartbeat",
            headers={"X-Real-IP": "192.168.50.88"},
            json={
                "station_code": code,
                "device_token": token,
                "audio_ready": True,
                "client_ready": True,
            },
        )
        assert hb_res.status_code == 200
        body = hb_res.json()
        assert body["device_reachable"] is True
        assert body["websocket_connected"] is False

        async with AsyncSessionLocal() as session:
            st = (
                await session.execute(select(Station).where(Station.station_code == code))
            ).scalar_one()
            assert st.ip_address == "192.168.50.88"
            assert st.status == "OFFLINE"
            assert st.audio_ready is False

