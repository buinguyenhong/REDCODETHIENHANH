from fastapi import APIRouter, Depends
from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
from app.database import get_db
from app.config import settings
from app.models import Station, StationStatus
from app.core.websocket_manager import manager
from app.schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["Health Check"])

@router.get("", response_model=HealthResponse)
async def get_health(db: AsyncSession = Depends(get_db)):
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    ws_status = "ok"

    n8n_status = "disabled"
    if settings.N8N_WEBHOOK_URL and settings.N8N_WEBHOOK_URL.strip():
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                res = await client.get(settings.N8N_WEBHOOK_URL.split("/webhook")[0] + "/healthz")
                n8n_status = "ok" if res.is_success else "degraded"
        except Exception:
            n8n_status = "degraded"

    # Count stations
    total_stations_stmt = select(func.count(Station.id))
    total_stations = (await db.execute(total_stations_stmt)).scalar() or 0
    active_stations = len(manager.active_stations)

    overall_status = "ok" if db_status == "ok" else "error"

    return HealthResponse(
        status=overall_status,
        database=db_status,
        websocket=ws_status,
        n8n=n8n_status,
        active_stations=active_stations,
        total_stations=total_stations
    )
