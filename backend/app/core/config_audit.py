"""Selective configuration before/after audit helpers (excluding secrets)."""
from typing import Any, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AlarmType,
    AudioFile,
    Department,
    ReceiverGroup,
    Station,
    User,
)

SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "device_token",
    "raw_device_token",
    "device_token_hash",
    "secret",
    "access_token",
}
SENSITIVE_SUFFIXES = ("_password", "_token", "_secret", "_hash")


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key).lower()
    return lowered in SENSITIVE_KEYS or lowered.endswith(SENSITIVE_SUFFIXES)


def sanitize_audit_data(value: Any) -> Any:
    """Recursively strip secrets/tokens/password hashes from audit payloads."""
    if isinstance(value, dict):
        return {
            k: sanitize_audit_data(v)
            for k, v in value.items()
            if not _is_sensitive_key(k)
        }
    if isinstance(value, list):
        return [sanitize_audit_data(item) for item in value]
    return value


def parse_config_target(method: str, path: str) -> Optional[Tuple[str, Optional[int]]]:
    """Identify configuration resource and optional entity ID for audit logging."""
    if method not in ("POST", "PUT", "DELETE"):
        return None

    segments = [seg for seg in path.strip("/").split("/") if seg]
    if len(segments) < 2 or segments[0] != "api":
        return None

    resource = segments[1]
    if resource in ("users", "departments", "alarm-types", "receiver-groups"):
        if len(segments) == 2 and method == "POST":
            return (resource, None)
        if len(segments) == 3 and method in ("PUT", "DELETE"):
            try:
                return (resource, int(segments[2]))
            except ValueError:
                return None
        return None

    if resource == "audio":
        if len(segments) == 3 and segments[2] == "upload" and method == "POST":
            return ("audio", None)
        if len(segments) == 3 and method == "DELETE":
            try:
                return ("audio", int(segments[2]))
            except ValueError:
                return None
        return None

    if resource == "stations":
        if len(segments) == 3 and segments[2] == "register" and method == "POST":
            return ("stations", None)
        if len(segments) == 3 and method in ("PUT", "DELETE"):
            try:
                return ("stations", int(segments[2]))
            except ValueError:
                return None
        return None

    return None


async def load_entity_snapshot(
    session: AsyncSession,
    resource: str,
    entity_id: int,
) -> Tuple[Optional[dict], Optional[str]]:
    """Load non-secret entity snapshot + secret hash fingerprint for change detection."""
    if resource == "users":
        user = await session.get(User, entity_id)
        if not user:
            return None, None
        snapshot = {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "department_id": user.department_id,
            "role": user.role,
            "enabled": user.enabled,
        }
        return sanitize_audit_data(snapshot), user.password_hash

    if resource == "departments":
        dept = await session.get(Department, entity_id)
        if not dept:
            return None, None
        snapshot = {
            "id": dept.id,
            "code": dept.code,
            "name": dept.name,
            "enabled": dept.enabled,
        }
        return sanitize_audit_data(snapshot), None

    if resource == "alarm-types":
        stmt = (
            select(AlarmType)
            .options(selectinload(AlarmType.department_permissions))
            .where(AlarmType.id == entity_id)
        )
        alarm_type = (await session.execute(stmt)).scalar_one_or_none()
        if not alarm_type:
            return None, None
        snapshot = {
            "id": alarm_type.id,
            "code": alarm_type.code,
            "name": alarm_type.name,
            "description": alarm_type.description,
            "enabled": alarm_type.enabled,
            "priority": alarm_type.priority,
            "display_color": alarm_type.display_color,
            "receiver_group_id": alarm_type.receiver_group_id,
            "audio_sequence": list(alarm_type.audio_sequence or []),
            "repeat_count": alarm_type.repeat_count,
            "repeat_interval_ms": alarm_type.repeat_interval_ms,
            "validity_seconds": alarm_type.validity_seconds,
            "allowed_department_ids": sorted(alarm_type.allowed_department_ids),
        }
        return sanitize_audit_data(snapshot), None

    if resource == "receiver-groups":
        stmt = (
            select(ReceiverGroup)
            .options(selectinload(ReceiverGroup.stations))
            .where(ReceiverGroup.id == entity_id)
        )
        group = (await session.execute(stmt)).scalar_one_or_none()
        if not group:
            return None, None
        snapshot = {
            "id": group.id,
            "code": group.code,
            "name": group.name,
            "description": group.description,
            "enabled": group.enabled,
            "station_ids": sorted(st.id for st in group.stations if st.enabled),
        }
        return sanitize_audit_data(snapshot), None

    if resource == "audio":
        audio = await session.get(AudioFile, entity_id)
        if not audio:
            return None, None
        snapshot = {
            "id": audio.id,
            "code": audio.code,
            "name": audio.name,
            "file_path": audio.file_path,
            "mime_type": audio.mime_type,
            "enabled": audio.enabled,
        }
        return sanitize_audit_data(snapshot), None

    if resource == "stations":
        stmt = (
            select(Station)
            .options(selectinload(Station.receiver_groups))
            .where(Station.id == entity_id)
        )
        station = (await session.execute(stmt)).scalar_one_or_none()
        if not station:
            return None, None
        snapshot = {
            "id": station.id,
            "station_code": station.station_code,
            "name": station.name,
            "department_id": station.department_id,
            "location": station.location,
            "enabled": station.enabled,
            "receiver_group_ids": sorted(g.id for g in station.receiver_groups),
        }
        return sanitize_audit_data(snapshot), station.device_token_hash

    return None, None

