from typing import List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import Department, User
from app.schemas import DepartmentCreate, DepartmentUpdate, DepartmentOut
from app.api.deps import get_current_user, get_current_active_admin

router = APIRouter(prefix="/departments", tags=["Departments"])

@router.get("", response_model=List[DepartmentOut])
async def list_departments(
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Department)
    if enabled_only:
        stmt = stmt.where(Department.enabled == True)
    stmt = stmt.order_by(Department.name.asc())
    res = await db.execute(stmt)
    return [DepartmentOut.model_validate(d) for d in res.scalars().all()]

@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(
    dept_in: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(Department).where(Department.code == dept_in.code)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Mã khoa/phòng đã tồn tại")

    dept = Department(
        code=dept_in.code,
        name=dept_in.name,
        enabled=dept_in.enabled
    )
    db.add(dept)
    await db.commit()
    await db.refresh(dept)
    return DepartmentOut.model_validate(dept)

@router.put("/{dept_id}", response_model=DepartmentOut)
async def update_department(
    dept_id: int,
    dept_in: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    dept = await db.get(Department, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Không tìm thấy khoa/phòng")

    if dept_in.name is not None:
        dept.name = dept_in.name
    if dept_in.enabled is not None:
        dept.enabled = dept_in.enabled
    dept.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(dept)
    return DepartmentOut.model_validate(dept)

@router.delete("/{dept_id}")
async def delete_department(
    dept_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    dept = await db.get(Department, dept_id)
    if not dept:
        raise HTTPException(status_code=404, detail="Không tìm thấy khoa/phòng")
    dept.enabled = False
    await db.commit()
    return {"message": "Đã xóa khoa/phòng thành công"}
