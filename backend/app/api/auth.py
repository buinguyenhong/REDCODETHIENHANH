from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import User, SystemEvent
from app.schemas import LoginRequest, TokenResponse, UserOut
from app.core.security import verify_password, create_access_token
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(User)
        .options(selectinload(User.department))
        .where(User.username == req.username)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        # Audit log failed login
        fail_event = SystemEvent(
            station_id=None,
            event_type="LOGIN_FAILED",
            severity="WARNING",
            message=f"Failed login attempt for username: {req.username}",
            event_metadata={"username": req.username},
            created_at=datetime.now(timezone.utc)
        )
        db.add(fail_event)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không chính xác",
        )

    if not user.enabled or user.role not in ('ADMIN', 'OPERATOR'):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản này đã bị vô hiệu hóa",
        )

    now = datetime.now(timezone.utc)
    user.last_login_at = now
    
    # Audit log successful login
    success_event = SystemEvent(
        station_id=None,
        event_type="LOGIN_SUCCESS",
        severity="INFO",
        message=f"User {user.username} logged in successfully",
        event_metadata={"user_id": user.id, "username": user.username, "role": user.role},
        created_at=now
    )
    db.add(success_event)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": user.username, "role": user.role, "id": user.id})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))

@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    return {"message": "Đã đăng xuất thành công"}

@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = (
        select(User)
        .options(selectinload(User.department))
        .where(User.id == current_user.id)
    )
    res = await db.execute(stmt)
    user = res.scalar_one()
    return UserOut.model_validate(user)
