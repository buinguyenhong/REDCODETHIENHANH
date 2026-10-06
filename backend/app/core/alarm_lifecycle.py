from datetime import datetime, timezone
from sqlalchemy import select
from app.models import Alarm, AlarmEvent


async def expire_alarms(session):
    now = datetime.now(timezone.utc)
    alarms = (await session.execute(select(Alarm).where(Alarm.status == 'ACTIVE', Alarm.expires_at <= now).with_for_update())).scalars().all()
    for alarm in alarms:
        alarm.status = 'EXPIRED'
        session.add(AlarmEvent(alarm_id=alarm.id, event_type='EXPIRED', event_time=now, created_at=now))
    if alarms:
        await session.commit()
    return [alarm.id for alarm in alarms]
