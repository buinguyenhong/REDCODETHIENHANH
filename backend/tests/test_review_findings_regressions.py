"""Regression tests cho đợt rà soát 5 phát hiện (2 P1 + 3 P2).

Mỗi test ở đây khoá đúng một hành vi đã sai trước đợt sửa, để lỗi không quay lại:

- P1: nhịp tim HTTP không có WebSocket vẫn ghi trạm ONLINE.
- P1: monitor nhịp tim ngắt trạm theo ảnh chụp cũ (race với nhịp tim mới).
- P2: /api/health tổng thể báo ok khi vòng giám sát nhịp tim đã chết.
- P2: /api/health/db và /api/health/websocket công khai và lộ chi tiết nội bộ.
- P2: thông báo n8n hết lượt thử không phân biệt được với lỗi còn thử lại.
"""
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.database import AsyncSessionLocal, engine, Base
from app.seed import seed_database
from app.models import NotificationOutbox, OutboxStatus, Station, SystemEvent
from app.core.n8n_outbox import outbox_worker
from app.core.websocket_manager import manager
from app.config import settings

import pytest_asyncio


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
    """Socket giả đủ để ConnectionManager gọi close() mà không cần mạng thật."""

    def __init__(self):
        self.closed_with = None

    async def close(self, code=None, reason=None):
        self.closed_with = (code, reason)

    async def send_text(self, payload):
        return None


# --- P1: nhịp tim HTTP không có WebSocket -------------------------------------

@pytest.mark.asyncio
async def test_http_heartbeat_without_websocket_never_reports_online():
    """Trạm gọi được API nhưng không có kênh nhận báo động KHÔNG được coi là ONLINE."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)
        code = 'ST-HB-NO-WS'
        reg = await ac.post('/api/stations/register', headers=headers, json={
            'station_code': code, 'name': 'Trạm kiểm thử nhịp tim', 'location': 'Test',
        })
        assert reg.status_code == 201, reg.text
        token = reg.json()['raw_device_token']

        # Chắc chắn không có socket nào đăng ký cho mã này.
        manager.active_stations.pop(code, None)

        hb = await ac.post('/api/stations/heartbeat', json={
            'station_code': code, 'device_token': token, 'audio_ready': True, 'client_ready': True,
        })
        assert hb.status_code == 200, hb.text
        body = hb.json()

        # Thiết bị còn gọi được API, nhưng KHÔNG nhận được báo động.
        assert body['device_reachable'] is True
        assert body['websocket_connected'] is False
        assert body['can_receive_alarms'] is False

        async with AsyncSessionLocal() as session:
            station = (await session.execute(
                select(Station).where(Station.station_code == code)
            )).scalar_one()
            # Đây là lỗi P1: trước đây status luôn là ONLINE ở đây.
            assert station.status == 'OFFLINE'
            assert station.websocket_connected is False
            # Cờ sẵn sàng cũng không được ghi khi thiếu kênh nhận báo động.
            assert station.audio_ready is False
            assert station.client_ready is False
            # Nhưng vẫn ghi nhận thiết bị còn sống.
            assert station.last_seen_at is not None

        # Có socket thật thì mới được ONLINE.
        manager.active_stations[code] = FakeSocket()
        try:
            hb2 = await ac.post('/api/stations/heartbeat', json={
                'station_code': code, 'device_token': token, 'audio_ready': True, 'client_ready': True,
            })
            assert hb2.json()['websocket_connected'] is True
            assert hb2.json()['can_receive_alarms'] is True
            async with AsyncSessionLocal() as session:
                station = (await session.execute(
                    select(Station).where(Station.station_code == code)
                )).scalar_one()
                assert station.status == 'ONLINE'
                assert station.audio_ready is True
        finally:
            manager.active_stations.pop(code, None)


# --- P1: race giữa ảnh chụp và lúc ngắt ---------------------------------------

@pytest.mark.asyncio
async def test_timeout_enforcement_rechecks_identity_and_freshness():
    """Không được ngắt theo ảnh chụp cũ: phiên mới hoặc nhịp tim mới phải được tha."""
    code = 'ST-TIMEOUT-RACE'
    threshold = 15

    # (a) Nhịp tim mới đến sau khi ảnh chụp được lấy -> không ngắt.
    ws_fresh = FakeSocket()
    manager.active_stations[code] = ws_fresh
    manager.last_heartbeats[code] = datetime.now(timezone.utc)
    await manager._enforce_timeouts([(code, ws_fresh)], threshold)
    assert ws_fresh.closed_with is None
    assert code in manager.active_stations

    # (b) Socket đã bị thay bằng phiên khác -> ảnh chụp vô hiệu, không ngắt phiên mới.
    ws_new = FakeSocket()
    ws_old = FakeSocket()
    manager.active_stations[code] = ws_new
    manager.last_heartbeats[code] = datetime.now(timezone.utc) - timedelta(seconds=120)
    await manager._enforce_timeouts([(code, ws_old)], threshold)
    assert ws_old.closed_with is None
    assert ws_new.closed_with is None
    assert manager.active_stations.get(code) is ws_new

    # (c) Thật sự quá hạn -> phải ngắt, đúng mã 1011, và gỡ khỏi danh sách.
    ws_stale = FakeSocket()
    manager.active_stations[code] = ws_stale
    manager.last_heartbeats[code] = datetime.now(timezone.utc) - timedelta(seconds=120)
    await manager._enforce_timeouts([(code, ws_stale)], threshold)
    assert ws_stale.closed_with is not None
    assert ws_stale.closed_with[0] == 1011
    assert code not in manager.active_stations
    assert code not in manager.last_heartbeats

    manager.active_stations.pop(code, None)
    manager.last_heartbeats.pop(code, None)


# --- P2: health tổng thể phải phản ánh lỗi giám sát ---------------------------

@pytest.mark.asyncio
async def test_health_readiness_reflects_dead_monitor():
    """Vòng giám sát chết là suy giảm thật: readiness phải nói ra, liveness vẫn ok."""
    class Done:
        def done(self):
            return True

    original_task = manager._monitor_task
    original_expected = manager._monitor_expected
    try:
        manager._monitor_expected = True
        manager._monitor_task = Done()
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
            body = (await ac.get('/api/health')).json()
        assert body['websocket'] == 'degraded'
        # Trước đây chỉ cần database ok là status trả "ok" — dashboard hiện HOẠT
        # ĐỘNG trong khi hệ thống đã mù với thiết bị offline và không còn kết thúc
        # báo động hết hạn.
        assert body['status'] == 'degraded'
        # Tiến trình vẫn phục vụ được request -> còn sống.
        assert body['liveness'] == 'ok'
        assert body['database'] == 'ok'
    finally:
        manager._monitor_task = original_task
        manager._monitor_expected = original_expected


@pytest.mark.asyncio
async def test_health_reports_not_started_separately_from_degraded():
    """Chưa từng chạy start_monitor KHÁC với đã chạy rồi chết."""
    original_task = manager._monitor_task
    original_expected = manager._monitor_expected
    try:
        manager._monitor_expected = False
        manager._monitor_task = None
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
            body = (await ac.get('/api/health')).json()
        assert body['websocket'] == 'not_started'
        assert body['status'] == 'ok'
        assert body['liveness'] == 'ok'
    finally:
        manager._monitor_task = original_task
        manager._monitor_expected = original_expected


# --- P2: health chẩn đoán không được công khai --------------------------------

@pytest.mark.asyncio
async def test_health_diagnostics_require_admin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        for path in ('/api/health/db', '/api/health/websocket'):
            anon = await ac.get(path)
            assert anon.status_code == 401, f'{path} phải yêu cầu xác thực'

        # OPERATOR không phải ADMIN cũng không được xem chi tiết hạ tầng.
        op = await ac.post('/api/auth/login', json={'username': 'operator_cc', 'password': 'pass123456'})
        assert op.status_code == 200, op.text
        op_headers = {'Authorization': f"Bearer {op.json()['access_token']}"}
        for path in ('/api/health/db', '/api/health/websocket'):
            denied = await ac.get(path, headers=op_headers)
            assert denied.status_code == 403, f'{path} phải từ chối OPERATOR'

        headers = await admin_headers(ac)
        db_body = (await ac.get('/api/health/db', headers=headers)).json()
        assert db_body['status'] == 'ok'
        # Không lộ thông báo exception thô / chuỗi kết nối.
        assert 'detail' not in db_body

        ws_body = (await ac.get('/api/health/websocket', headers=headers)).json()
        assert 'monitor_running' in ws_body

        # Health công khai vẫn phải tối thiểu: không mã trạm.
        public = (await ac.get('/api/health')).json()
        assert 'active_station_codes' not in public


# --- P2: outbox hết lượt thử phải phân biệt được -------------------------------

async def _make_outbox_row(**values):
    async with AsyncSessionLocal() as session:
        item = NotificationOutbox(event_type='ALARM_CREATED', payload={'k': 'v'}, **values)
        session.add(item)
        await session.commit()
        return item.id


@pytest.mark.asyncio
async def test_exhausted_outbox_row_is_distinct_from_retryable_failure():
    previous = (settings.N8N_ENABLED, settings.N8N_WEBHOOK_URL, settings.N8N_MAX_RETRIES)
    settings.N8N_ENABLED = True
    settings.N8N_WEBHOOK_URL = 'http://127.0.0.1:1/test'
    settings.N8N_MAX_RETRIES = 2
    try:
        from unittest.mock import AsyncMock, patch

        # Còn lượt: lần lỗi đầu tiên -> FAILED, có next_attempt_at.
        retryable_id = await _make_outbox_row(status='PENDING', attempt_count=0)
        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, side_effect=RuntimeError('n8n down')):
            await outbox_worker._send_item(retryable_id)
        async with AsyncSessionLocal() as session:
            row = await session.get(NotificationOutbox, retryable_id)
            assert row.status == OutboxStatus.FAILED.value
            assert row.next_attempt_at is not None

        # Hết lượt: attempt_count đã bằng max -> EXHAUSTED, không còn lịch thử lại.
        exhausted_id = await _make_outbox_row(status='PENDING', attempt_count=1)
        with patch('httpx.AsyncClient.post', new_callable=AsyncMock, side_effect=RuntimeError('n8n down')):
            await outbox_worker._send_item(exhausted_id)
        async with AsyncSessionLocal() as session:
            row = await session.get(NotificationOutbox, exhausted_id)
            # Đây là lỗi P2: trước đây giá trị này là FAILED, không phân biệt được
            # với lỗi còn thử lại nếu không suy từ next_attempt_at IS NULL.
            assert row.status == OutboxStatus.EXHAUSTED.value
            assert row.next_attempt_at is None

        # Đã cạn lượt thì worker không tự nhặt lại nữa, dù webhook đã sống lại.
        with patch('httpx.AsyncClient.post', new_callable=AsyncMock):
            await outbox_worker.process_outbox()
        async with AsyncSessionLocal() as session:
            row = await session.get(NotificationOutbox, exhausted_id)
            # Vẫn EXHAUSTED và attempt_count không tăng: bản ghi chưa hề bị claim
            # lại, đúng quy tắc "bật lại n8n không tự phát lại thông báo đã bỏ hẳn".
            assert row.status == OutboxStatus.EXHAUSTED.value
            assert row.attempt_count == 2

        # Và phải có bản ghi kiểm toán để người vận hành biết là có thông báo bỏ hẳn.
        async with AsyncSessionLocal() as session:
            events = (await session.execute(
                select(SystemEvent).where(
                    SystemEvent.event_type == 'N8N_NOTIFICATION_FAILED',
                    SystemEvent.severity == 'ERROR',
                )
            )).scalars().all()
            assert any((e.event_metadata or {}).get('outbox_id') == exhausted_id for e in events)
    finally:
        settings.N8N_ENABLED, settings.N8N_WEBHOOK_URL, settings.N8N_MAX_RETRIES = previous


@pytest.mark.asyncio
async def test_admin_can_see_and_requeue_exhausted_notifications():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)
        exhausted_id = await _make_outbox_row(status=OutboxStatus.EXHAUSTED.value, attempt_count=3, last_error='n8n down')

        status_body = (await ac.get('/api/system/status', headers=headers)).json()
        assert status_body['notification_outbox']['exhausted'] >= 1
        assert any(
            item['id'] == exhausted_id
            for item in status_body['notification_outbox']['exhausted_recent']
        )

        # OPERATOR không được đụng vào hàng đợi.
        op = await ac.post('/api/auth/login', json={'username': 'operator_cc', 'password': 'pass123456'})
        op_headers = {'Authorization': f"Bearer {op.json()['access_token']}"}
        assert (await ac.post('/api/system/outbox/requeue-exhausted', headers=op_headers)).status_code == 403

        requeue = await ac.post('/api/system/outbox/requeue-exhausted', headers=headers)
        assert requeue.status_code == 200
        assert requeue.json()['requeued'] >= 1

        async with AsyncSessionLocal() as session:
            row = await session.get(NotificationOutbox, exhausted_id)
            assert row.status == OutboxStatus.PENDING.value
            assert row.attempt_count == 0
            assert row.next_attempt_at is None
