import asyncio
import logging
from datetime import datetime, timezone
import httpx
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import SystemEvent

logger = logging.getLogger("redcode.n8n")

async def send_n8n_alarm_notification(payload: dict):
    """
    Sends alarm notification to n8n webhook asynchronously with retry and logging.
    Executes in background so core alarm handling is never delayed.
    """
    if not settings.N8N_WEBHOOK_URL or settings.N8N_WEBHOOK_URL.strip() == "":
        return

    url = settings.N8N_WEBHOOK_URL
    timeout = settings.N8N_TIMEOUT_SECONDS
    retries = settings.N8N_MAX_RETRIES

    success = False
    last_error = ""

    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
                if response.is_success:
                    success = True
                    logger.info(f"n8n webhook delivered successfully (attempt {attempt}): {response.status_code}")
                    break
                else:
                    last_error = f"HTTP {response.status_code}: {response.text}"
                    logger.warning(f"n8n webhook attempt {attempt} failed: {last_error}")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"n8n webhook attempt {attempt} exception: {last_error}")

        if attempt < retries:
            await asyncio.sleep(1.5 * attempt)

    # Log outcome to database system_events table
    async with AsyncSessionLocal() as session:
        try:
            now = datetime.now(timezone.utc)
            if success:
                event = SystemEvent(
                    station_id=None,
                    event_type="N8N_REQUEST_SUCCESS",
                    severity="INFO",
                    message="Alarm webhook delivered to n8n successfully",
                    event_metadata={"alarm_id": payload.get("alarm_id"), "url": url},
                    created_at=now
                )
            else:
                event = SystemEvent(
                    station_id=None,
                    event_type="N8N_REQUEST_FAILED",
                    severity="ERROR",
                    message=f"Failed to deliver alarm webhook to n8n after {retries} attempts: {last_error}",
                    event_metadata={"alarm_id": payload.get("alarm_id"), "url": url, "error": last_error},
                    created_at=now
                )
            session.add(event)
            await session.commit()
        except Exception as e:
            logger.error(f"Error logging n8n event to DB: {e}")
