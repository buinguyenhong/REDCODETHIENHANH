from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import (
    Station, ReceiverGroup, ReceiverGroupStation, 
    Alarm, AlarmEvent, AlarmStatus, StationStatus, SystemEvent, User
)
from app.schemas import StationRegister, StationHeartbeat, StationDismiss, StationOut
from app.core.security import hash_device_token
from app.core.websocket_manager import manager
from app.api.deps import get_current_user, get_current_active_admin

router = APIRouter(prefix="/stations", tags=["Stations"])

@router.get("", response_model=List[StationOut])
async def list_stations(
    status_filter: Optional[str] = None,
    department_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Station)
        .options(selectinload(Station.department), selectinload(Station.receiver_groups))
    )
    if status_filter:
        stmt = stmt.where(Station.status == status_filter.upper())
    if department_id:
        stmt = stmt.where(Station.department_id == department_id)
    stmt = stmt.order_by(Station.station_code.asc())
    res = await db.execute(stmt)
    return [StationOut.model_validate(s) for s in res.scalars().all()]

@router.get("/{station_id}", response_model=StationOut)
async def get_station(station_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Station)
        .options(selectinload(Station.department), selectinload(Station.receiver_groups))
        .where(Station.id == station_id)
    )
    station = (await db.execute(stmt)).scalar_one_or_none()
    if not station:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm nhận")
    return StationOut.model_validate(station)

@router.post("/register", response_model=StationOut)
async def register_station(
    reg: StationRegister, 
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Registers or updates an existing receiver station (kiosk / PC station).
    Stores device_token_hash safely.
    """
    token_hash = hash_device_token(reg.device_token)
    stmt = select(Station).where(Station.station_code == reg.station_code)
    station = (await db.execute(stmt)).scalar_one_or_none()

    client_ip = request.client.host if request.client else None

    if station:
        # Update existing station
        station.name = reg.name
        station.department_id = reg.department_id
        station.location = reg.location
        station.device_token_hash = token_hash
        station.ip_address = client_ip
        station.updated_at = datetime.now(timezone.utc)
    else:
        # Create new station
        station = Station(
            station_code=reg.station_code,
            name=reg.name,
            department_id=reg.department_id,
            location=reg.location,
            ip_address=client_ip,
            device_token_hash=token_hash,
            enabled=True,
            status=StationStatus.OFFLINE.value
        )
        db.add(station)

    await db.commit()
    await db.refresh(station)

    if reg.receiver_group_ids:
        for gid in reg.receiver_group_ids:
            exists = (await db.execute(
                select(ReceiverGroupStation).where(
                    ReceiverGroupStation.receiver_group_id == gid,
                    ReceiverGroupStation.station_id == station.id
                )
            )).scalar_one_or_none()
            if not exists:
                db.add(ReceiverGroupStation(receiver_group_id=gid, station_id=station.id))
        await db.commit()

    stmt = (
        select(Station)
        .options(selectinload(Station.department), selectinload(Station.receiver_groups))
        .where(Station.id == station.id)
    )
    res = await db.execute(stmt)
    return StationOut.model_validate(res.scalar_one())

@router.post("/heartbeat")
async def station_heartbeat(
    hb: StationHeartbeat,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Heartbeat sent by stations every 5 seconds.
    Validates token and updates readiness.
    """
    stmt = select(Station).where(Station.station_code == hb.station_code)
    station = (await db.execute(stmt)).scalar_one_or_none()
    if not station or not station.enabled:
        raise HTTPException(status_code=404, detail="Trạm không tồn tại hoặc bị khóa")

    expected_hash = hash_device_token(hb.device_token)
    if station.device_token_hash != expected_hash:
        raise HTTPException(status_code=401, detail="Token trạm không hợp lệ")

    now = datetime.now(timezone.utc)
    client_ip = hb.ip_address or (request.client.host if request.client else station.ip_address)
    
    station.last_seen_at = now
    station.websocket_connected = True
    station.audio_ready = hb.audio_ready
    station.client_ready = hb.client_ready
    station.status = StationStatus.ONLINE.value
    station.ip_address = client_ip
    station.updated_at = now

    await db.commit()

    # Inform WebSocket manager
    await manager.update_heartbeat(
        station_code=hb.station_code,
        audio_ready=hb.audio_ready,
        client_ready=hb.client_ready
    )

    return {"status": "ok", "timestamp": now.isoformat()}

@router.post("/dismiss")
async def dismiss_station_alarm(
    dismiss_data: StationDismiss,
    db: AsyncSession = Depends(get_db)
):
    """
    LOCAL DISMISS:
    Only acknowledges the alarm for the specified station.
    The alarm continues on other stations until dismissed locally.
    """
    stmt = select(Station).where(Station.station_code == dismiss_data.station_code)
    station = (await db.execute(stmt)).scalar_one_or_none()
    if not station:
        raise HTTPException(status_code=404, detail="Trạm không tồn tại")

    alarm = await db.get(Alarm, dismiss_data.alarm_id)
    if not alarm:
        raise HTTPException(status_code=404, detail="Báo động không tồn tại")

    now = datetime.now(timezone.utc)

    # Record dismissal event for this station
    event = AlarmEvent(
        alarm_id=alarm.id,
        station_id=station.id,
        event_type="DISMISSED",
        event_time=now,
        event_metadata={
            "station_code": station.station_code,
            "station_name": station.name,
            "note": dismiss_data.note
        },
        created_at=now
    )
    db.add(event)
    await db.commit()

    # Notify dashboards that this station dismissed the alarm
    await manager.broadcast_to_dashboards({
        "type": "ALARM_ACKNOWLEDGED",
        "alarm_id": alarm.id,
        "station_id": station.id,
        "station_code": station.station_code,
        "station_name": station.name,
        "timestamp": now.isoformat()
    })

    return {"status": "dismissed_locally", "alarm_id": alarm.id, "station_code": station.station_code}

@router.post("/{station_id}/audio-test")
async def test_station_audio(
    station_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    """
    Sends an audio test signal to a specific station via WebSocket.
    """
    station = await db.get(Station, station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm nhận")

    sent = await manager.send_to_station(station.station_code, {
        "type": "AUDIO_TEST",
        "station_code": station.station_code,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    if not sent:
        raise HTTPException(status_code=503, detail="Trạm hiện không có kết nối WebSocket trực tiếp")

    return {"status": "test_signal_sent", "station_code": station.station_code}

@router.put("/{station_id}", response_model=StationOut)
async def update_station(
    station_id: int,
    reg: StationRegister,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    station = await db.get(Station, station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm nhận")

    station.station_code = reg.station_code
    station.name = reg.name
    station.department_id = reg.department_id
    station.location = reg.location
    if reg.device_token and reg.device_token.strip():
        station.device_token_hash = hash_device_token(reg.device_token.strip())
    station.updated_at = datetime.now(timezone.utc)

    if reg.receiver_group_ids is not None:
        await db.execute(
            ReceiverGroupStation.__table__.delete().where(ReceiverGroupStation.station_id == station.id)
        )
        for gid in reg.receiver_group_ids:
            db.add(ReceiverGroupStation(receiver_group_id=gid, station_id=station.id))

    await db.commit()
    stmt = (
        select(Station)
        .options(selectinload(Station.department), selectinload(Station.receiver_groups))
        .where(Station.id == station.id)
    )
    res = await db.execute(stmt)
    return StationOut.model_validate(res.scalar_one())

@router.delete("/{station_id}")
async def delete_station(
    station_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    station = await db.get(Station, station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm nhận")
    await db.delete(station)
    await db.commit()
    return {"message": "Đã xóa trạm nhận thành công"}

