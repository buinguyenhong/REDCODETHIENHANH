from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import SystemEvent, Station, Alarm, User
from app.api.deps import get_current_active_admin
from app.core.websocket_manager import manager

router = APIRouter(prefix="/system", tags=["System Management"])

@router.get("/status")
async def get_system_status(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(Station)
    stations = (await db.execute(stmt)).scalars().all()
    
    online_count = sum(1 for s in stations if s.status == "ONLINE")
    offline_count = len(stations) - online_count

    return {
        "core_status": "RUNNING",
        "active_ws_stations": list(manager.active_stations.keys()),
        "active_dashboards_count": len(manager.active_dashboards),
        "total_configured_stations": len(stations),
        "online_stations": online_count,
        "offline_stations": offline_count
    }

@router.get("/events")
async def list_system_events(
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_active_admin)
):
    stmt = select(SystemEvent).order_by(desc(SystemEvent.created_at)).limit(limit)
    if event_type:
        stmt = stmt.where(SystemEvent.event_type == event_type)
    if severity:
        stmt = stmt.where(SystemEvent.severity == severity.upper())

    events = (await db.execute(stmt)).scalars().all()
    return events
