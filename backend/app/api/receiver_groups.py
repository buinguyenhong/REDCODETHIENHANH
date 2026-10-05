from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import ReceiverGroup, ReceiverGroupStation, Station, User
from app.schemas import ReceiverGroupCreate, ReceiverGroupUpdate, ReceiverGroupOut
from app.api.deps import get_current_user, get_current_active_admin

router = APIRouter(prefix="/receiver-groups", tags=["Receiver Groups"])

@router.get("", response_model=List[ReceiverGroupOut])
async def list_receiver_groups(
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ReceiverGroup)
    if enabled_only:
        stmt = stmt.where(ReceiverGroup.enabled == True)
    stmt = stmt.order_by(ReceiverGroup.name.asc())
    res = await db.execute(stmt)
    return [ReceiverGroupOut.model_validate(g) for g in res.scalars().all()]

@router.post("", response_model=ReceiverGroupOut, status_code=status.HTTP_201_CREATED)
async def create_receiver_group(
    group_in: ReceiverGroupCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(ReceiverGroup).where(ReceiverGroup.code == group_in.code)
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Mã nhóm nhận đã tồn tại")

    group = ReceiverGroup(
        code=group_in.code,
        name=group_in.name,
        description=group_in.description or "",
        enabled=group_in.enabled
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)

    if group_in.station_ids:
        for s_id in group_in.station_ids:
            db.add(ReceiverGroupStation(receiver_group_id=group.id, station_id=s_id))
        await db.commit()

    return ReceiverGroupOut.model_validate(group)

@router.put("/{group_id}", response_model=ReceiverGroupOut)
async def update_receiver_group(
    group_id: int,
    group_in: ReceiverGroupUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    group = await db.get(ReceiverGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhóm nhận")

    if group_in.name is not None:
        group.name = group_in.name
    if group_in.description is not None:
        group.description = group_in.description
    if group_in.enabled is not None:
        group.enabled = group_in.enabled

    if group_in.station_ids is not None:
        # Replace stations in group
        await db.execute(delete(ReceiverGroupStation).where(ReceiverGroupStation.receiver_group_id == group_id))
        for s_id in group_in.station_ids:
            db.add(ReceiverGroupStation(receiver_group_id=group_id, station_id=s_id))

    group.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(group)
    return ReceiverGroupOut.model_validate(group)

@router.delete("/{group_id}")
async def delete_receiver_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    group = await db.get(ReceiverGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhóm nhận")
    await db.delete(group)
    await db.commit()
    return {"message": "Đã xóa nhóm nhận thành công"}

