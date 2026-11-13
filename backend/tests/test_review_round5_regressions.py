"""Regression tests cho đợt rà soát thứ năm (P1-01, P1-02, P2-03, P2-04).

- P1-01: ``POST /api/stations/dismiss`` phải kiểm tra vòng đời toàn cục của
  báo động (chỉ chấp nhận khi còn ``ACTIVE`` và chưa hết hạn) trong khi giữ
  nguyên tính độc lập giữa các trạm.
- P1-02: Cấu hình n8n thống nhất qua biến môi trường (``.env``), loại bỏ model
  legacy ``IntegrationSettings`` khỏi runtime ORM và kiểm tra ràng buộc cấu hình.
- P2-03: ``GET /api/reports/summary`` dùng SQL aggregation (không tải cả bảng
  vào RAM) và trả về tổng thời gian offline + thời gian trình chiếu/ACK trung bình
  khi đủ dữ liệu (trả ``None`` khi thiếu dữ liệu).
- P2-04: Middleware ``configuration_audit`` ghi nhận ``before`` / ``after`` có
  chọn lọc cho thay đổi cấu hình và tuyệt đối không lưu password/token/hash/secret.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from pydantic import ValidationError
from sqlalchemy import select

import app.models as app_models
from app.config import Settings
from app.database import AsyncSessionLocal, Base, engine
from app.main import app
from app.models import (
    Alarm,
    AlarmEvent,
    AlarmStationState,
    AlarmStatus,
    Department,
    Station,
    StationAlarmStateEnum,
    SystemEvent,
)
from app.seed import seed_database


@pytest_asyncio.fixture(scope="module", autouse=True)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()


async def _admin_headers(client: AsyncClient) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123456"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _register_station(
    client: AsyncClient,
    headers: dict,
    code: str,
    group_ids=(1,),
) -> dict:
    res = await client.post(
        "/api/stations/register",
        headers=headers,
        json={
            "station_code": code,
            "name": f"Trạm {code}",
            "location": "Khu test",
            "receiver_group_ids": list(group_ids),
            "enabled": True,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


# --- P1-01: Dismiss kiểm tra vòng đời toàn cục -------------------------------

@pytest.mark.asyncio
async def test_dismiss_rejects_cancelled_and_expired_alarms_while_preserving_station_independence():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = await _admin_headers(ac)
        suffix = uuid.uuid4().hex[:6].upper()
        st1 = await _register_station(ac, headers, f"ST-LIFE1-{suffix}", group_ids=[1])
        st2 = await _register_station(ac, headers, f"ST-LIFE2-{suffix}", group_ids=[1])

        # 1. Alarm đã CANCELLED -> từ chối 409, không chuyển DISMISSED, không ghi AlarmEvent DISMISSED
        alarm_cancel_res = await ac.post(
            "/api/alarms",
            headers=headers,
            json={"alarm_type_id": 2, "source_location": "P101", "note": "Cancel test"},
        )
        assert alarm_cancel_res.status_code == 201, alarm_cancel_res.text
        alarm_cancel_id = alarm_cancel_res.json()["id"]

        cancel_res = await ac.post(f"/api/alarms/{alarm_cancel_id}/cancel", headers=headers)
        assert cancel_res.status_code == 200, cancel_res.text

        dismiss_cancelled = await ac.post(
            "/api/stations/dismiss",
            json={
                "alarm_id": alarm_cancel_id,
                "station_code": st1["station_code"],
                "device_token": st1["raw_device_token"],
                "note": "Late dismiss",
            },
        )
        assert dismiss_cancelled.status_code == 409, dismiss_cancelled.text

        # 2. Alarm đã hết hạn (expires_at <= now) -> tự chuyển EXPIRED và trả 409
        alarm_exp_res = await ac.post(
            "/api/alarms",
            headers=headers,
            json={"alarm_type_id": 2, "source_location": "P102", "note": "Expire test"},
        )
        assert alarm_exp_res.status_code == 201, alarm_exp_res.text
        alarm_exp_id = alarm_exp_res.json()["id"]

        async with AsyncSessionLocal() as session:
            alarm_row = await session.get(Alarm, alarm_exp_id)
            alarm_row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
            await session.commit()

        dismiss_expired = await ac.post(
            "/api/stations/dismiss",
            json={
                "alarm_id": alarm_exp_id,
                "station_code": st1["station_code"],
                "device_token": st1["raw_device_token"],
            },
        )
        assert dismiss_expired.status_code == 409, dismiss_expired.text

        async with AsyncSessionLocal() as session:
            refreshed_exp = await session.get(Alarm, alarm_exp_id)
            assert refreshed_exp.status == AlarmStatus.EXPIRED.value
            for check_alarm_id in (alarm_cancel_id, alarm_exp_id):
                st_state = (await session.execute(
                    select(AlarmStationState).where(
                        AlarmStationState.alarm_id == check_alarm_id,
                        AlarmStationState.station_id == st1["id"],
                    )
                )).scalar_one()
                assert st_state.state != StationAlarmStateEnum.DISMISSED.value
                dismiss_ev = (await session.execute(
                    select(AlarmEvent).where(
                        AlarmEvent.alarm_id == check_alarm_id,
                        AlarmEvent.station_id == st1["id"],
                        AlarmEvent.event_type == "DISMISSED",
                    )
                )).scalars().all()
                assert dismiss_ev == []

        # 3. Alarm ACTIVE -> trạm 1 dismiss thành công, trạm 2 và alarm toàn cục giữ nguyên độc lập
        alarm_active_res = await ac.post(
            "/api/alarms",
            headers=headers,
            json={"alarm_type_id": 2, "source_location": "P103", "note": "Active test"},
        )
        assert alarm_active_res.status_code == 201, alarm_active_res.text
        alarm_active_id = alarm_active_res.json()["id"]

        ok = await ac.post(
            "/api/stations/dismiss",
            json={
                "alarm_id": alarm_active_id,
                "station_code": st1["station_code"],
                "device_token": st1["raw_device_token"],
            },
        )
        assert ok.status_code == 200, ok.text

        async with AsyncSessionLocal() as session:
            active_alarm = await session.get(Alarm, alarm_active_id)
            assert active_alarm.status == AlarmStatus.ACTIVE.value
            s1_state = (await session.execute(
                select(AlarmStationState).where(
                    AlarmStationState.alarm_id == alarm_active_id,
                    AlarmStationState.station_id == st1["id"],
                )
            )).scalar_one()
            s2_state = (await session.execute(
                select(AlarmStationState).where(
                    AlarmStationState.alarm_id == alarm_active_id,
                    AlarmStationState.station_id == st2["id"],
                )
            )).scalar_one()
            assert s1_state.state == StationAlarmStateEnum.DISMISSED.value
            assert s2_state.state == StationAlarmStateEnum.PENDING.value


# --- P1-02: Cấu hình n8n qua .env & bỏ IntegrationSettings legacy -------------

@pytest.mark.asyncio
async def test_n8n_env_only_config_validation_and_legacy_model_removed():
    assert not hasattr(app_models, "IntegrationSettings")
    assert "integration_settings" not in Base.metadata.tables

    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="development", N8N_ENABLED=True, N8N_WEBHOOK_URL="ftp://invalid")
    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="development", N8N_TIMEOUT_SECONDS=0)
    with pytest.raises(ValidationError):
        Settings(ENVIRONMENT="development", N8N_MAX_RETRIES=99)

    valid = Settings(
        ENVIRONMENT="development",
        N8N_ENABLED=True,
        N8N_WEBHOOK_URL="http://n8n:5678/webhook/redcode",
        N8N_TIMEOUT_SECONDS=5,
        N8N_MAX_RETRIES=4,
    )
    assert valid.N8N_ENABLED is True

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = await _admin_headers(ac)
        res = await ac.get("/api/system/status", headers=headers)
        assert res.status_code == 200, res.text
        n8n_info = res.json().get("n8n_integration")
        assert n8n_info is not None
        assert n8n_info["config_source"] == "env"


# --- P2-03: Reports SQL aggregation, offline duration & avg presentation/ACK -

@pytest.mark.asyncio
async def test_reports_summary_sql_aggregation_offline_duration_and_avg_times():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = await _admin_headers(ac)
        suffix = uuid.uuid4().hex[:6].upper()
        st = await _register_station(ac, headers, f"ST-RPT-{suffix}", group_ids=[1])

        # Khoảng ngày cô lập 2031-05-10 (Asia/Ho_Chi_Minh -> 2031-05-09 17:00 UTC .. 2031-05-10 17:00 UTC)
        t_alarm = datetime(2031, 5, 10, 2, 0, 0, tzinfo=timezone.utc)
        t_off1 = datetime(2031, 5, 10, 3, 0, 0, tzinfo=timezone.utc)
        t_on1 = datetime(2031, 5, 10, 3, 1, 30, tzinfo=timezone.utc)  # 90s offline

        # Khoảng ngày thiếu dữ liệu 2031-06-10 (chỉ có 1 DEVICE_DISCONNECTED chưa kết nối lại & không có ACK/Display)
        t_alarm_empty = datetime(2031, 6, 10, 2, 0, 0, tzinfo=timezone.utc)
        t_off_open = datetime(2031, 6, 10, 4, 0, 0, tzinfo=timezone.utc)

        async with AsyncSessionLocal() as session:
            dept = (await session.execute(select(Department))).scalars().first()
            a1 = Alarm(
                alarm_type_id=2,
                source_department_id=dept.id,
                source_location="Phòng Test RPT",
                note="đủ dữ liệu",
                status=AlarmStatus.EXPIRED.value,
                server_sequence=991001,
                created_at=t_alarm,
                activated_at=t_alarm,
            )
            a2 = Alarm(
                alarm_type_id=2,
                source_department_id=None,
                source_location="Phòng thiếu",
                note="thiếu dữ liệu",
                status=AlarmStatus.EXPIRED.value,
                server_sequence=991002,
                created_at=t_alarm_empty,
                activated_at=t_alarm_empty,
            )
            session.add_all([a1, a2])
            await session.flush()

            session.add(AlarmStationState(
                alarm_id=a1.id,
                station_id=st["id"],
                state=StationAlarmStateEnum.DISMISSED.value,
                received_at=t_alarm + timedelta(seconds=1),
                displayed_at=t_alarm + timedelta(seconds=2),
                dismissed_at=t_alarm + timedelta(seconds=12),
                created_at=t_alarm,
                updated_at=t_alarm + timedelta(seconds=12),
            ))
            session.add(AlarmStationState(
                alarm_id=a2.id,
                station_id=st["id"],
                state=StationAlarmStateEnum.PENDING.value,
                created_at=t_alarm_empty,
                updated_at=t_alarm_empty,
            ))
            session.add_all([
                SystemEvent(
                    station_id=st["id"],
                    event_type="DEVICE_DISCONNECTED",
                    severity="WARNING",
                    message="disconnect",
                    created_at=t_off1,
                ),
                SystemEvent(
                    station_id=st["id"],
                    event_type="DEVICE_CONNECTED",
                    severity="INFO",
                    message="reconnect",
                    created_at=t_on1,
                ),
                SystemEvent(
                    station_id=st["id"],
                    event_type="DEVICE_DISCONNECTED",
                    severity="WARNING",
                    message="open disconnect",
                    created_at=t_off_open,
                ),
            ])
            await session.commit()

        res_full = await ac.get(
            "/api/reports/summary",
            headers=headers,
            params={"from_date": "2031-05-10", "to_date": "2031-05-10"},
        )
        assert res_full.status_code == 200, res_full.text
        full = res_full.json()
        assert full["total_alarms"] == 1
        assert full["by_day"] == {"2031-05-10": 1}
        assert full["by_month"] == {"2031-05": 1}
        assert full["avg_received_seconds"] == pytest.approx(1.0, abs=0.1)
        assert full["avg_presentation_seconds"] == pytest.approx(2.0, abs=0.1)
        assert full["avg_ack_seconds"] == pytest.approx(12.0, abs=0.1)
        assert full["device_offline_events_count"] == 1
        assert full["total_offline_duration_seconds"] == pytest.approx(90.0, abs=0.2)
        station_entry = next(item for item in full["by_station_offline"] if item["station_id"] == st["id"])
        assert station_entry["offline_count"] == 1
        assert station_entry["resolved_intervals_count"] == 1
        assert station_entry["offline_duration_seconds"] == pytest.approx(90.0, abs=0.2)

        res_sparse = await ac.get(
            "/api/reports/summary",
            headers=headers,
            params={"from_date": "2031-06-10", "to_date": "2031-06-10"},
        )
        assert res_sparse.status_code == 200, res_sparse.text
        sparse = res_sparse.json()
        assert sparse["total_alarms"] == 1
        assert sparse["by_department"].get("Không xác định") == 1
        assert sparse["avg_received_seconds"] is None
        assert sparse["avg_presentation_seconds"] is None
        assert sparse["avg_ack_seconds"] is None
        assert sparse["device_offline_events_count"] == 1
        assert sparse["total_offline_duration_seconds"] is None


# --- P2-04: Configuration audit before/after & không rò rỉ secret ------------

@pytest.mark.asyncio
async def test_configuration_audit_captures_before_after_without_secrets():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = await _admin_headers(ac)
        suffix = uuid.uuid4().hex[:6]
        secret_pwd = f"SuperSecretPwd_{suffix}!"
        new_pwd = f"UpdatedSecretPwd_{suffix}!"
        raw_station_secret = f"RawStationSecret_{suffix}!"

        # 1. Tạo user -> before=None, after có username/display_name, không có password/hash
        u_create = await ac.post(
            "/api/users",
            headers=headers,
            json={
                "username": f"audit_u_{suffix}",
                "password": secret_pwd,
                "display_name": "Audit User Before",
                "department_id": 1,
                "role": "OPERATOR",
                "enabled": True,
            },
        )
        assert u_create.status_code == 201, u_create.text
        user_id = u_create.json()["id"]

        # 2. Cập nhật user kèm đổi mật khẩu
        u_update = await ac.put(
            f"/api/users/{user_id}",
            headers=headers,
            json={
                "display_name": "Audit User After",
                "password": new_pwd,
            },
        )
        assert u_update.status_code == 200, u_update.text

        # 3. Tạo trạm -> cập nhật tên + xoay device_token -> xóa mềm trạm
        st_code = f"ST-AUD-{suffix.upper()}"
        st_create = await ac.post(
            "/api/stations/register",
            headers=headers,
            json={
                "station_code": st_code,
                "name": "Trạm Audit Ban Đầu",
                "location": "Tầng 1",
                "receiver_group_ids": [1],
                "enabled": True,
            },
        )
        assert st_create.status_code == 201, st_create.text
        station_id = st_create.json()["id"]

        st_update = await ac.put(
            f"/api/stations/{station_id}",
            headers=headers,
            json={
                "station_code": st_code,
                "name": "Trạm Audit Đã Sửa",
                "location": "Tầng 2",
                "device_token": raw_station_secret,
                "receiver_group_ids": [1],
                "enabled": True,
            },
        )
        assert st_update.status_code == 200, st_update.text

        st_delete = await ac.delete(f"/api/stations/{station_id}", headers=headers)
        assert st_delete.status_code == 200, st_delete.text

        async with AsyncSessionLocal() as session:
            events = (await session.execute(
                select(SystemEvent)
                .where(SystemEvent.event_type == "CONFIGURATION_CHANGED")
                .order_by(SystemEvent.id.asc())
            )).scalars().all()

        def find_event(method: str, path: str):
            for ev in reversed(events):
                md = ev.event_metadata or {}
                if md.get("method") == method and md.get("path") == path:
                    return md
            return None

        ev_u_create = find_event("POST", "/api/users")
        assert ev_u_create is not None
        assert ev_u_create["before"] is None
        assert ev_u_create["after"]["username"] == f"audit_u_{suffix}"
        assert ev_u_create["after"]["display_name"] == "Audit User Before"

        ev_u_update = find_event("PUT", f"/api/users/{user_id}")
        assert ev_u_update is not None
        assert ev_u_update["before"]["display_name"] == "Audit User Before"
        assert ev_u_update["after"]["display_name"] == "Audit User After"
        assert ev_u_update["after"]["password_changed"] is True

        ev_st_update = find_event("PUT", f"/api/stations/{station_id}")
        assert ev_st_update is not None
        assert ev_st_update["before"]["name"] == "Trạm Audit Ban Đầu"
        assert ev_st_update["after"]["name"] == "Trạm Audit Đã Sửa"
        assert ev_st_update["after"]["credential_rotated"] is True

        ev_st_delete = find_event("DELETE", f"/api/stations/{station_id}")
        assert ev_st_delete is not None
        assert ev_st_delete["before"]["enabled"] is True
        assert ev_st_delete["after"]["enabled"] is False

        # Đảm bảo tuyệt đối không rò rỉ password, device_token hay hash trong audit metadata
        for md in (ev_u_create, ev_u_update, ev_st_update, ev_st_delete):
            serialized = json.dumps(md, ensure_ascii=False)
            assert secret_pwd not in serialized
            assert new_pwd not in serialized
            assert raw_station_secret not in serialized
            for side in (md.get("before"), md.get("after")):
                if isinstance(side, dict):
                    assert "password" not in side
                    assert "password_hash" not in side
                    assert "device_token" not in side
                    assert "device_token_hash" not in side

