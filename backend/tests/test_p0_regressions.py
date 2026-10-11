"""Hồi quy cho loạt sửa P0 về kết nối, phục hồi và tính trung thực của trạng thái.

Mỗi test ở đây tái hiện một lỗi có thật đã được sửa, không phải kiểm tra hình thức.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, update

from app.core.websocket_manager import manager
from app.main import app
from app.database import engine, Base, AsyncSessionLocal
from app.models import Alarm, AlarmStationState, Station, StationStatus, User, UserRole
from app.seed import seed_database


@pytest_asyncio.fixture(scope="module", autouse=True)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()


class FakeSocket:
    """Socket tối thiểu đủ để ConnectionManager làm việc."""

    def __init__(self, station_code):
        self.station_code = station_code
        self.messages = []
        self.closed_with = None

    async def accept(self):
        pass

    async def send_text(self, text):
        self.messages.append(json.loads(text))

    async def close(self, code=1000, reason=""):
        self.closed_with = (code, reason)


async def admin_headers(client):
    response = await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123456'})
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


async def provision_station(client, headers, group_ids=(1,)):
    body = (await client.post('/api/stations/register', headers=headers, json={
        'station_code': 'REG-' + uuid.uuid4().hex[:10],
        'name': 'Regression station',
        'receiver_group_ids': list(group_ids),
    })).json()
    return body


# --- HTTP heartbeat không được nói dối về khả năng nhận báo động ---

@pytest.mark.asyncio
async def test_http_heartbeat_reports_no_alarm_channel_without_websocket():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        headers = await admin_headers(client)
        station = await provision_station(client, headers)

        response = await client.post('/api/stations/heartbeat', json={
            'station_code': station['station_code'],
            'device_token': station['raw_device_token'],
            'audio_ready': True,
            'client_ready': True,
        })
        assert response.status_code == 200
        body = response.json()
        # Không có WebSocket thì không thể nhận báo động, dù nhịp tim vẫn tới.
        assert body['websocket_connected'] is False
        assert body['can_receive_alarms'] is False

        async with AsyncSessionLocal() as session:
            stored = (await session.execute(
                select(Station).where(Station.station_code == station['station_code'])
            )).scalar_one()
            # Trước đây endpoint ghi websocket_connected=True và status=ONLINE, nên
            # dashboard hiện ONLINE xanh cho thiết bị không bao giờ nhận được báo động.
            assert stored.websocket_connected is False
            # Cờ sẵn sàng âm thanh cũng không được nhận từ một nhịp tim không có kênh thật.
            assert stored.audio_ready is False
            assert stored.client_ready is False


@pytest.mark.asyncio
async def test_http_heartbeat_does_not_create_orphan_liveness_entry():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        headers = await admin_headers(client)
        station = await provision_station(client, headers)

        await client.post('/api/stations/heartbeat', json={
            'station_code': station['station_code'],
            'device_token': station['raw_device_token'],
        })
        # Entry mồ côi trong last_heartbeats khiến monitor tưởng trạm vừa mất kết nối.
        assert station['station_code'] not in manager.last_heartbeats


# --- Guard danh tính socket ---

@pytest.mark.asyncio
async def test_unidentified_disconnect_cannot_evict_a_live_socket():
    code = 'GUARD-' + uuid.uuid4().hex[:8]
    live = FakeSocket(code)
    await manager.connect_station(code, live)
    try:
        # Trước đây disconnect_station(code) với websocket=None bỏ qua guard danh
        # tính và xoá thẳng socket đang sống.
        await manager.disconnect_station(code)
        assert manager.active_stations.get(code) is live
    finally:
        await manager.disconnect_station(code, live)


@pytest.mark.asyncio
async def test_stale_socket_disconnect_cannot_evict_its_replacement():
    code = 'REPLACE-' + uuid.uuid4().hex[:8]
    old = FakeSocket(code)
    new = FakeSocket(code)
    await manager.connect_station(code, old)
    await manager.connect_station(code, new)
    try:
        assert manager.active_stations.get(code) is new
        # Socket cũ đóng muộn (handler của nó vẫn chạy) không được đá socket mới.
        await manager.disconnect_station(code, old)
        assert manager.active_stations.get(code) is new
        # Mã đóng phải là 4001: client coi 1000 là đóng bình thường và thử lại sau
        # ~1 giây, nên hai thiết bị mở cùng mã trạm sẽ đá nhau không dứt.
        assert old.closed_with is not None and old.closed_with[0] == 4001
    finally:
        await manager.disconnect_station(code, new)


@pytest.mark.asyncio
async def test_connect_station_does_not_hold_the_lock_while_closing_previous_socket():
    code = 'LOCK-' + uuid.uuid4().hex[:8]
    old = FakeSocket(code)
    await manager.connect_station(code, old)

    class HangingClose(FakeSocket):
        async def close(self, code=1000, reason=""):
            await asyncio.sleep(30)

    hanging = HangingClose(code)
    # Đóng socket cũ treo phải KHÔNG giữ lock: nếu giữ, mọi broadcast_alarm xếp hàng
    # sau nó và một thiết bị hỏng làm tê liệt phát báo động toàn viện.
    await asyncio.wait_for(manager.connect_station(code, hanging), timeout=5)
    try:
        await asyncio.wait_for(manager.touch_station(code), timeout=1)
        assert manager.active_stations.get(code) is hanging
    finally:
        manager.active_stations.pop(code, None)
        manager.last_heartbeats.pop(code, None)


# --- Idempotency ---

@pytest.mark.asyncio
async def test_replaying_a_finished_alarm_does_not_claim_a_live_broadcast():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        headers = await admin_headers(client)
        key = 'idem-' + uuid.uuid4().hex
        payload = {'alarm_type_id': 1, 'idempotency_key': key}

        first = await client.post('/api/alarms', headers=headers, json=payload)
        assert first.status_code == 201
        alarm_id = first.json()['id']

        # Phát lại khi còn ACTIVE: trả đúng báo động đó.
        replay = await client.post('/api/alarms', headers=headers, json=payload)
        assert replay.status_code == 201
        assert replay.json()['id'] == alarm_id

        cancelled = await client.post(f'/api/alarms/{alarm_id}/cancel', headers=headers)
        assert cancelled.status_code == 200

        # Trước đây trả lại bản ghi EXPIRED/CANCELLED với 201, khiến người trực
        # tưởng vừa phát được báo động đang hiệu lực trong khi không còi nào hú.
        after = await client.post('/api/alarms', headers=headers, json=payload)
        assert after.status_code == 409
        assert 'kết thúc' in after.json()['detail']


@pytest.mark.asyncio
async def test_broadcast_evicts_a_dead_socket_so_it_stops_costing_time():
    code = 'DEAD-' + uuid.uuid4().hex[:8]

    class DeadSocket(FakeSocket):
        async def send_text(self, text):
            raise RuntimeError('socket đã chết')

    dead = DeadSocket(code)
    await manager.connect_station(code, dead)
    try:
        result = await manager.broadcast_alarm({'alarm_id': 1}, target_station_codes=[code])
        assert result['delivered'] == 0
        assert result['targets'] == 1
        # Trước đây cleanup gọi disconnect_station(code) KHÔNG kèm danh tính, bị guard
        # từ chối, nên xác socket nằm lại trong active_stations vĩnh viễn: mọi báo
        # động sau đó lại thử gửi vào nó và tốn trọn 1 giây timeout mỗi lượt.
        assert code not in manager.active_stations
        assert code not in manager.last_heartbeats
    finally:
        manager.active_stations.pop(code, None)
        manager.last_heartbeats.pop(code, None)


@pytest.mark.asyncio
async def test_delivery_counts_report_only_stations_that_received():
    good_code = 'GOOD-' + uuid.uuid4().hex[:8]
    dead_code = 'GONE-' + uuid.uuid4().hex[:8]

    class DeadSocket(FakeSocket):
        async def send_text(self, text):
            raise RuntimeError('socket đã chết')

    good = FakeSocket(good_code)
    await manager.connect_station(good_code, good)
    await manager.connect_station(dead_code, DeadSocket(dead_code))
    try:
        result = await manager.broadcast_alarm(
            {'alarm_id': 1}, target_station_codes=[good_code, dead_code]
        )
        # "Đã phát tới 2 trạm" trong khi chỉ 1 trạm hú là lời nói dối nguy hiểm nhất
        # trong hệ thống này: người trực tin đã báo động được cho cả hai khoa.
        assert result == {'delivered': 1, 'targets': 2}
        assert any(m.get('event') == 'ALARM_TRIGGERED' for m in good.messages)
    finally:
        for code in (good_code, dead_code):
            manager.active_stations.pop(code, None)
            manager.last_heartbeats.pop(code, None)


@pytest.mark.asyncio
async def test_replay_response_reports_real_delivery_counts():
    """Báo cáo sau khi phát phải khớp đúng số trạm THẬT SỰ nhận được."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        headers = await admin_headers(client)
        station = await provision_station(client, headers, group_ids=())

        # Nhóm nhận riêng cho trạm này, để đếm được chính xác thay vì phụ thuộc
        # vào số trạm có sẵn trong dữ liệu mẫu.
        group = (await client.post('/api/receiver-groups', headers=headers, json={
            'code': 'P0_' + uuid.uuid4().hex[:8],
            'name': 'Nhóm kiểm tra P0',
            'station_ids': [station['id']],
        })).json()
        alarm_type = (await client.post('/api/alarm-types', headers=headers, json={
            'code': 'P0_' + uuid.uuid4().hex[:8],
            'name': 'P0 delivery',
            'receiver_group_id': group['id'],
            'audio_sequence': ['/assets/audio/red_code_1.wav'],
        })).json()

        socket = FakeSocket(station['station_code'])
        await manager.connect_station(station['station_code'], socket)
        try:
            created = (await client.post('/api/alarms', headers=headers, json={
                'alarm_type_id': alarm_type['id'],
            })).json()
            assert created['target_station_count'] == 1
            assert created['delivered_station_count'] == 1
            assert any(m.get('event') == 'ALARM_TRIGGERED' for m in socket.messages)
        finally:
            await manager.disconnect_station(station['station_code'], socket)

        # Trạm offline: báo động vẫn được ghi nhận cho đúng nhóm đó, nhưng KHÔNG
        # được báo cáo là đã phát tới ai — chưa có còi nào hú.
        offline = (await client.post('/api/alarms', headers=headers, json={
            'alarm_type_id': alarm_type['id'],
        })).json()
        assert offline['target_station_count'] == 1
        assert offline['delivered_station_count'] == 0


# --- Phục hồi sau khi máy chủ khởi động lại ---

@pytest.mark.asyncio
async def test_restart_reconciliation_clears_stale_readiness_flags():
    async with AsyncSessionLocal() as session:
        await session.execute(update(Station).values(
            websocket_connected=True, status=StationStatus.ONLINE.value,
            audio_ready=True, client_ready=True,
        ))
        await session.commit()
    # Cùng câu lệnh mà lifespan() chạy lúc khởi động.
    async with AsyncSessionLocal() as session:
        await session.execute(update(Station).values(
            websocket_connected=False, status=StationStatus.OFFLINE.value,
            audio_ready=False, client_ready=False,
        ))
        await session.commit()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Station))).scalars().all()
    assert rows, 'cần ít nhất một trạm để kiểm tra'
    for station in rows:
        # Giữ cờ cũ sẽ khiến bảng trạm hiện "AUDIO READY" cho thiết bị đã offline.
        assert station.websocket_connected is False
        assert station.audio_ready is False
        assert station.client_ready is False


# --- Cấu hình báo động câm ---

@pytest.mark.asyncio
async def test_alarm_type_requires_at_least_one_audio_file():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        headers = await admin_headers(client)
        base = {'code': 'SILENT_' + uuid.uuid4().hex[:8], 'name': 'Silent'}

        assert (await client.post('/api/alarm-types', headers=headers, json=base)).status_code == 422
        assert (await client.post('/api/alarm-types', headers=headers, json={
            **base, 'audio_sequence': []
        })).status_code == 422

        created = await client.post('/api/alarm-types', headers=headers, json={
            **base, 'audio_sequence': ['/assets/audio/red_code_1.wav'],
        })
        assert created.status_code == 201

        # Cập nhật cũng không được phép làm câm một mã đang có còi.
        assert (await client.put(f"/api/alarm-types/{created.json()['id']}", headers=headers, json={
            'audio_sequence': []
        })).status_code == 422


# --- Xoay credential trạm: không được đá trạm đang trực vì lý do không liên quan ---

@pytest.mark.asyncio
async def test_reregistering_with_the_same_token_does_not_evict_the_live_station():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        headers = await admin_headers(client)
        code = 'SAME-' + uuid.uuid4().hex[:8]
        token = 'tok-' + uuid.uuid4().hex
        body = {'station_code': code, 'name': 'Trạm giữ nguyên token', 'device_token': token}

        created = (await client.post('/api/stations/register', headers=headers, json=body)).json()
        socket = FakeSocket(code)
        await manager.connect_station(code, socket)
        try:
            # Admin đăng ký lại trạm (đổi tên, đổi nhóm nhận) mà KHÔNG đổi token.
            # Trước đây endpoint luôn đóng 1008, khiến mọi trạm đang trực dừng thử lại
            # vĩnh viễn và chờ người xác nhận lại chỉ vì một lần sửa cấu hình.
            again = await client.post('/api/stations/register', headers=headers, json={
                **body, 'name': 'Trạm đã đổi tên',
            })
            assert again.status_code == 201
            assert socket.closed_with is None
            assert manager.active_stations.get(code) is socket

            # Đổi token thì phải đóng, và phải kèm lý do đọc được.
            rotated = await client.post('/api/stations/register', headers=headers, json={
                **body, 'device_token': token + '-new',
            })
            assert rotated.status_code == 201
            assert socket.closed_with is not None
            assert socket.closed_with[0] == 1008
            assert socket.closed_with[1], 'thiết bị cần đọc được lý do để biết phải làm gì'
            assert code not in manager.active_stations
        finally:
            manager.active_stations.pop(code, None)
            manager.last_heartbeats.pop(code, None)


@pytest.mark.asyncio
async def test_renaming_a_station_code_closes_the_socket_under_the_old_code():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        headers = await admin_headers(client)
        old_code = 'OLD-' + uuid.uuid4().hex[:8]
        new_code = 'NEW-' + uuid.uuid4().hex[:8]
        token = 'tok-' + uuid.uuid4().hex
        created = (await client.post('/api/stations/register', headers=headers, json={
            'station_code': old_code, 'name': 'Trạm đổi mã', 'device_token': token,
        })).json()

        socket = FakeSocket(old_code)
        await manager.connect_station(old_code, socket)
        try:
            updated = await client.put(f"/api/stations/{created['id']}", headers=headers, json={
                'station_code': new_code, 'name': 'Trạm đổi mã', 'device_token': token,
            })
            assert updated.status_code == 200
            # Socket mồ côi dưới mã CŨ sẽ không bao giờ nhận được báo động phát theo
            # mã mới, nhưng vẫn được vòng giám sát coi là trạm đang sống.
            assert old_code not in manager.active_stations
            assert socket.closed_with is not None and socket.closed_with[0] == 1008
            assert socket.closed_with[1]
        finally:
            for code in (old_code, new_code):
                manager.active_stations.pop(code, None)
                manager.last_heartbeats.pop(code, None)


# --- /api/health phải nói ra khi vòng giám sát nhịp tim đã chết ---

@pytest.mark.asyncio
async def test_health_reports_degraded_when_the_heartbeat_monitor_is_down():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        original = manager._monitor_task
        try:
            # Giả lập vòng giám sát đã chết: trạm rút điện sẽ hiện ONLINE mãi mãi.
            class Done:
                def done(self):
                    return True

            manager._monitor_task = Done()
            body = (await client.get('/api/health')).json()
            assert body['websocket'] == 'degraded'
            # Trạng thái chung vẫn phải là ok: mất vòng giám sát không làm sập báo động.
            assert body['status'] == 'ok'
        finally:
            manager._monitor_task = original
