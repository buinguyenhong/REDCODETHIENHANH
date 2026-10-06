from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import AlarmType, ReceiverGroup, User, DepartmentAlarmPermission
from app.schemas import AlarmTypeCreate, AlarmTypeUpdate, AlarmTypeOut, DepartmentAlarmPermissionOut, DepartmentAlarmPermissionCreate
from app.api.deps import get_current_user, get_current_active_admin

router = APIRouter(prefix="/alarm-types", tags=["Alarm Types"])

@router.get("", response_model=List[AlarmTypeOut])
async def list_alarm_types(
    enabled_only: bool = False,
    permitted_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(AlarmType).options(selectinload(AlarmType.receiver_group), selectinload(AlarmType.department_permissions))
    if permitted_only and current_user.role != 'ADMIN':
        if current_user.role == 'VIEWER':
            return []
        stmt = stmt.join(DepartmentAlarmPermission).where(DepartmentAlarmPermission.department_id == current_user.department_id, DepartmentAlarmPermission.enabled == True)
    if enabled_only:
        stmt = stmt.where(AlarmType.enabled == True)
    stmt = stmt.order_by(AlarmType.priority.asc(), AlarmType.id.asc())
    res = await db.execute(stmt)
    result = []
    for alarm_type in res.scalars().all():
        output = AlarmTypeOut.model_validate(alarm_type)
        output.allowed_department_ids = [permission.department_id for permission in alarm_type.department_permissions if permission.enabled]
        result.append(output)
    return result

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

    # Synchronize department_alarm_permissions relational records
    from app.models import Department
    department_ids = (await db.execute(select(Department.id))).scalars().all()
    if department_ids:
        for d_id in department_ids:
            db.add(DepartmentAlarmPermission(
                department_id=d_id,
                alarm_type_id=alarm_type.id,
                enabled=d_id in (type_in.allowed_department_ids or [])
            ))
        await db.commit()

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

    # Synchronize relational table department_alarm_permissions
    if type_in.allowed_department_ids is not None:
        await db.execute(
            DepartmentAlarmPermission.__table__.delete().where(
                DepartmentAlarmPermission.alarm_type_id == alarm_type.id
            )
        )
        from app.models import Department
        department_ids = (await db.execute(select(Department.id))).scalars().all()
        for d_id in department_ids:
            db.add(DepartmentAlarmPermission(
                department_id=d_id,
                alarm_type_id=alarm_type.id,
                enabled=d_id in type_in.allowed_department_ids
            ))
        await db.commit()

    stmt = select(AlarmType).options(selectinload(AlarmType.receiver_group)).where(AlarmType.id == alarm_type.id)
    updated = (await db.execute(stmt)).scalar_one()
    return AlarmTypeOut.model_validate(updated)

@router.get("/{type_id}/permissions", response_model=List[DepartmentAlarmPermissionOut])
async def get_alarm_type_permissions(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(DepartmentAlarmPermission).where(DepartmentAlarmPermission.alarm_type_id == type_id)
    res = await db.execute(stmt)
    return [DepartmentAlarmPermissionOut.model_validate(p) for p in res.scalars().all()]

@router.delete("/{type_id}")
async def delete_alarm_type(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    alarm_type = await db.get(AlarmType, type_id)
    if not alarm_type:
        raise HTTPException(status_code=404, detail="Không tìm thấy loại báo động")
    alarm_type.enabled = False
    await db.commit()
    return {"message": "Đã xóa loại báo động"}
