import os
import shutil
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import AudioFile, User
from app.schemas import AudioFileOut
from app.config import settings
from app.api.deps import get_current_active_admin

router = APIRouter(prefix="/audio", tags=["Audio"])

@router.get("", response_model=List[AudioFileOut])
async def list_audio_files(db: AsyncSession = Depends(get_db)):
    stmt = select(AudioFile).order_by(AudioFile.id.asc())
    res = await db.execute(stmt)
    return [AudioFileOut.model_validate(a) for a in res.scalars().all()]

@router.post("/upload", response_model=AudioFileOut, status_code=status.HTTP_201_CREATED)
async def upload_audio_file(
    code: str = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(AudioFile).where(AudioFile.code == code)
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Mã file âm thanh đã tồn tại")

    os.makedirs(settings.AUDIO_UPLOAD_DIR, exist_ok=True)
    filename = f"{code}_{file.filename}"
    file_path = os.path.join(settings.AUDIO_UPLOAD_DIR, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Relative web path
    web_path = f"/assets/audio/{filename}"

    audio = AudioFile(
        code=code,
        name=name,
        file_path=web_path,
        mime_type=file.content_type or "audio/mpeg",
        enabled=True
    )
    db.add(audio)
    await db.commit()
    await db.refresh(audio)

    return AudioFileOut.model_validate(audio)

@router.delete("/{audio_id}")
async def delete_audio_file(
    audio_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    audio = await db.get(AudioFile, audio_id)
    if not audio:
        raise HTTPException(status_code=404, detail="Không tìm thấy file âm thanh")

    # Mark disabled or delete record
    audio.enabled = False
    audio.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Đã vô hiệu hóa file âm thanh"}
