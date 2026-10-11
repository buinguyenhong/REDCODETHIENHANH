"""Regression tests cho đợt rà soát thứ hai (2 P1 + 2 P2).

Mỗi test khoá đúng một hành vi đã sai trước đợt sửa:

- P1: hai lượt ghi trạng thái ONLINE/OFFLINE của cùng một trạm chạy song song, nên
  giao dịch cũ có thể commit sau và để lại database OFFLINE trong khi socket mới
  đang hoạt động.
- P1: vòng giám sát kiểm lại nhịp tim rồi THẢ lock trước khi đóng socket, nên vẫn
  còn khe cho một nhịp tim hợp lệ chen vào giữa quyết định và thi hành.
- P2: ``POST /outbox/requeue-exhausted`` phát lại toàn bộ lịch sử lỗi trong một lần
  gọi, không trần số lượng và không nói còn lại bao nhiêu.
- P2: ``GET /api/health`` còn chờ tới 1,5 giây để hỏi ``/healthz`` của n8n — độ trễ
  của một hệ thống phụ quyết định độ trễ phép đo sức khoẻ hệ thống chính.
"""
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.database import AsyncSessionLocal, engine, Base
from app.seed import seed_database
from app.models import NotificationOutbox, OutboxStatus, Station, SystemEvent
from app.core.websocket_manager import manager
from app.config import settings


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


async def _register_station(client, headers, code):
    res = await client.post('/api/stations/register', headers=headers, json={
        'station_code': code, 'name': f'Trạm {code}', 'location': 'Test',
    })
    assert res.status_code == 201, res.text
    return res.json()['raw_device_token']


async def _station_row(code):
    async with AsyncSessionLocal() as session:
        return (await session.execute(
            select(Station).where(Station.station_code == code)
        )).scalar_one_or_none()


async def _make_outbox_row(**values):
    async with AsyncSessionLocal() as session:
        item = NotificationOutbox(event_type='ALARM_CREATED', payload={'k': 'v'}, **values)
        session.add(item)
        await session.commit()
        return item.id


# --- P1: hai lượt ghi trạng thái của cùng một trạm phải tuần tự hoá ------------

@pytest.mark.asyncio
async def test_presence_writes_are_serialized_and_converge_to_truth():
    """Lượt ghi OFFLINE của phiên cũ KHÔNG được thắng lượt ghi ONLINE của phiên mới.

    Kịch bản đúng như phát hiện mô tả: phiên cũ bắt đầu ghi OFFLINE (chậm), phiên
    mới kết nối và ghi ONLINE (nhanh). Nếu hai lượt ghi chạy song song thì lượt
    OFFLINE commit sau cùng và database báo OFFLINE trong khi socket mới đang hoạt
    động — bảng giám sát hiện một khoa đã tắt báo động trong lúc khoa đó đang nhận
    báo động bình thường.
    """
    code = 'ST-PRESENCE-RACE'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)
        await _register_station(ac, headers, code)

    manager.active_stations.pop(code, None)
    manager.last_heartbeats.pop(code, None)

    real_write = manager._update_station_db_status
    state = {'active': 0, 'overlapped': False}

    async def slow_write(station_code, connected, event=None, readiness=None, seen_at=None):
        state['active'] += 1
        if state['active'] > 1:
            state['overlapped'] = True
        try:
            # Lượt ghi OFFLINE chậm hơn hẳn lượt ghi ONLINE. Nếu không tuần tự hoá,
            # nó sẽ commit sau cùng và thắng.
            await asyncio.sleep(0.30 if not connected else 0.05)
            await real_write(station_code, connected, event, readiness, seen_at)
        finally:
            state['active'] -= 1

    manager._update_station_db_status = slow_write
    try:
        async def old_session_leaves():
            manager.active_stations.pop(code, None)
            return await manager._sync_station_db_status(code, event='DEVICE_DISCONNECTED')

        async def new_session_arrives():
            await asyncio.sleep(0.02)
            manager.active_stations[code] = FakeSocket()
            return await manager._sync_station_db_status(code, event='DEVICE_CONNECTED')

        results = await asyncio.gather(old_session_leaves(), new_session_arrives())

        assert state['overlapped'] is False, (
            'hai lượt ghi trạng thái của cùng một trạm không được chạy song song'
        )
        # Lượt ghi cuối phải phản ánh đúng sổ phiên tại thời điểm ghi.
        assert results[-1] is True
        assert code in manager.active_stations

        row = await _station_row(code)
        assert row.status == 'ONLINE', 'database phải hội tụ về trạng thái thật của bộ nhớ'
        assert row.websocket_connected is True
    finally:
        manager._update_station_db_status = real_write
        manager.active_stations.pop(code, None)
        manager.last_heartbeats.pop(code, None)


@pytest.mark.asyncio
async def test_superseded_disconnect_does_not_log_a_false_disconnect_event():
    """Ghi audit theo HÀNH ĐỘNG của phiên, nhưng chỉ khi hành động đó khớp sự thật.

    Một lượt ngắt bị phiên mới kế chỗ không phải là "trạm mất kết nối". Ghi
    DEVICE_DISCONNECTED ở đây khiến người đọc log tưởng một khoa vừa rơi khỏi hệ
    thống, trong khi thực tế nó đang online.
    """
    code = 'ST-SUPERSEDE-AUDIT'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)
        await _register_station(ac, headers, code)

    # Phiên mới đang giữ trạm, rồi phiên cũ mới hoàn tất việc rời đi.
    manager.active_stations[code] = FakeSocket()
    try:
        connected = await manager._sync_station_db_status(code, event='DEVICE_DISCONNECTED')
        assert connected is True, 'sự thật là trạm đang online'

        row = await _station_row(code)
        assert row.status == 'ONLINE'
        assert row.websocket_connected is True

        async with AsyncSessionLocal() as session:
            events = (await session.execute(
                select(SystemEvent).where(SystemEvent.event_type == 'DEVICE_DISCONNECTED')
            )).scalars().all()
            assert not any(
                (e.event_metadata or {}).get('station_code') == code for e in events
            ), 'không được ghi audit "mất kết nối" cho một trạm vẫn đang online'

        # Chiều ngược lại: ngắt thật thì PHẢI có audit, nếu không log mất dấu sự kiện.
        manager.active_stations.pop(code, None)
        connected = await manager._sync_station_db_status(code, event='DEVICE_DISCONNECTED')
        assert connected is False
        async with AsyncSessionLocal() as session:
            events = (await session.execute(
                select(SystemEvent).where(SystemEvent.event_type == 'DEVICE_DISCONNECTED')
            )).scalars().all()
            assert any(
                (e.event_metadata or {}).get('station_code') == code for e in events
            ), 'ngắt thật thì phải có bản ghi kiểm toán'
    finally:
        manager.active_stations.pop(code, None)
        manager.last_heartbeats.pop(code, None)


# --- P1: quyết định ngắt và thi hành phải nguyên tử ---------------------------

@pytest.mark.asyncio
async def test_timeout_removes_session_before_closing_socket():
    """Nhịp tim đến trong lúc socket đang đóng KHÔNG được làm sống lại phiên đã cắt.

    Code cũ kiểm lại nhịp tim dưới lock rồi THẢ lock trước khi gọi ``ws.close()``.
    Trong khe đó một nhịp tim hợp lệ vẫn được chấp nhận, làm trạng thái nhảy về
    ONLINE trong khi phiên đang bị ngắt.
    """
    station_code = 'ST-TIMEOUT-ATOMIC'
    threshold = 15
    manager.active_stations.pop(station_code, None)
    manager.last_heartbeats.pop(station_code, None)

    observed = {}

    class SlowCloseSocket(FakeSocket):
        async def close(self, code=None, reason=None):
            # Ở đúng thời điểm gọi close(), quyết định ngắt phải đã hoàn tất: phiên
            # đã bị rút khỏi sổ, nên nhịp tim tới muộn bị từ chối.
            observed['still_registered'] = station_code in manager.active_stations
            observed['touch_accepted'] = await manager.touch_station(station_code)
            await super().close(code=code, reason=reason)

    ws = SlowCloseSocket()
    manager.active_stations[station_code] = ws
    manager.last_heartbeats[station_code] = datetime.now(timezone.utc) - timedelta(seconds=120)

    await manager._enforce_timeouts([(station_code, ws)], threshold)

    assert observed['still_registered'] is False, 'phiên phải bị rút khỏi sổ TRƯỚC khi đóng socket'
    assert observed['touch_accepted'] is False
    assert station_code not in manager.active_stations
    assert station_code not in manager.last_heartbeats
    assert ws.closed_with is not None and ws.closed_with[0] == 1011

    manager.active_stations.pop(station_code, None)
    manager.last_heartbeats.pop(station_code, None)


# --- P2: phát lại thông báo cạn lượt phải có trần -----------------------------

@pytest.mark.asyncio
async def test_requeue_exhausted_is_bounded_and_reports_remaining_scope():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        headers = await admin_headers(ac)

        ids = [
            await _make_outbox_row(
                status=OutboxStatus.EXHAUSTED.value, attempt_count=3, last_error='n8n down'
            )
            for _ in range(5)
        ]

        # (a) ids= chỉ chạm đúng những bản ghi được chọn.
        scoped = (await ac.post(
            '/api/system/outbox/requeue-exhausted', headers=headers, params={'ids': ids[:2]},
        )).json()
        assert scoped['requeued'] == 2
        assert scoped['has_more'] is (scoped['remaining_exhausted'] > 0)
        async with AsyncSessionLocal() as session:
            for row_id in ids[:2]:
                assert (await session.get(NotificationOutbox, row_id)).status == OutboxStatus.PENDING.value
            for row_id in ids[2:]:
                assert (await session.get(NotificationOutbox, row_id)).status == OutboxStatus.EXHAUSTED.value

        # (b) limit= có tác dụng, và phản hồi nói còn lại bao nhiêu để người vận
        #     hành biết mình đang ở đâu thay vì phải đoán.
        one = (await ac.post(
            '/api/system/outbox/requeue-exhausted', headers=headers, params={'limit': 1},
        )).json()
        assert one['requeued'] == 1
        assert one['limit'] == 1
        assert one['remaining_exhausted'] >= 2
        assert one['has_more'] is True

        # (c) Trần cứng: một lần gọi không giới hạn sẽ dội cả lịch sử lỗi vào n8n.
        assert (await ac.post(
            '/api/system/outbox/requeue-exhausted', headers=headers, params={'limit': 500},
        )).status_code == 422
        assert (await ac.post(
            '/api/system/outbox/requeue-exhausted', headers=headers, params={'limit': 0},
        )).status_code == 422

        # (d) OPERATOR vẫn không được đụng vào hàng đợi.
        op = await ac.post('/api/auth/login', json={'username': 'operator_cc', 'password': 'pass123456'})
        op_headers = {'Authorization': f"Bearer {op.json()['access_token']}"}
        assert (await ac.post(
            '/api/system/outbox/requeue-exhausted', headers=op_headers, params={'limit': 1},
        )).status_code == 403


# --- P2: health chính không được gọi ra mạng ngoài ----------------------------

@pytest.mark.asyncio
async def test_health_never_calls_n8n_and_reports_configuration_only():
    """n8n là đường bổ sung: độ trễ của nó không được quyết định độ trễ health chính."""
    previous = (settings.N8N_ENABLED, settings.N8N_WEBHOOK_URL)
    settings.N8N_ENABLED = True
    # Trỏ vào cổng không có gì lắng nghe: code cũ sẽ chờ tới hết timeout ở đây.
    settings.N8N_WEBHOOK_URL = 'http://127.0.0.1:9/webhook/redcode'
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
            def explode(*args, **kwargs):
                raise AssertionError('/api/health không được gọi ra mạng ngoài')

            with patch('httpx.AsyncClient', side_effect=explode):
                started = datetime.now(timezone.utc)
                res = await ac.get('/api/health')
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()

            assert res.status_code == 200
            body = res.json()
            # Trường n8n phản ánh CẤU HÌNH, không phải khả năng kết nối.
            assert body['n8n'] == 'enabled'
            assert elapsed < 1.0, 'health chính không được chờ một phép đo mạng ngoài'
            assert body['status'] in ('ok', 'degraded')

            # Kiểm tra n8n sống hay không là việc riêng, và vẫn yêu cầu ADMIN.
            assert (await ac.get('/api/health/n8n')).status_code == 401

            headers = await admin_headers(ac)
            n8n_body = (await ac.get('/api/health/n8n', headers=headers)).json()
            assert n8n_body['reachable'] is False
            assert n8n_body['status'] == 'degraded'

        # Khi n8n tắt thì trường cấu hình nói đúng là tắt, không đi kiểm tra gì cả.
        settings.N8N_ENABLED = False
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
            with patch('httpx.AsyncClient', side_effect=explode):
                assert (await ac.get('/api/health')).json()['n8n'] == 'disabled'
            headers = await admin_headers(ac)
            off = (await ac.get('/api/health/n8n', headers=headers)).json()
            assert off['status'] == 'disabled'
            assert off['reachable'] is False
            assert off['latency_ms'] is None
    finally:
        settings.N8N_ENABLED, settings.N8N_WEBHOOK_URL = previous
