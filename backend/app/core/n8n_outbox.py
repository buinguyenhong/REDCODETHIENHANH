"""Hàng đợi gửi thông báo sang n8n (đường phụ, không chặn báo động).

Vòng đời một bản ghi, tường minh theo trạng thái:

    PENDING ──claim──▶ PROCESSING ──thành công──▶ SENT        (kết thúc)
                           │
                           ├── lỗi, còn lượt ──▶ FAILED  + next_attempt_at  (sẽ thử lại)
                           └── lỗi, hết lượt ──▶ EXHAUSTED                  (kết thúc)

FAILED và EXHAUSTED là hai chuyện khác nhau và phải tra được bằng trạng thái,
không phải suy ra từ ``next_attempt_at IS NULL``: bản ghi còn được thử lại thì
backoff cũng có lúc để ``next_attempt_at`` khác NULL, còn bản ghi đã bỏ hẳn thì
không. Trước đây cả hai dùng chung giá trị FAILED nên câu hỏi "còn bao nhiêu
thông báo đã bỏ hẳn" không có truy vấn nào trả lời được.

Quy tắc khi bật lại n8n: worker chỉ nhặt PENDING và FAILED còn lượt, nên thông
báo đã EXHAUSTED nằm im — bật lại n8n **không** tự phát lại chúng. Đó là chủ ý:
một hàng đợi tồn đọng lâu ngày mà tự xả ra sẽ dội một loạt thông báo cũ vào hệ
thống nhận. Người vận hành xem số lượng ở ``GET /api/system/status``
(``notification_outbox.exhausted``) và quyết định phát lại qua
``POST /api/system/outbox/requeue-exhausted``. Gửi lại là an toàn về trùng lặp:
mỗi bản ghi giữ nguyên Idempotency-Key ``redcode-outbox-{id}`` nên n8n tự khử.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
import httpx
from sqlalchemy import select, update, or_
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import NotificationOutbox, OutboxStatus, SystemEvent

logger = logging.getLogger("redcode.n8n_outbox")

class OutboxWorker:
    def __init__(self):
        self._running = False
        self._task = None

    async def start(self):
        self._running = True
        logger.info("Notification outbox worker started.")
        while self._running:
            try:
                await self.process_outbox()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing notification outbox: {e}")
            await asyncio.sleep(2)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Notification outbox worker stopped.")

    async def process_outbox(self):
        # n8n là tích hợp bổ sung: tắt thì worker không làm gì, và vì outbox chỉ
        # được ghi khi bật, tắt n8n không để lại tồn đọng nào để phát lại.
        if not settings.N8N_ENABLED:
            return
        now = datetime.now(timezone.utc)
        now_naive = now.replace(tzinfo=None)
        async with AsyncSessionLocal() as session:
            # Thu hồi job mồ côi: worker chết giữa chừng để lại PROCESSING với lease
            # đã hết hạn. Trả nó về FAILED để được thử lại — lượt đã bị tiêu lúc
            # claim, nên lần thử kế tiếp là lượt kế tiếp.
            await session.execute(update(NotificationOutbox).where(
                NotificationOutbox.status == OutboxStatus.PROCESSING.value,
                or_(NotificationOutbox.locked_at == None, NotificationOutbox.locked_at < now - timedelta(minutes=5))
            ).values(status=OutboxStatus.FAILED.value, locked_at=None))
            # Rồi chốt vòng đời cho những bản ghi đã chạm trần lượt thử. Bước này bắt
            # cả bản ghi vừa được thu hồi ở trên (tiến trình chết đúng lượt cuối) lẫn
            # bản ghi cũ còn nằm ở FAILED với next_attempt_at NULL từ trước — đúng
            # trạng thái mơ hồ mà EXHAUSTED sinh ra để xoá bỏ: bộ chọn bên dưới không
            # bao giờ nhặt lại (đã chạm trần), nhưng nếu để nguyên FAILED thì không
            # phép đếm theo trạng thái nào trả lời được "còn bao nhiêu thông báo đã
            # bỏ hẳn". Đây là chuyển trạng thái dữ liệu, không đổi schema.
            await session.execute(update(NotificationOutbox).where(
                NotificationOutbox.status == OutboxStatus.FAILED.value,
                NotificationOutbox.attempt_count >= settings.N8N_MAX_RETRIES
            ).values(status=OutboxStatus.EXHAUSTED.value, next_attempt_at=None))
            await session.commit()
            stmt = (
                select(NotificationOutbox)
                .where(
                    NotificationOutbox.status.in_([OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]),
                    NotificationOutbox.attempt_count < settings.N8N_MAX_RETRIES
                    , or_(NotificationOutbox.next_attempt_at == None, NotificationOutbox.next_attempt_at <= now)
                )
                .order_by(NotificationOutbox.created_at.asc())
                .limit(20)
            )
            all_pending = (await session.execute(stmt)).scalars().all()
            items = []
            for it in all_pending:
                if it.next_attempt_at is None:
                    items.append(it)
                else:
                    target_time = it.next_attempt_at
                    if target_time.tzinfo is None:
                        if target_time <= now_naive:
                            items.append(it)
                    else:
                        if target_time <= now:
                            items.append(it)

            if not items:
                return

            for item in items:
                await self._send_item(item.id)

    async def _send_item(self, item_id: int):
        if not settings.N8N_ENABLED:
            return
        async with AsyncSessionLocal() as session:
            now = datetime.now(timezone.utc)
            # Claim one job immediately before I/O. CAS prevents two workers
            # claiming the same job; increment persisted before a possible crash.
            claimed = await session.execute(update(NotificationOutbox).where(
                NotificationOutbox.id == item_id,
                NotificationOutbox.status.in_(['PENDING', 'FAILED']),
                NotificationOutbox.attempt_count < settings.N8N_MAX_RETRIES,
                or_(NotificationOutbox.next_attempt_at == None, NotificationOutbox.next_attempt_at <= now)
            ).values(status='PROCESSING', locked_at=now,
                     attempt_count=NotificationOutbox.attempt_count + 1))
            await session.commit()
            if claimed.rowcount != 1:
                return
            item = await session.get(NotificationOutbox, item_id)
            lease = item.locked_at
            success = False
            last_err = ""

            try:
                async with httpx.AsyncClient(timeout=settings.N8N_TIMEOUT_SECONDS) as client:
                    res = await client.post(settings.N8N_WEBHOOK_URL, json=item.payload, headers={'Idempotency-Key': f'redcode-outbox-{item.id}'})
                    if res.is_success:
                        success = True
                    else:
                        last_err = f"HTTP {res.status_code}: {res.text[:200]}"
            except Exception as e:
                last_err = str(e)[:300]

            # Only the lease owner can finish; another worker may reclaim a
            # genuinely stale job. n8n must dedup the stable idempotency key.
            await session.refresh(item)
            if item.status != 'PROCESSING' or item.locked_at != lease:
                return
            item.locked_at = None
            if success:
                item.status = OutboxStatus.SENT.value
                item.sent_at = now
                item.last_error = None
                item.next_attempt_at = None
                # Audit log
                session.add(SystemEvent(
                    station_id=None,
                    event_type="N8N_NOTIFICATION_SENT",
                    severity="INFO",
                    message="Durable notification delivered to n8n webhook",
                    event_metadata={"alarm_id": item.alarm_id, "outbox_id": item.id},
                    created_at=now
                ))
                logger.info(f"Outbox notification {item.id} (alarm {item.alarm_id}) sent successfully.")
            else:
                session.add(SystemEvent(event_type='N8N_REQUEST_FAILED', severity='WARNING', message='n8n delivery attempt failed', event_metadata={'outbox_id': item.id, 'attempt': item.attempt_count}, created_at=now))
                item.last_error = last_err
                if item.attempt_count >= settings.N8N_MAX_RETRIES:
                    # EXHAUSTED, không phải FAILED: hai vòng đời khác nhau. FAILED
                    # là "lần này lỗi, còn thử lại" (có next_attempt_at); EXHAUSTED
                    # là "đã bỏ hẳn". Trước đây cả hai dùng chung giá trị FAILED và
                    # chỉ phân biệt được bằng next_attempt_at IS NULL — thông tin
                    # ngầm, không đếm được bằng truy vấn theo trạng thái, nên không
                    # có cách nào trả lời "còn bao nhiêu thông báo đã bỏ hẳn".
                    item.status = OutboxStatus.EXHAUSTED.value
                    item.next_attempt_at = None
                    session.add(SystemEvent(
                        station_id=None,
                        event_type="N8N_NOTIFICATION_FAILED",
                        severity="ERROR",
                        message=f"Durable notification exhausted max retries: {last_err}",
                        event_metadata={"alarm_id": item.alarm_id, "outbox_id": item.id, "attempts": item.attempt_count},
                        created_at=now
                    ))
                    logger.warning(f"Outbox notification {item.id} exhausted {settings.N8N_MAX_RETRIES} attempts.")
                else:
                    item.status = OutboxStatus.FAILED.value
                    # Exponential backoff: 2s, 4s, 8s...
                    backoff_seconds = min(2 ** item.attempt_count, 300)
                    item.next_attempt_at = now + timedelta(seconds=backoff_seconds)
                    logger.info(f"Outbox notification {item.id} failed attempt {item.attempt_count}. Retrying in {backoff_seconds}s.")

            await session.commit()

outbox_worker = OutboxWorker()
