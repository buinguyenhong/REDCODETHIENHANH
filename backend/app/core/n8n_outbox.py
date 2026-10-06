import asyncio
import logging
from datetime import datetime, timezone, timedelta
import httpx
from sqlalchemy import select, update
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
        now_naive = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            stmt = (
                select(NotificationOutbox)
                .where(
                    NotificationOutbox.status.in_([OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]),
                    NotificationOutbox.attempt_count < settings.N8N_MAX_RETRIES
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
                item.status = OutboxStatus.PROCESSING.value
            await session.commit()

            for item in items:
                await self._send_item(item.id)

    async def _send_item(self, item_id: int):
        async with AsyncSessionLocal() as session:
            item = await session.get(NotificationOutbox, item_id)
            if not item:
                return

            now = datetime.now(timezone.utc)
            item.attempt_count += 1
            success = False
            last_err = ""

            try:
                async with httpx.AsyncClient(timeout=settings.N8N_TIMEOUT_SECONDS) as client:
                    res = await client.post(settings.N8N_WEBHOOK_URL, json=item.payload)
                    if res.is_success:
                        success = True
                    else:
                        last_err = f"HTTP {res.status_code}: {res.text[:200]}"
            except Exception as e:
                last_err = str(e)[:300]

            if success:
                item.status = OutboxStatus.SENT.value
                item.sent_at = now
                item.last_error = None
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
                    backoff_seconds = 2 * item.attempt_count
                    item.next_attempt_at = now + timedelta(seconds=backoff_seconds)
                    logger.info(f"Outbox notification {item.id} failed attempt {item.attempt_count}. Retrying in {backoff_seconds}s.")

            await session.commit()

outbox_worker = OutboxWorker()
