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
    limit: int = Query(
        50, ge=1, le=200,
        description="Số thông báo tối đa đưa lại hàng đợi trong một lần gọi.",
    ),
    ids: Optional[List[int]] = Query(
        None,
        description="Chỉ đưa lại đúng các bản ghi này (theo id). Bỏ trống = lấy theo thứ tự cũ nhất trước.",
    ),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    """Đưa thông báo đã cạn lượt thử về hàng đợi, có giới hạn số lượng. Yêu cầu ADMIN.

    Quy tắc khi bật lại n8n: worker chỉ nhặt PENDING/FAILED còn lượt, nên thông báo
    đã cạn lượt sẽ nằm im ở EXHAUSTED vĩnh viễn — đó là chủ ý, không phải bỏ sót.
    Sau khi n8n sống lại, người vận hành quyết định phát lại bằng endpoint này;
    đặt attempt_count về 0 để vòng đời bắt đầu lại từ đầu.

    **Có trần số lượng, và đây là chủ ý.** Một lần gọi không giới hạn sẽ đẩy toàn
    bộ lịch sử lỗi — có thể hàng nghìn thông báo tích từ nhiều tuần — vào hàng đợi
    cùng lúc, và n8n sống lại sẽ nhận một đợt dội ngay khi vừa hồi phục. Trần mặc
    định 50, tối đa 200 mỗi lần. Muốn phát lại nhiều hơn thì gọi lặp: phản hồi luôn
    nói còn bao nhiêu bản ghi ở lại, để người vận hành biết mình đang ở đâu.

    Truyền ``ids`` để chỉ phát lại đúng những bản ghi đã chọn — dùng khi đã xem
    ``exhausted_recent`` ở ``GET /api/system/status`` và biết chính xác cái nào cần
    gửi lại.

    Gửi lại là an toàn về mặt trùng lặp: mỗi bản ghi giữ nguyên Idempotency-Key
    ``redcode-outbox-{id}``, nên n8n tự khử trùng nếu thông báo trước đó đã tới.
    """
    now = datetime.now(timezone.utc)

    # 1. Chọn đúng các bản ghi sẽ phát lại. Lọc và chốt danh sách trước khi ghi,
    #    để biết chắc mình đã chạm vào bao nhiêu bản ghi.
    candidates = select(NotificationOutbox.id).where(
        NotificationOutbox.status == OutboxStatus.EXHAUSTED.value
    )
    if ids:
        candidates = candidates.where(NotificationOutbox.id.in_(ids))
    # Cũ nhất trước: thông báo tồn lâu nhất được gửi lại trước, đúng thứ tự hàng đợi.
    selected = (await db.execute(
        candidates.order_by(NotificationOutbox.created_at).limit(limit)
    )).scalars().all()

    if selected:
        await db.execute(
            update(NotificationOutbox)
            .where(NotificationOutbox.id.in_(selected))
            .values(
                status=OutboxStatus.PENDING.value,
                attempt_count=0,
                next_attempt_at=None,
                locked_at=None,
            )
        )
        db.add(SystemEvent(
            station_id=None,
            event_type="N8N_OUTBOX_REQUEUED",
            severity="INFO",
            message=f"{len(selected)} thông báo đã cạn lượt được đưa lại hàng đợi",
            event_metadata={
                "count": len(selected),
                "limit": limit,
                "explicit_ids": bool(ids),
                "by_user_id": admin.id,
            },
            created_at=now,
        ))
    await db.commit()

    # 2. Còn lại bao nhiêu? Không có con số này thì người vận hành phải đoán xem đã
    #    phát lại hết chưa.
    remaining = (await db.execute(
        select(func.count(NotificationOutbox.id)).where(
            NotificationOutbox.status == OutboxStatus.EXHAUSTED.value
        )
    )).scalar() or 0

    return {
        "requeued": len(selected),
        "limit": limit,
        "remaining_exhausted": remaining,
        "has_more": remaining > 0,
    }

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
