from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.departments import router as departments_router
from app.api.users import router as users_router
from app.api.stations import router as stations_router
from app.api.alarm_types import router as alarm_types_router
from app.api.receiver_groups import router as receiver_groups_router
from app.api.alarms import router as alarms_router
from app.api.reports import router as reports_router
from app.api.audio import router as audio_router
from app.api.system import router as system_router
from app.api.health import router as health_router
from app.api.settings import router as settings_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(departments_router)
api_router.include_router(users_router)
api_router.include_router(stations_router)
api_router.include_router(alarm_types_router)
api_router.include_router(receiver_groups_router)
api_router.include_router(alarms_router)
api_router.include_router(reports_router)
api_router.include_router(audio_router)
api_router.include_router(system_router)
api_router.include_router(health_router)
api_router.include_router(settings_router)
