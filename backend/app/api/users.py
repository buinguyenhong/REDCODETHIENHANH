from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import User, Department, UserRole
from app.schemas import UserCreate, UserUpdate, UserOut
from app.core.security import hash_password
from app.api.deps import get_current_user, get_current_active_admin

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("", response_model=List[UserOut])
async def list_users(
    department_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(User).options(selectinload(User.department))
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    stmt = stmt.order_by(User.id.asc())
    res = await db.execute(stmt)
    return [UserOut.model_validate(u) for u in res.scalars().all()]

@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(User).where(User.username == user_in.username)
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Tên người dùng đã tồn tại")

    if user_in.department_id:
        dept = await db.get(Department, user_in.department_id)
        if not dept:
            raise HTTPException(status_code=400, detail="Khoa phòng không hợp lệ")

    user = User(
        username=user_in.username,
        password_hash=hash_password(user_in.password),
        display_name=user_in.display_name,
        department_id=user_in.department_id,
        role=user_in.role,
        enabled=user_in.enabled
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    stmt = select(User).options(selectinload(User.department)).where(User.id == user.id)
    user_with_dept = (await db.execute(stmt)).scalar_one()
    return UserOut.model_validate(user_with_dept)

@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")

    if user_in.display_name is not None:
        user.display_name = user_in.display_name
    if user_in.department_id is not None:
        user.department_id = user_in.department_id
    if user_in.role is not None:
        user.role = user_in.role
    if user_in.enabled is not None:
        user.enabled = user_in.enabled
    if user_in.password:
        user.password_hash = hash_password(user_in.password)
    user.updated_at = datetime.now(timezone.utc)

    await db.commit()
    stmt = select(User).options(selectinload(User.department)).where(User.id == user.id)
    user_with_dept = (await db.execute(stmt)).scalar_one()
    return UserOut.model_validate(user_with_dept)

@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Không thể xóa tài khoản Admin đang đăng nhập")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    user.enabled = False
    await db.commit()
    return {"message": "Đã xóa người dùng thành công"}
