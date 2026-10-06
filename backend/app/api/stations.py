import secrets
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models import (
    Station, ReceiverGroup, ReceiverGroupStation, 
    Alarm, AlarmType, AlarmEvent, AlarmStatus, StationStatus, SystemEvent, User,
    AlarmStationState, StationAlarmStateEnum
)
from app.schemas import StationRegister, StationHeartbeat, StationDismiss, StationOut
from app.core.security import hash_device_token
from app.core.websocket_manager import manager
from app.api.deps import get_current_user, get_current_active_admin

router = APIRouter(prefix="/stations", tags=["Stations"])

@router.post('/activate', response_model=StationOut)
async def activate_station(credentials: StationHeartbeat, db: AsyncSession = Depends(get_db)):
    station = (await db.execute(select(Station).options(selectinload(Station.department), selectinload(Station.receiver_groups)).where(Station.station_code == credentials.station_code))).scalar_one_or_none()
    if not station or not station.enabled or hash_device_token(credentials.device_token) != station.device_token_hash:
        raise HTTPException(status_code=401, detail='Thông tin kích hoạt trạm không hợp lệ')
    return StationOut.model_validate(station)

@router.get("", response_model=List[StationOut])
async def list_stations(
    status_filter: Optional[str] = None,
    department_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List stations - requires authenticated hospital staff.
    """
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
async def get_station(
    station_id: int, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get station detail - requires authenticated hospital staff.
    """
    stmt = (
        select(Station)
        .options(selectinload(Station.department), selectinload(Station.receiver_groups))
        .where(Station.id == station_id)
    )
    station = (await db.execute(stmt)).scalar_one_or_none()
    if not station:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm nhận")
    return StationOut.model_validate(station)

@router.post("/register", response_model=StationOut, status_code=status.HTTP_201_CREATED)
async def register_station(
    reg: StationRegister, 
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    """
    Registers or provisions a receiver station (ADMIN ONLY).
    Generates cryptographically secure random token if not provided.
    Returns raw_device_token once upon creation/rotation.
    """
    raw_token = reg.device_token.strip() if reg.device_token and reg.device_token.strip() else secrets.token_urlsafe(32)
    token_hash = hash_device_token(raw_token)

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
        await db.execute(
            ReceiverGroupStation.__table__.delete().where(ReceiverGroupStation.station_id == station.id)
        )
        for gid in reg.receiver_group_ids:
            db.add(ReceiverGroupStation(receiver_group_id=gid, station_id=station.id))
        await db.commit()

    # Log system event
    db.add(SystemEvent(
        station_id=station.id,
        event_type="STATION_REGISTERED",
        severity="INFO",
        message=f"Station {station.station_code} registered/provisioned by admin {admin.username}",
        event_metadata={"admin": admin.username, "station_code": station.station_code},
        created_at=datetime.now(timezone.utc)
    ))
    await db.commit()

    stmt = (
        select(Station)
        .options(selectinload(Station.department), selectinload(Station.receiver_groups))
        .where(Station.id == station.id)
    )
    res = await db.execute(stmt)
    out = StationOut.model_validate(res.scalar_one())
    out.raw_device_token = raw_token
    return out

@router.post("/heartbeat")
async def station_heartbeat(
    hb: StationHeartbeat,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Heartbeat sent by stations every 5 seconds.
    Validates station token and updates readiness.
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

@router.get("/{station_code}/active-alarms")
async def get_station_active_alarms(
    station_code: str,
    x_station_token: Optional[str] = Header(None, alias="X-Station-Token"),
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Sync missed/ongoing active alarms for a station upon reconnect or kiosk load.
    AUTHENTICATED: Must supply valid device token for this specific station.
    Returns undismissed active alarms in FIFO order (by server_sequence).
    """
    stmt = (
        select(Station)
        .options(selectinload(Station.receiver_groups))
        .where(Station.station_code == station_code)
    )
    station = (await db.execute(stmt)).scalar_one_or_none()
    if not station or not station.enabled:
        raise HTTPException(status_code=404, detail="Trạm không tồn tại hoặc đã bị khóa")

    # Validate station credential
    device_token = x_station_token or token
    if not device_token or hash_device_token(device_token) != station.device_token_hash:
        raise HTTPException(status_code=401, detail="Xác thực trạm không hợp lệ")

    target_ids = set((await db.execute(select(AlarmStationState.alarm_id).where(AlarmStationState.station_id == station.id))).scalars().all())

    # Query all ACTIVE alarms
    alarm_stmt = (
        select(Alarm)
        .options(
            selectinload(Alarm.alarm_type).selectinload(AlarmType.receiver_group),
            selectinload(Alarm.source_department)
        )
        .where(Alarm.status == AlarmStatus.ACTIVE.value)
        .order_by(Alarm.server_sequence.asc())
    )
    all_active = (await db.execute(alarm_stmt)).scalars().all()

    # Find alarms that this station has already dismissed in alarm_station_states or alarm_events
    dismissed_stmt = select(AlarmStationState.alarm_id).where(
        AlarmStationState.station_id == station.id,
        AlarmStationState.state == StationAlarmStateEnum.DISMISSED.value
    )
    dismissed_ids = set((await db.execute(dismissed_stmt)).scalars().all())

    now = datetime.now(timezone.utc)
    result = []
    for a in all_active:
        if a.id in dismissed_ids:
            continue
        # Check receiver group mapping: None means all stations, else must match
        if a.id not in target_ids:
            continue

        # Update or create AlarmStationState to DELIVERED/DISPLAYED
        st_state_stmt = select(AlarmStationState).where(
            AlarmStationState.alarm_id == a.id,
            AlarmStationState.station_id == station.id
        )
        st_state = (await db.execute(st_state_stmt)).scalar_one_or_none()
        if st_state:
            if st_state.state == StationAlarmStateEnum.PENDING.value:
                st_state.state = StationAlarmStateEnum.PENDING.value
                st_state.updated_at = now
        else:
            db.add(AlarmStationState(
                alarm_id=a.id,
                station_id=station.id,
                state=StationAlarmStateEnum.DISPLAYED.value,
                received_at=now,
                displayed_at=now,
                created_at=now,
                updated_at=now
            ))

        dept_name = a.source_department.name if a.source_department else "Toàn viện"
        result.append({
            "alarm_id": a.id,
            "code": a.alarm_type.code if a.alarm_type else "",
            "name": a.alarm_type.name if a.alarm_type else "",
            "department": dept_name,
            "location": a.source_location or dept_name,
            "note": a.note,
            "display_color": a.alarm_type.display_color if a.alarm_type else "#dc2626",
            "priority": a.alarm_type.priority if a.alarm_type else 1,
            "repeat_count": a.alarm_type.repeat_count if a.alarm_type else 3,
            "repeat_interval_ms": a.alarm_type.repeat_interval_ms if a.alarm_type else 3000,
            "audio_sequence": a.alarm_type.audio_sequence or [] if a.alarm_type else [],
            "server_sequence": a.server_sequence,
            "created_at": a.created_at.isoformat() if a.created_at else ""
        })

    await db.commit()
    return result

@router.post("/dismiss")
async def dismiss_station_alarm(
    dismiss_data: StationDismiss,
    db: AsyncSession = Depends(get_db)
):
    """
    LOCAL DISMISS:
    Only acknowledges and stops audio/visual for the specified station.
    AUTHENTICATION MANDATORY: validates station_code and device_token.
    RECEIVER GROUP VALIDATION: verifies station belongs to the alarm's receiver group.
    DOES NOT CANCEL OR COMPLETE THE GLOBAL ALARM (global alarm remains ACTIVE).
    """
    stmt = (
        select(Station)
        .options(selectinload(Station.receiver_groups))
        .where(Station.station_code == dismiss_data.station_code)
    )
    station = (await db.execute(stmt)).scalar_one_or_none()
    if not station or not station.enabled:
        raise HTTPException(status_code=404, detail="Trạm không tồn tại hoặc đã bị khóa")

    # 1. Validate station token credential
    expected_hash = hash_device_token(dismiss_data.device_token)
    if station.device_token_hash != expected_hash:
        raise HTTPException(status_code=401, detail="Token trạm không hợp lệ")

    # 2. Check alarm exists
    alarm_stmt = (
        select(Alarm)
        .options(selectinload(Alarm.alarm_type))
        .where(Alarm.id == dismiss_data.alarm_id)
    )
    alarm = (await db.execute(alarm_stmt)).scalar_one_or_none()
    if not alarm:
        raise HTTPException(status_code=404, detail="Báo động không tồn tại")

    # 3. Verify station belongs to the alarm's target receiver group
    target = (await db.execute(select(AlarmStationState.id).where(AlarmStationState.alarm_id == alarm.id, AlarmStationState.station_id == station.id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=403, detail='Trạm không thuộc nhóm nhận của báo động này')

    now = datetime.now(timezone.utc)

    # 4. Update AlarmStationState to DISMISSED
    st_state_stmt = select(AlarmStationState).where(
        AlarmStationState.alarm_id == alarm.id,
        AlarmStationState.station_id == station.id
    )
    st_state = (await db.execute(st_state_stmt)).scalar_one_or_none()
    if st_state:
        if st_state.state == StationAlarmStateEnum.DISMISSED.value:
            return {'status': 'dismissed_locally', 'alarm_id': alarm.id, 'station_code': station.station_code}
        st_state.state = StationAlarmStateEnum.DISMISSED.value
        st_state.dismissed_at = now
        st_state.updated_at = now
    else:
        st_state = AlarmStationState(
            alarm_id=alarm.id,
            station_id=station.id,
            state=StationAlarmStateEnum.DISMISSED.value,
            dismissed_at=now,
            created_at=now,
            updated_at=now
        )
        db.add(st_state)

    # 5. Record dismissal event for audit trail
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

    # 6. Notify dashboards that this station dismissed the alarm locally
    await manager.broadcast_to_dashboards({
        "type": "ALARM_ACKNOWLEDGED",
        "alarm_id": alarm.id,
        "station_id": station.id,
        "station_code": station.station_code,
        "station_name": station.name,
        "timestamp": now.isoformat()
    })

    return {
        "status": "dismissed_locally",
        "alarm_id": alarm.id,
        "station_code": station.station_code
    }

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
    station.enabled = reg.enabled
    raw_token = None
    if reg.device_token and reg.device_token.strip():
        raw_token = reg.device_token.strip()
        station.device_token_hash = hash_device_token(raw_token)
    station.updated_at = datetime.now(timezone.utc)

    if reg.receiver_group_ids is not None:
        await db.execute(
            ReceiverGroupStation.__table__.delete().where(ReceiverGroupStation.station_id == station.id)
        )
        for gid in reg.receiver_group_ids:
            db.add(ReceiverGroupStation(receiver_group_id=gid, station_id=station.id))

    await db.commit()
    if not station.enabled or raw_token:
        ws = manager.active_stations.get(station.station_code)
        if ws:
            await ws.close(code=1008)
    stmt = (
        select(Station)
        .options(selectinload(Station.department), selectinload(Station.receiver_groups))
        .where(Station.id == station.id)
    )
    res = await db.execute(stmt)
    out = StationOut.model_validate(res.scalar_one())
    out.raw_device_token = raw_token
    return out

@router.delete("/{station_id}")
async def delete_station(
    station_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    station = await db.get(Station, station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Không tìm thấy trạm nhận")
    station.enabled = False
    ws = manager.active_stations.get(station.station_code)
    if ws:
        await ws.close(code=1008)
    await db.commit()
    return {"message": "Đã xóa trạm nhận thành công"}
