from datetime import datetime, timezone
from sqlalchemy import select, update
from app.models import Alarm, AlarmEvent, Station, AlarmStationState


async def broadcast_terminal_alarm(session, alarm_id, status, timestamp):
    from app.core.websocket_manager import manager
    message = {'type': f'ALARM_{status}', 'event': f'ALARM_{status}',
               'alarm_id': alarm_id, 'status': status, 'timestamp': timestamp.isoformat()}
    await manager.broadcast_to_dashboards(message)
    targets = (await session.execute(select(Station.station_code).join(AlarmStationState).where(
        AlarmStationState.alarm_id == alarm_id))).scalars().all()
    import asyncio
    await asyncio.gather(*(manager.send_to_station(code, message) for code in targets))


async def expire_alarms(session):
    now = datetime.now(timezone.utc)
    alarms = (await session.execute(select(Alarm).where(Alarm.status == 'ACTIVE', Alarm.expires_at <= now).with_for_update())).scalars().all()
    expired = []
    for alarm in alarms:
        result = await session.execute(update(Alarm).where(Alarm.id == alarm.id, Alarm.status == 'ACTIVE').values(status='EXPIRED'))
        if result.rowcount == 1:
            expired.append(alarm.id)
            session.add(AlarmEvent(alarm_id=alarm.id, event_type='EXPIRED', event_time=now, created_at=now))
    if expired:
        await session.commit()
        for alarm_id in expired:
            await broadcast_terminal_alarm(session, alarm_id, 'EXPIRED', now)
    return expired
