from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import SystemEvent, Station, Alarm, User, NotificationOutbox, OutboxStatus
from app.api.deps import get_current_active_admin
from app.core.websocket_manager import manager

router = APIRouter(prefix="/system", tags=["System Management"])

@router.get("/status")
async def get_system_status(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(Station)
    stations = (await db.execute(stmt)).scalars().all()

    online_count = sum(1 for s in stations if s.status == "ONLINE")
    offline_count = len(stations) - online_count

    # Tồn đọng thông báo n8n, đếm theo trạng thái. n8n là đường phụ (báo động nội
    # bộ không đi qua đây), nhưng "đã bỏ hẳn bao nhiêu thông báo" là câu hỏi vận
    # hành thật và trước đây không trả lời được: FAILED gộp cả lỗi còn thử lại lẫn
    # lỗi đã cạn lượt, nên phải suy ra từ next_attempt_at IS NULL.
    counts = dict((await db.execute(
        select(NotificationOutbox.status, func.count(NotificationOutbox.id)).group_by(NotificationOutbox.status)
    )).all())
    exhausted = (await db.execute(
        select(NotificationOutbox)
        .where(NotificationOutbox.status == OutboxStatus.EXHAUSTED.value)
        .order_by(desc(NotificationOutbox.created_at))
        .limit(20)
    )).scalars().all()

    return {
        "core_status": "RUNNING",
        "active_ws_stations": list(manager.active_stations.keys()),
        "active_dashboards_count": len(manager.active_dashboards),
        "total_configured_stations": len(stations),
        "online_stations": online_count,
        "offline_stations": offline_count,
        "notification_outbox": {
            "pending": counts.get(OutboxStatus.PENDING.value, 0),
            "processing": counts.get(OutboxStatus.PROCESSING.value, 0),
            "sent": counts.get(OutboxStatus.SENT.value, 0),
            # Còn được thử lại (đang chờ backoff hoặc vừa lỗi).
            "retryable_failed": counts.get(OutboxStatus.FAILED.value, 0),
            # Đã cạn lượt thử. Không tự gửi lại nữa; chỉ gửi lại khi admin yêu cầu.
            "exhausted": counts.get(OutboxStatus.EXHAUSTED.value, 0),
            "exhausted_recent": [
                {
                    "id": item.id,
                    "alarm_id": item.alarm_id,
                    "event_type": item.event_type,
                    "attempt_count": item.attempt_count,
                    "last_error": (item.last_error or "")[:200],
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in exhausted
            ],
        },
    }

@router.post("/outbox/requeue-exhausted")
async def requeue_exhausted_notifications(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    """Đưa các thông báo đã cạn lượt thử về hàng đợi. Yêu cầu ADMIN.

    Quy tắc khi bật lại n8n: worker chỉ nhặt PENDING/FAILED còn lượt, nên thông báo
    đã cạn lượt sẽ nằm im ở EXHAUSTED vĩnh viễn — đó là chủ ý, không phải bỏ sót.
    Sau khi n8n sống lại, người vận hành quyết định phát lại bằng endpoint này;
    đặt attempt_count về 0 để vòng đời bắt đầu lại từ đầu.

    Gửi lại là an toàn về mặt trùng lặp: mỗi bản ghi giữ nguyên Idempotency-Key
    ``redcode-outbox-{id}``, nên n8n tự khử trùng nếu thông báo trước đó đã tới.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(NotificationOutbox)
        .where(NotificationOutbox.status == OutboxStatus.EXHAUSTED.value)
        .values(
            status=OutboxStatus.PENDING.value,
            attempt_count=0,
            next_attempt_at=None,
            locked_at=None,
        )
    )
    if result.rowcount:
        db.add(SystemEvent(
            station_id=None,
            event_type="N8N_OUTBOX_REQUEUED",
            severity="INFO",
            message=f"{result.rowcount} thông báo đã cạn lượt được đưa lại hàng đợi",
            event_metadata={"count": result.rowcount, "by_user_id": admin.id},
            created_at=now,
        ))
    await db.commit()
    return {"requeued": result.rowcount}

@router.get("/events")
async def list_system_events(
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(SystemEvent).order_by(desc(SystemEvent.created_at)).limit(limit)
    if event_type:
        stmt = stmt.where(SystemEvent.event_type == event_type)
    if severity:
        stmt = stmt.where(SystemEvent.severity == severity.upper())

    events = (await db.execute(stmt)).scalars().all()
    return events
