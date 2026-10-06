import asyncio
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import (
    Alarm, AlarmType, AlarmEvent, Department, User, Station, 
    ReceiverGroupStation, AlarmStatus, UserRole
)
from app.schemas import AlarmCreate, AlarmOut, AlarmEventOut
from app.core.websocket_manager import manager
from app.core.n8n_client import send_n8n_alarm_notification
from app.api.deps import get_current_user, get_current_operator_or_admin

router = APIRouter(prefix="/alarms", tags=["Alarms"])

@router.get("", response_model=List[AlarmOut])
async def list_alarms(
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
            selectinload(Alarm.source_department),
            selectinload(Alarm.created_by_user),
            selectinload(Alarm.events)
        )
        .order_by(desc(Alarm.created_at))
        .offset(offset)
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(Alarm.status == status_filter.upper())
    
    res = await db.execute(stmt)
    return [AlarmOut.model_validate(a) for a in res.scalars().all()]

@router.get("/{alarm_id}", response_model=AlarmOut)
async def get_alarm(alarm_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
            selectinload(Alarm.source_department),
            selectinload(Alarm.created_by_user),
            selectinload(Alarm.events)
        )
        .where(Alarm.id == alarm_id)
    )
    res = await db.execute(stmt)
    alarm = res.scalar_one_or_none()
    if not alarm:
        raise HTTPException(status_code=404, detail="Không tìm thấy báo động")
    return AlarmOut.model_validate(alarm)

@router.post("", response_model=AlarmOut, status_code=status.HTTP_201_CREATED)
async def create_alarm(
    alarm_in: AlarmCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_operator_or_admin)
):
    """
    Kích hoạt báo động khẩn cấp.
    - Tạo bản ghi Alarm trong DB
    - Tính toán Server Sequence
    - Xác định Receiver Group để gửi WebSocket tới đúng trạm nhận
    - Đẩy n8n webhook ở background (không chặn còi báo động)
    """
    # 1. Idempotency check (within 60s / duplicate submissions)
    if alarm_in.idempotency_key:
        stmt = (
            select(Alarm)
            .options(
                selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
                selectinload(Alarm.source_department),
                selectinload(Alarm.created_by_user),
                selectinload(Alarm.events)
            )
            .where(Alarm.idempotency_key == alarm_in.idempotency_key)
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            return AlarmOut.model_validate(existing)

    # 2. Validate Alarm Type
    alarm_type = await db.get(AlarmType, alarm_in.alarm_type_id)
    if not alarm_type or not alarm_type.enabled:
        raise HTTPException(status_code=400, detail="Loại báo động không tồn tại hoặc đã bị khóa")

    # 3. Department authorization check
    if current_user.role != UserRole.ADMIN.value:
        if alarm_type.allowed_department_ids and len(alarm_type.allowed_department_ids) > 0:
            if not current_user.department_id or current_user.department_id not in alarm_type.allowed_department_ids:
                raise HTTPException(status_code=403, detail="Khoa/phòng của bạn không có quyền phát loại báo động này")

    # 4. Get department info
    dept_id = alarm_in.source_department_id or current_user.department_id
    dept_name = "Toàn viện"
    if dept_id:
        dept = await db.get(Department, dept_id)
        if dept:
            dept_name = dept.name

    # 5. Calculate sequence number
    seq_stmt = select(func.coalesce(func.max(Alarm.server_sequence), 0))
    current_seq = (await db.execute(seq_stmt)).scalar() or 0
    new_seq = current_seq + 1

    now = datetime.now(timezone.utc)

    # 6. Create Alarm
    alarm = Alarm(
        alarm_type_id=alarm_type.id,
        created_by_user_id=current_user.id,
        source_department_id=dept_id,
        source_location=alarm_in.source_location or dept_name,
        note=alarm_in.note or "",
        status=AlarmStatus.ACTIVE.value,
        server_sequence=new_seq,
        idempotency_key=alarm_in.idempotency_key,
        created_at=now,
        activated_at=now
    )
    db.add(alarm)
    await db.commit()
    await db.refresh(alarm)

    # 5. Determine target stations from Receiver Group
    target_station_codes = None
    if alarm_type.receiver_group_id:
        st_stmt = (
            select(Station.station_code)
            .join(ReceiverGroupStation, Station.id == ReceiverGroupStation.station_id)
            .where(
                ReceiverGroupStation.receiver_group_id == alarm_type.receiver_group_id,
                Station.enabled == True
            )
        )
        target_station_codes = (await db.execute(st_stmt)).scalars().all()
        target_station_codes = list(target_station_codes)

    # 6. Record CREATED & BROADCAST events
    created_event = AlarmEvent(
        alarm_id=alarm.id,
        event_type="CREATED",
        event_time=now,
        event_metadata={"created_by": current_user.username, "sequence": new_seq},
        created_at=now
    )
    broadcast_event = AlarmEvent(
        alarm_id=alarm.id,
        event_type="BROADCAST",
        event_time=now,
        event_metadata={"target_stations_count": len(target_station_codes) if target_station_codes else "ALL"},
        created_at=now
    )
    db.add_all([created_event, broadcast_event])
    await db.commit()

    # Load complete alarm model for response & broadcast payload
    res_stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
            selectinload(Alarm.source_department),
            selectinload(Alarm.created_by_user),
            selectinload(Alarm.events)
        )
        .where(Alarm.id == alarm.id)
    )
    alarm_full = (await db.execute(res_stmt)).scalar_one()
    alarm_out = AlarmOut.model_validate(alarm_full)

    # 7. Realtime WebSocket Broadcast
    broadcast_payload = {
        "alarm_id": alarm.id,
        "code": alarm_type.code,
        "name": alarm_type.name,
        "department": dept_name,
        "location": alarm_in.source_location or dept_name,
        "note": alarm.note,
        "display_color": alarm_type.display_color,
        "priority": alarm_type.priority,
        "repeat_count": alarm_type.repeat_count,
        "repeat_interval_ms": alarm_type.repeat_interval_ms,
        "audio_sequence": alarm_type.audio_sequence or [],
        "server_sequence": new_seq,
        "created_at": now.isoformat()
    }
    await manager.broadcast_alarm(broadcast_payload, target_station_codes=target_station_codes)

    # 8. Dispatch n8n notification in background
    n8n_payload = {
        "event": "RED_CODE_CREATED",
        "alarm_id": alarm.id,
        "alarm_type": alarm_type.code,
        "alarm_name": alarm_type.name,
        "department": dept_name,
        "location": alarm_in.source_location or dept_name,
        "note": alarm.note,
        "created_at": now.isoformat()
    }
    background_tasks.add_task(send_n8n_alarm_notification, n8n_payload)

    return alarm_out

@router.post("/{alarm_id}/cancel", response_model=AlarmOut)
async def cancel_alarm(
    alarm_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Hủy báo động (chỉ dùng khi phát nhầm).
    """
    alarm = await db.get(Alarm, alarm_id)
    if not alarm:
        raise HTTPException(status_code=404, detail="Không tìm thấy báo động")

    if current_user.role != UserRole.ADMIN.value and alarm.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Chỉ Admin hoặc người tạo mới có quyền hủy báo động này")

    now = datetime.now(timezone.utc)
    alarm.status = AlarmStatus.CANCELLED.value
    alarm.cancelled_at = now

    cancel_event = AlarmEvent(
        alarm_id=alarm.id,
        event_type="CANCELLED",
        event_time=now,
        event_metadata={"cancelled_by": current_user.username},
        created_at=now
    )
    db.add(cancel_event)
    await db.commit()

    # Broadcast cancellation over WebSocket
    await manager.broadcast_alarm({
        "alarm_id": alarm.id,
        "status": AlarmStatus.CANCELLED.value,
        "cancelled_at": now.isoformat()
    })

    res_stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
            selectinload(Alarm.source_department),
            selectinload(Alarm.created_by_user),
            selectinload(Alarm.events)
        )
        .where(Alarm.id == alarm.id)
    )
    alarm_full = (await db.execute(res_stmt)).scalar_one()
    return AlarmOut.model_validate(alarm_full)
