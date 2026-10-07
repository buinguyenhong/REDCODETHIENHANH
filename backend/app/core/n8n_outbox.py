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
        if not settings.N8N_WEBHOOK_URL or not settings.N8N_WEBHOOK_URL.strip():
            return

        now = datetime.now(timezone.utc)
        now_naive = now.replace(tzinfo=None)
        async with AsyncSessionLocal() as session:
            await session.execute(update(NotificationOutbox).where(NotificationOutbox.status == OutboxStatus.PROCESSING.value, or_(NotificationOutbox.locked_at == None, NotificationOutbox.locked_at < now - timedelta(minutes=5))).values(status=OutboxStatus.FAILED.value, locked_at=None))
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
                    item.status = OutboxStatus.FAILED.value
                    item.next_attempt_at = None
                    session.add(SystemEvent(
                        station_id=None,
                        event_type="N8N_NOTIFICATION_FAILED",
                        severity="ERROR",
                        message=f"Durable notification exhausted max retries: {last_err}",
                        event_metadata={"alarm_id": item.alarm_id, "outbox_id": item.id, "attempts": item.attempt_count},
                        created_at=now
                    ))
                    logger.warning(f"Outbox notification {item.id} exhausted {settings.N8N_MAX_RETRIES} attempts. Error: {last_err}")
                else:
                    item.status = OutboxStatus.FAILED.value
                    # Exponential backoff: 2s, 4s, 8s...
                    backoff_seconds = min(2 ** item.attempt_count, 300)
                    item.next_attempt_at = now + timedelta(seconds=backoff_seconds)
                    logger.info(f"Outbox notification {item.id} failed attempt {item.attempt_count}. Retrying in {backoff_seconds}s.")

            await session.commit()

outbox_worker = OutboxWorker()
