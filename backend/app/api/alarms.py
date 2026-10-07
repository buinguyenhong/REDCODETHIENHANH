import asyncio
from datetime import datetime, timezone, timedelta
from app.core.alarm_lifecycle import expire_alarms, broadcast_terminal_alarm
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, desc, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models import (
    Alarm, AlarmType, AlarmEvent, Department, User, Station, 
    ReceiverGroupStation, AlarmStatus, UserRole,
    AlarmStationState, StationAlarmStateEnum,
    DepartmentAlarmPermission, NotificationOutbox, OutboxStatus
)
from app.schemas import AlarmCreate, AlarmOut, AlarmEventOut
from app.core.websocket_manager import manager
from app.core.integration_settings import get_integration
from app.api.deps import get_current_user, get_current_operator_or_admin

router = APIRouter(prefix="/alarms", tags=["Alarms"])

class SequenceGenerator:
    _lock = asyncio.Lock()
    _last_seq = None

    @classmethod
    async def get_next(cls, db: AsyncSession, dialect_name: str) -> int:
        if dialect_name == "postgresql":
            seq_res = await db.execute(text("SELECT nextval('alarm_server_sequence')"))
            return int(seq_res.scalar())
        async with cls._lock:
            if cls._last_seq is None:
                seq_stmt = select(func.coalesce(func.max(Alarm.server_sequence), 0))
                cls._last_seq = (await db.execute(seq_stmt)).scalar() or 0
            cls._last_seq += 1
            return cls._last_seq

@router.get("", response_model=List[AlarmOut])
async def list_alarms(
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    await expire_alarms(db)
    stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
            selectinload(Alarm.source_department),
            selectinload(Alarm.created_by_user),
            selectinload(Alarm.events),
            selectinload(Alarm.station_states)
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
async def get_alarm(
    alarm_id: int, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    await expire_alarms(db)
    stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
            selectinload(Alarm.source_department),
            selectinload(Alarm.created_by_user),
            selectinload(Alarm.events),
            selectinload(Alarm.station_states)
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_operator_or_admin)
):
    """
    Kích hoạt báo động khẩn cấp (P0 Core).
    - Ngăn chặn triệt để Operator spoofing source department
    - Enforce Department Alarm Permission (quan hệ quan hệ department_alarm_permissions)
    - Enforce atomic sequence & DB-level unique idempotency
    - Khởi tạo alarm_station_states cho toàn bộ trạm mục tiêu
    - Bền vững n8n notification outbox
    """
    # 1. Idempotency fast check
    dept_id = current_user.department_id if current_user.role == UserRole.OPERATOR.value else (alarm_in.source_department_id or current_user.department_id)
    dept = await db.get(Department, dept_id) if dept_id else None
    dept_name = dept.name if dept else 'Toàn viện'
    location = alarm_in.source_location or dept_name
    note = alarm_in.note or ''

    def same_request(existing):
        return (existing.created_by_user_id == current_user.id and
                existing.alarm_type_id == alarm_in.alarm_type_id and
                existing.source_department_id == dept_id and
                existing.source_location == location and existing.note == note)

    if alarm_in.idempotency_key:
        stmt = (
            select(Alarm)
            .options(
                selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
                selectinload(Alarm.source_department),
                selectinload(Alarm.created_by_user),
                selectinload(Alarm.events),
                selectinload(Alarm.station_states)
            )
            .where(Alarm.idempotency_key == alarm_in.idempotency_key)
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            if not same_request(existing):
                raise HTTPException(status_code=409, detail='Idempotency key đã được sử dụng cho yêu cầu khác')
            return AlarmOut.model_validate(existing)

    # 2. Validate Alarm Type
    alarm_type = await db.get(AlarmType, alarm_in.alarm_type_id)
    if not alarm_type or not alarm_type.enabled:
        raise HTTPException(status_code=400, detail="Loại báo động không tồn tại hoặc đã bị khóa")

    # 3. Department authorization check (Enforce permission rules)
    if current_user.role != UserRole.ADMIN.value:
        perm_stmt = select(DepartmentAlarmPermission).where(
            DepartmentAlarmPermission.alarm_type_id == alarm_type.id,
            DepartmentAlarmPermission.department_id == current_user.department_id
        )
        dept_perm = (await db.execute(perm_stmt)).scalar_one_or_none()
        if dept_perm is not None:
            if not dept_perm.enabled:
                raise HTTPException(status_code=403, detail="Khoa/phòng của bạn không có quyền phát loại báo động này")
        else:
            raise HTTPException(status_code=403, detail="Khoa/phòng của bạn chưa được cấp quyền phát loại báo động này")

    # 4. Anti-spoofing source department
    if current_user.role == UserRole.OPERATOR.value:
        dept_id = current_user.department_id
    else:
        dept_id = alarm_in.source_department_id or current_user.department_id

    dept_name = "Toàn viện"
    if dept_id:
        dept = await db.get(Department, dept_id)
        if dept:
            dept_name = dept.name

    # 5. Atomic sequence generation
    try:
        bind = db.bind or getattr(db, "sync_session", None)
        dialect_name = bind.dialect.name if bind else ""
    except Exception:
        dialect_name = ""

    new_seq = await SequenceGenerator.get_next(db, dialect_name)

    now = datetime.now(timezone.utc)

    # 6. Create Alarm with DB Unique Idempotency protection
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
        , expires_at=now + timedelta(seconds=alarm_type.validity_seconds)
    )
    db.add(alarm)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        if alarm_in.idempotency_key:
            existing_stmt = (
                select(Alarm)
                .options(
                    selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
                    selectinload(Alarm.source_department),
                    selectinload(Alarm.created_by_user),
                    selectinload(Alarm.events),
                    selectinload(Alarm.station_states)
                )
                .where(Alarm.idempotency_key == alarm_in.idempotency_key)
            )
            existing = (await db.execute(existing_stmt)).scalar_one_or_none()
            if existing:
                if not same_request(existing):
                    raise HTTPException(status_code=409, detail='Idempotency key đã được sử dụng cho yêu cầu khác')
                return AlarmOut.model_validate(existing)
        raise HTTPException(status_code=409, detail="Yêu cầu kích hoạt trùng lặp")

    # 7. Determine target stations from Receiver Group and initialize alarm_station_states
    target_station_codes = None
    if alarm_type.receiver_group_id:
        st_stmt = (
            select(Station)
            .join(ReceiverGroupStation, Station.id == ReceiverGroupStation.station_id)
            .where(
                ReceiverGroupStation.receiver_group_id == alarm_type.receiver_group_id,
                Station.enabled == True
            )
        )
    else:
        st_stmt = select(Station).where(Station.enabled == True)

    target_stations = (await db.execute(st_stmt)).scalars().all()
    target_station_codes = [s.station_code for s in target_stations]

    for st in target_stations:
        is_online = st.station_code in manager.active_stations
        initial_state = StationAlarmStateEnum.PENDING.value
        st_state = AlarmStationState(
            alarm_id=alarm.id,
            station_id=st.id,
            state=initial_state,
            received_at=None,
            displayed_at=None,
            created_at=now,
            updated_at=now
        )
        db.add(st_state)

    # 8. Record CREATED & BROADCAST events
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

    # 9. Queue durable n8n notification in outbox table
    n8n_payload = {
        "event": "RED_CODE_CREATED",
        "alarm_id": alarm.id,
        "alarm_type": alarm_type.code,
        "alarm_name": alarm_type.name,
        "department": dept_name,
        "location": alarm_in.source_location or dept_name,
        "note": alarm.note,
        "server_sequence": new_seq,
        "created_at": now.isoformat()
    }
    outbox_item = NotificationOutbox(
        event_type="ALARM_CREATED",
        alarm_id=alarm.id,
        payload=n8n_payload,
        status=OutboxStatus.PENDING.value,
        created_at=now
    )
    integration = await get_integration(db)
    if integration and integration.enabled:
        db.add(outbox_item)
    await db.commit()

    # 10. Realtime WebSocket Broadcast
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
        , "expires_at": alarm.expires_at.isoformat(), "server_time": now.isoformat()
    }
    await manager.broadcast_alarm(broadcast_payload, target_station_codes=target_station_codes)

    # Load complete alarm model for response
    res_stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
            selectinload(Alarm.source_department),
            selectinload(Alarm.created_by_user),
            selectinload(Alarm.events),
            selectinload(Alarm.station_states)
        )
        .where(Alarm.id == alarm.id)
    )
    alarm_full = (await db.execute(res_stmt)).scalar_one()
    return AlarmOut.model_validate(alarm_full)

@router.post("/{alarm_id}/cancel", response_model=AlarmOut)
async def cancel_alarm(
    alarm_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Hủy báo động (chỉ dùng khi phát nhầm).
    Phát sự kiện riêng ALARM_CANCELLED qua WebSocket.
    """
    await expire_alarms(db)
    alarm = (await db.execute(select(Alarm).where(Alarm.id == alarm_id).with_for_update())).scalar_one_or_none()
    if not alarm:
        raise HTTPException(status_code=404, detail="Không tìm thấy báo động")

    if current_user.role != UserRole.ADMIN.value and alarm.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Chỉ Admin hoặc người tạo mới có quyền hủy báo động này")

    now = datetime.now(timezone.utc)
    if alarm.status == AlarmStatus.CANCELLED.value:
        return await get_alarm(alarm_id, db, current_user)
    if alarm.status != AlarmStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail='Báo động đã hết hiệu lực, không thể hủy')
    changed = await db.execute(update(Alarm).where(Alarm.id == alarm_id, Alarm.status == 'ACTIVE').values(status='CANCELLED', cancelled_at=now))
    if changed.rowcount != 1:
        raise HTTPException(status_code=409, detail='Trạng thái báo động đã thay đổi')

    cancel_event = AlarmEvent(
        alarm_id=alarm.id,
        event_type="ALARM_CANCELLED",
        event_time=now,
        event_metadata={"cancelled_by": current_user.username},
        created_at=now
    )
    db.add(cancel_event)

    await db.commit()

    # Broadcast distinct cancellation event over WebSocket
    await broadcast_terminal_alarm(db, alarm.id, 'CANCELLED', now)

    res_stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
            selectinload(Alarm.source_department),
            selectinload(Alarm.created_by_user),
            selectinload(Alarm.events),
            selectinload(Alarm.station_states)
        )
        .where(Alarm.id == alarm.id)
    )
    alarm_full = (await db.execute(res_stmt)).scalar_one()
    return AlarmOut.model_validate(alarm_full)
