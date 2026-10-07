"""Server-side, monotonic receiver acknowledgements (never infer playback)."""
from datetime import datetime, timezone
from sqlalchemy import select, update
from app.models import Alarm, AlarmEvent, AlarmStationState


TRANSITIONS = {
    'RECEIVED': ('DELIVERED', 'received_at', {'PENDING'}),
    'DISPLAYED': ('DISPLAYED', 'displayed_at', {'DELIVERED'}),
    'AUDIO_STARTED': ('AUDIO_STARTED', 'audio_started_at', {'DISPLAYED', 'FAILED'}),
    'AUDIO_COMPLETED': ('AUDIO_COMPLETED', 'audio_completed_at', {'AUDIO_STARTED'}),
    'AUDIO_FAILED': ('FAILED', 'failed_at', {'DISPLAYED', 'AUDIO_STARTED'}),
}


async def acknowledge_station_event(session, alarm_id, station_id, event_type, metadata):
    if event_type not in TRANSITIONS or not isinstance(metadata, dict):
        return False
    now = datetime.now(timezone.utc)
    # Same lock order as cancel/expire/dismiss; serializes terminal status vs ACK.
    alarm = (await session.execute(select(Alarm).where(Alarm.id == alarm_id).with_for_update())).scalar_one_or_none()
    if not alarm or alarm.status != 'ACTIVE':
        return False
    expiry = alarm.expires_at
    if expiry and (expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry) <= now:
        return False
    state, timestamp, predecessors = TRANSITIONS[event_type]
    target = (await session.execute(select(AlarmStationState).where(
        AlarmStationState.alarm_id == alarm_id, AlarmStationState.station_id == station_id
    ).with_for_update())).scalar_one_or_none()
    if not target or target.state not in predecessors:
        return False
    values = {'state': state, 'updated_at': now}
    # First successful start time survives an explicit retry after failure.
    if getattr(target, timestamp) is None or event_type == 'AUDIO_FAILED':
        values[timestamp] = now
    if event_type == 'AUDIO_FAILED':
        values['error_message'] = str(metadata.get('error', 'Audio playback error'))[:2000]
    # Compare-and-set protects idempotency even on SQLite (no row locks).
    result = await session.execute(update(AlarmStationState).where(
        AlarmStationState.id == target.id, AlarmStationState.state == target.state
    ).values(**values))
    if result.rowcount != 1:
        return False
    session.add(AlarmEvent(alarm_id=alarm_id, station_id=station_id, event_type=event_type,
                           event_time=now, event_metadata=metadata, created_at=now))
    await session.commit()
    return True
