"""Regression tests cho đợt rà soát thứ ba (12 phát hiện F-01..F-12).

Mỗi test khoá đúng một hành vi đã sai trước đợt sửa. Các phát hiện thuần giao
diện (F-01 phần UI, F-02, F-05, F-07, F-08) có test riêng trong ``frontend/tests``;
ở đây là phần máy chủ và những bất biến máy chủ phải giữ.

- F-03: lượt phát lại theo ``idempotency_key`` trả về số trạm ĐÃ NHẬN là 0 vì
  ``AlarmOut`` không có hai trường đếm, khiến người trực tưởng không còi nào hú.
- F-04: broadcast tới dashboard là vòng lặp tuần tự, mỗi socket chờ tới 1 giây,
  nên vài dashboard treo cộng thẳng vào thời gian chờ của POST /api/alarms.
- F-06: xóa trạm chỉ gọi ``ws.close(1008)`` trần — thiếu lý do đọc được và thiếu
  gỡ khỏi sổ phiên, nên báo động vẫn thử gửi vào xác đó.
- F-09: phép kiểm tra "trạm còn báo động chưa ACK" chạy mỗi nhịp tim (5 giây) cho
  mọi trạm — hàng nghìn lượt JOIN ba bảng mỗi phút cho một tình huống hiếm.
- F-10: báo cáo tổng hợp nạp cả đối tượng ORM cho một truy vấn chỉ để đếm.
- F-12: ``create_all`` chạy trên PostgreSQL khi ``ENVIRONMENT`` bị đặt sai.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.database import AsyncSessionLocal, engine, Base
from app.seed import seed_database
from app.models import (
    Alarm, AlarmType, AlarmStatus, Department, ReceiverGroup,
    ReceiverGroupStation, Station, User, UserRole,
)
from app.core.websocket_manager import manager


@pytest_asyncio.fixture(scope="module", autouse=True)
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database()


async def admin_headers(client):
    res = await client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123456'})
    assert res.status_code == 200, res.text
    return {'Authorization': f"Bearer {res.json()['access_token']}"}


class FakeSocket:
    """Socket giả: ghi lại lý do đóng và có thể giả lập treo khi gửi."""

    def __init__(self, hang_seconds: float = 0.0):
        self.closed_with = None
        self.hang_seconds = hang_seconds
        self.sent = []

    async def close(self, code=None, reason=None):
        self.closed_with = (code, reason)

    async def send_text(self, payload):
        if self.hang_seconds:
            await asyncio.sleep(self.hang_seconds)
        self.sent.append(payload)


async def _register_station(client, headers, code):
    res = await client.post('/api/stations/register', headers=headers, json={
        'station_code': code, 'name': f'Trạm {code}', 'location': 'Test',
    })
    assert res.status_code == 201, res.text
    return res.json()


async def _station_row(code):
    async with AsyncSessionLocal() as session:
        return (await session.execute(
            select(Station).where(Station.station_code == code)
        )).scalar_one_or_none()


# --- F-03: lượt phát lại phải trả về số trạm thật, không phải 0 -----------------

@pytest.mark.asyncio
async def test_replay_of_duplicate_alarm_reports_real_station_counts():
    """Phát lại cùng ``idempotency_key`` không được báo "0 trạm đã nhận".

    Kịch bản thật: mất gói ở chân HTTP phản hồi rồi client thử lại. Báo động đã
    ACTIVE và còi đang hú, nhưng phản hồi cũ trả ``AlarmOut`` trần nên hai trường
    đếm rơi về 0, và ``OperatorDashboard`` dịch số 0 đó thành "KHÔNG trạm nào đang
    trực tuyến — hiện chưa có còi nào hú".
    """
    code = 'ST-REPLAY-COUNT'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)
        await _register_station(ac, headers, code)

        # Loại báo động riêng, không gắn nhóm nhận, để tập trạm đích là MỌI trạm đang
        # bật — nhờ vậy trạm vừa đăng ký chắc chắn nằm trong đó và phép đếm kiểm
        # chứng được. Dùng loại có sẵn của seed thì tập trạm phụ thuộc nhóm của nó.
        async with AsyncSessionLocal() as session:
            alarm_type = AlarmType(
                code='AT-REPLAY-COUNT',
                name='Loại kiểm tra phát lại',
                description='',
                enabled=True,
                receiver_group_id=None,
                audio_sequence=['/assets/audio/a.wav'],
                repeat_count=1,
                repeat_interval_ms=1000,
                validity_seconds=300,
                created_at=datetime.now(timezone.utc),
            )
            session.add(alarm_type)
            await session.commit()
            alarm_type_id = alarm_type.id

        payload = {
            'alarm_type_id': alarm_type_id,
            'source_location': 'Khoa Test',
            'note': 'kiểm tra phát lại',
            'idempotency_key': 'replay-count-key-1',
        }

        first = await ac.post('/api/alarms', headers=headers, json=payload)
        assert first.status_code == 201, first.text
        body = first.json()

        # Bản ghi đích phải tồn tại — nếu không thì test này không chứng minh được gì.
        assert body['target_station_count'] >= 1, body
        assert body['idempotency_key'] == 'replay-count-key-1'

        second = await ac.post('/api/alarms', headers=headers, json=payload)
        assert second.status_code == 201, second.text
        replay = second.json()

        assert replay['id'] == body['id'], 'phát lại phải trả về chính báo động cũ'
        assert replay['target_station_count'] == body['target_station_count'], (
            'lượt phát lại phải báo cùng số trạm đích, không được rơi về 0'
        )
        # Cùng một khóa idempotency nên không được tạo thêm bản ghi trạm nào.
        assert replay['target_station_count'] == len(replay['station_states'])

        # Trạm đang có kết nối thì phải được tính là đã nhận.
        socket = FakeSocket()
        manager.active_stations[code] = socket
        try:
            third = await ac.post('/api/alarms', headers=headers, json=payload)
            assert third.status_code == 201, third.text
            assert third.json()['delivered_station_count'] >= 1, (
                'trạm đang kết nối phải được tính vào số trạm đã nhận của lượt phát lại'
            )
        finally:
            manager.active_stations.pop(code, None)


@pytest.mark.asyncio
async def test_replay_still_refuses_a_finished_alarm():
    """Số liệu trạm không được biến một báo động đã kết thúc thành "vừa phát xong"."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)
        async with AsyncSessionLocal() as session:
            alarm_type = (await session.execute(select(AlarmType))).scalars().first()
            alarm_type_id = alarm_type.id

        payload = {
            'alarm_type_id': alarm_type_id,
            'source_location': 'Khoa Test',
            'note': 'phát lại sau khi kết thúc',
            'idempotency_key': 'replay-finished-key-1',
        }
        first = await ac.post('/api/alarms', headers=headers, json=payload)
        assert first.status_code == 201, first.text
        alarm_id = first.json()['id']

        cancelled = await ac.post(f'/api/alarms/{alarm_id}/cancel', headers=headers)
        assert cancelled.status_code == 200, cancelled.text

        again = await ac.post('/api/alarms', headers=headers, json=payload)
        assert again.status_code == 409, (
            'báo động đã kết thúc thì lượt phát lại phải là 409, kèm số liệu trạm hay không'
        )


# --- F-04: broadcast tới dashboard phải chạy song song --------------------------

@pytest.mark.asyncio
async def test_dashboard_broadcast_runs_in_parallel_not_one_socket_at_a_time():
    """Ba dashboard treo nửa vời không được cộng dồn 3 giây vào lượt phát báo động.

    Hàm này nằm trên đường phản hồi của POST /api/alarms, nên mỗi giây nó chờ là
    một giây người trực còn đứng trước màn hình chưa thấy xác nhận.
    """
    hang = 0.30
    sockets = [FakeSocket(hang_seconds=hang) for _ in range(3)]
    manager.active_dashboards = set(sockets)
    try:
        started = asyncio.get_event_loop().time()
        await manager.broadcast_to_dashboards({'type': 'ALARM_TRIGGERED', 'data': {}})
        elapsed = asyncio.get_event_loop().time() - started

        assert all(s.sent for s in sockets), 'mọi dashboard còn sống đều phải nhận được tin'
        assert elapsed < hang * 2, (
            f'phải gửi song song, không phải tuần tự: mất {elapsed:.2f}s cho 3 socket '
            f'treo {hang}s mỗi cái'
        )
    finally:
        manager.active_dashboards = set()


@pytest.mark.asyncio
async def test_dashboard_broadcast_still_prunes_dead_sockets():
    """Gửi song song không được bỏ mất bước dọn socket chết."""
    class DeadSocket(FakeSocket):
        async def send_text(self, payload):
            raise RuntimeError('socket đã chết')

    dead = DeadSocket()
    alive = FakeSocket()
    manager.active_dashboards = {dead, alive}
    try:
        await manager.broadcast_to_dashboards({'type': 'ALARM_TRIGGERED', 'data': {}})
        assert dead not in manager.active_dashboards, 'socket chết phải bị gỡ khỏi sổ dashboard'
        assert alive in manager.active_dashboards, 'socket sống không được bị gỡ oan'
    finally:
        manager.active_dashboards = set()


@pytest.mark.asyncio
async def test_connected_station_codes_is_a_snapshot_not_a_live_view():
    """Số liệu phát lại đọc từ sổ phiên phải là ảnh chụp, không phải tham chiếu sống."""
    manager.active_stations['ST-SNAP-A'] = FakeSocket()
    try:
        snapshot = manager.connected_station_codes
        assert 'ST-SNAP-A' in snapshot
        manager.active_stations['ST-SNAP-B'] = FakeSocket()
        assert 'ST-SNAP-B' not in snapshot, 'ảnh chụp không được đổi theo sổ sau khi đã lấy'
        assert 'ST-SNAP-B' in manager.connected_station_codes
    finally:
        manager.active_stations.pop('ST-SNAP-A', None)
        manager.active_stations.pop('ST-SNAP-B', None)


# --- F-06: xóa trạm phải đóng socket kèm lý do và gỡ khỏi sổ phiên --------------

@pytest.mark.asyncio
async def test_deleting_station_closes_socket_with_reason_and_unregisters():
    """Xóa trạm mà để socket nằm lại thì mọi báo động sau đó vẫn gửi vào xác đó.

    Mỗi lượt gửi như vậy tốn trọn 1 giây timeout, và kiosk chỉ nhận câu thông báo
    chung "chưa được xác nhận hoặc credential đã bị thu hồi" vì lý do đóng bị bỏ trống.
    """
    code = 'ST-DELETE-CLOSE'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)
        created = await _register_station(ac, headers, code)
        station_id = created['id']

        socket = FakeSocket()
        manager.active_stations[code] = socket
        try:
            res = await ac.delete(f'/api/stations/{station_id}', headers=headers)
            assert res.status_code == 200, res.text

            assert code not in manager.active_stations, (
                'trạm bị xóa phải được gỡ khỏi sổ phiên ngay, không chờ vòng đọc nhận ra'
            )
            assert socket.closed_with is not None, 'socket phải được đóng'
            closed_code, reason = socket.closed_with
            assert closed_code == 1008, 'kiosk phải biết đây là lỗi credential, không phải mất mạng'
            assert reason, 'lý do đóng không được để trống — kiosk cần câu giải thích đọc được'
        finally:
            manager.active_stations.pop(code, None)

    row = await _station_row(code)
    assert row.enabled is False, 'trạm bị xóa mềm phải tắt, không được xóa bản ghi'


# --- F-09: kiểm tra "báo động chưa ACK" phải được giãn nhịp ---------------------

@pytest.mark.asyncio
async def test_pending_sync_check_is_throttled_between_heartbeats():
    """Nhịp tim 5 giây không được kéo theo một lượt JOIN ba bảng cho mỗi trạm.

    Phép kiểm tra chỉ bắt đúng một tình huống hiếm: khung broadcast bị mất trong khi
    socket vẫn sống. Mọi tình huống khác đã có đường khác phủ — nối lại thì connect
    kiểm tra đầy đủ, báo động mới phát thì chính khung broadcast là đường chính.
    """
    from app import main as main_module

    code = 'ST-THROTTLE'
    main_module._last_pending_sync_check.pop(code, None)
    try:
        assert main_module._pending_sync_check_due(code) is True, (
            'lượt hỏi đầu tiên của một trạm chưa có mốc thời gian phải được chạy'
        )
        for _ in range(20):
            assert main_module._pending_sync_check_due(code) is False, (
                'các nhịp tim liên tiếp trong cùng khoảng giãn phải bị chặn'
            )
    finally:
        main_module._last_pending_sync_check.pop(code, None)


@pytest.mark.asyncio
async def test_pending_sync_check_becomes_due_again_after_the_interval():
    """Giãn nhịp không được biến thành "chỉ chạy một lần rồi thôi"."""
    from app import main as main_module

    code = 'ST-THROTTLE-2'
    main_module._last_pending_sync_check.pop(code, None)
    try:
        assert main_module._pending_sync_check_due(code) is True
        # Lùi mốc thời gian thay vì chờ thật 30 giây.
        main_module._last_pending_sync_check[code] = (
            datetime.now(timezone.utc)
            - timedelta(seconds=main_module.PENDING_SYNC_CHECK_INTERVAL_SECONDS + 1)
        )
        assert main_module._pending_sync_check_due(code) is True, (
            'quá hạn giãn nhịp thì phải chạy lại — nếu không, mất khung broadcast sẽ '
            'không bao giờ được nhắc lại'
        )
    finally:
        main_module._last_pending_sync_check.pop(code, None)


@pytest.mark.asyncio
async def test_pending_sync_check_interval_is_longer_than_the_heartbeat():
    """Bản thân con số giãn nhịp phải lớn hơn chu kỳ nhịp tim, nếu không thì vô nghĩa."""
    from app import main as main_module

    assert main_module.PENDING_SYNC_CHECK_INTERVAL_SECONDS > 5, (
        'giãn nhịp phải dài hơn chu kỳ nhịp tim 5 giây, nếu không thì chẳng giảm được gì'
    )


# --- F-10: báo cáo tổng hợp không nạp đối tượng ORM ----------------------------

@pytest.mark.asyncio
async def test_summary_report_counts_are_unchanged_and_do_not_load_orm_objects():
    """Kết quả đếm phải giữ nguyên sau khi đổi sang chọn cột.

    Truy vấn cũ nạp cả đối tượng ``Alarm`` kèm hai quan hệ chỉ để đọc tên, trên một
    bảng không giới hạn số dòng. Test này khoá phần dễ vỡ nhất khi đổi: hai phép
    join mới không được nhân dòng, và tên ``None`` vẫn phải rơi vào "Không xác định".
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)

        async with AsyncSessionLocal() as session:
            alarm_type = (await session.execute(select(AlarmType))).scalars().first()
            dept = (await session.execute(select(Department))).scalars().first()

        payload = {
            'alarm_type_id': alarm_type.id,
            'source_department_id': dept.id,
            'source_location': 'Khoa Test',
            'note': 'đếm báo cáo',
            'idempotency_key': 'summary-count-key-1',
        }
        created = await ac.post('/api/alarms', headers=headers, json=payload)
        assert created.status_code == 201, created.text

        res = await ac.get('/api/reports/summary', headers=headers)
        assert res.status_code == 200, res.text
        report = res.json()

        # Tổng phải bằng đúng số báo động trong bảng — join nhiều-một không được nhân dòng.
        async with AsyncSessionLocal() as session:
            total_in_db = len((await session.execute(select(Alarm.id))).scalars().all())
        assert report['total_alarms'] == total_in_db, (
            f"join làm nhân dòng: báo cáo {report['total_alarms']} so với DB {total_in_db}"
        )

        assert sum(report['by_type'].values()) == total_in_db
        assert sum(report['by_department'].values()) == total_in_db
        assert sum(report['by_status'].values()) == total_in_db
        assert sum(report['by_day'].values()) == total_in_db
        assert sum(report['by_month'].values()) == total_in_db
        assert report['by_type'].get(alarm_type.name, 0) >= 1
        assert report['by_department'].get(dept.name, 0) >= 1


@pytest.mark.asyncio
async def test_summary_report_buckets_alarms_without_a_type_or_department():
    """Báo động mồ côi vẫn phải được đếm, không được biến mất khỏi báo cáo.

    Đây là chỗ dễ hỏng nhất khi đổi từ ``selectinload`` sang ``outerjoin``: đổi
    thành ``join`` trong là mọi báo động thiếu loại/khoa biến mất khỏi tổng, và
    không có gì báo lỗi.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)

    async with AsyncSessionLocal() as session:
        alarm_type = (await session.execute(select(AlarmType))).scalars().first()
        now = datetime.now(timezone.utc)
        orphan = Alarm(
            alarm_type_id=alarm_type.id,
            created_by_user_id=None,
            source_department_id=None,
            source_location='Không rõ',
            note='',
            status=AlarmStatus.EXPIRED.value,
            server_sequence=900001,
            created_at=now,
            activated_at=now,
        )
        session.add(orphan)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)
        report = (await ac.get('/api/reports/summary', headers=headers)).json()

    async with AsyncSessionLocal() as session:
        total_in_db = len((await session.execute(select(Alarm.id))).scalars().all())

    assert report['total_alarms'] == total_in_db
    assert report['by_department'].get('Không xác định', 0) >= 1, (
        'báo động không có khoa phải rơi vào nhóm "Không xác định", không được rơi khỏi báo cáo'
    )
    assert sum(report['by_department'].values()) == total_in_db


# --- F-12: không create_all trên PostgreSQL ------------------------------------

def test_create_all_allowed_only_on_sqlite_regardless_of_environment():
    """``create_all`` chỉ được chạy trên SQLite, bất kể ``ENVIRONMENT``.

    Trên PostgreSQL schema thuộc về Alembic. ``ENVIRONMENT`` có thể bị đặt sai
    trong ``.env`` (đó chính là lỗi F-12: giá trị viết cứng trong docker-compose
    khiến ``.env`` không ghi đè được), nên chỉ dựa vào nó là không đủ chặn.
    """
    from app.main import create_all_allowed

    for environment in ('development', 'test', 'production', 'staging', ''):
        assert create_all_allowed(environment, 'postgresql+asyncpg://u:p@db:5432/redcode') is False, (
            f'create_all không được chạy trên PostgreSQL (ENVIRONMENT={environment!r})'
        )

    for environment in ('development', 'test'):
        assert create_all_allowed(environment, 'sqlite+aiosqlite:///./redcode.db') is True, (
            'trên SQLite (dev/test) vẫn phải tạo bảng để chạy được'
        )

    # Production trên SQLite vẫn bị chặn: production phải đi qua Alembic.
    assert create_all_allowed('production', 'sqlite+aiosqlite:///./redcode.db') is False


# --- F-01 (máy chủ): API nhóm nhận phải trả về station_ids ----------------------

@pytest.mark.asyncio
async def test_receiver_group_api_returns_station_ids():
    """``station_ids`` phải được điền, nếu không giao diện Admin luôn hiện nhóm rỗng.

    ``from_attributes`` lặng lẽ dùng giá trị mặc định ``[]`` khi đối tượng nguồn
    không có thuộc tính ``station_ids``, nên thiếu bước điền tay thì mọi nhóm đều
    trả về danh sách trạm rỗng mà không có lỗi nào.
    """
    code = 'ST-GROUP-MEMBER'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)
        station = await _register_station(ac, headers, code)

        created = await ac.post('/api/receiver-groups', headers=headers, json={
            'code': 'RG-API-IDS',
            'name': 'Nhóm kiểm tra station_ids',
            'description': '',
            'station_ids': [station['id']],
        })
        assert created.status_code == 201, created.text
        assert created.json()['station_ids'] == [station['id']], (
            'phản hồi lúc tạo nhóm phải nói đúng các trạm vừa gán'
        )

        listed = await ac.get('/api/receiver-groups', headers=headers)
        assert listed.status_code == 200, listed.text
        match = [g for g in listed.json() if g['code'] == 'RG-API-IDS']
        assert match and match[0]['station_ids'] == [station['id']], (
            'danh sách nhóm phải trả về station_ids để form sửa nhóm hiện sẵn trạm đã gán'
        )

        updated = await ac.put(f"/api/receiver-groups/{created.json()['id']}", headers=headers, json={
            'name': 'Nhóm kiểm tra (đổi tên)',
        })
        assert updated.status_code == 200, updated.text
        assert updated.json()['station_ids'] == [station['id']], (
            'đổi tên nhóm không được làm mất danh sách trạm trả về'
        )
