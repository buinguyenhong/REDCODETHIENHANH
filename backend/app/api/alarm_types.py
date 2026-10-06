from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import AlarmType, ReceiverGroup, User
from app.schemas import AlarmTypeCreate, AlarmTypeUpdate, AlarmTypeOut
from app.api.deps import get_current_user, get_current_active_admin

router = APIRouter(prefix="/alarm-types", tags=["Alarm Types"])

@router.get("", response_model=List[AlarmTypeOut])
async def list_alarm_types(
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(AlarmType).options(selectinload(AlarmType.receiver_group))
    if enabled_only:
        stmt = stmt.where(AlarmType.enabled == True)
    stmt = stmt.order_by(AlarmType.priority.asc(), AlarmType.id.asc())
    res = await db.execute(stmt)
    return [AlarmTypeOut.model_validate(at) for at in res.scalars().all()]

@router.post("", response_model=AlarmTypeOut, status_code=status.HTTP_201_CREATED)
async def create_alarm_type(
    type_in: AlarmTypeCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(AlarmType).where(AlarmType.code == type_in.code)
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Mã loại báo động đã tồn tại")

    if type_in.receiver_group_id:
        rg = await db.get(ReceiverGroup, type_in.receiver_group_id)
        if not rg:
            raise HTTPException(status_code=400, detail="Nhóm nhận không hợp lệ")

    alarm_type = AlarmType(
        code=type_in.code,
        name=type_in.name,
        description=type_in.description or "",
        enabled=type_in.enabled,
        priority=type_in.priority,
        display_color=type_in.display_color,
        receiver_group_id=type_in.receiver_group_id,
        audio_sequence=type_in.audio_sequence or [],
        allowed_department_ids=type_in.allowed_department_ids or [],
        repeat_count=type_in.repeat_count,
        repeat_interval_ms=type_in.repeat_interval_ms
    )
    db.add(alarm_type)
    await db.commit()
    await db.refresh(alarm_type)

    stmt = select(AlarmType).options(selectinload(AlarmType.receiver_group)).where(AlarmType.id == alarm_type.id)
    created = (await db.execute(stmt)).scalar_one()
    return AlarmTypeOut.model_validate(created)

@router.put("/{type_id}", response_model=AlarmTypeOut)
async def update_alarm_type(
    type_id: int,
    type_in: AlarmTypeUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    alarm_type = await db.get(AlarmType, type_id)
    if not alarm_type:
        raise HTTPException(status_code=404, detail="Không tìm thấy loại báo động")

    for field, value in type_in.model_dump(exclude_unset=True).items():
        setattr(alarm_type, field, value)

    alarm_type.updated_at = datetime.now(timezone.utc)
    await db.commit()

    stmt = select(AlarmType).options(selectinload(AlarmType.receiver_group)).where(AlarmType.id == alarm_type.id)
    updated = (await db.execute(stmt)).scalar_one()
    return AlarmTypeOut.model_validate(updated)

@router.delete("/{type_id}")
async def delete_alarm_type(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    alarm_type = await db.get(AlarmType, type_id)
    if not alarm_type:
        raise HTTPException(status_code=404, detail="Không tìm thấy loại báo động")
    await db.delete(alarm_type)
    await db.commit()
    return {"message": "Đã xóa loại báo động"}

