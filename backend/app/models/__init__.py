import enum
from datetime import datetime, timezone
from typing import Optional, List, Any
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, 
    Text, JSON, UniqueConstraint, Index, Enum as SAEnum
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app.database import Base

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"

class AlarmStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"

class StationStatus(str, enum.Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"

class StationAlarmStateEnum(str, enum.Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    DISPLAYED = "DISPLAYED"
    AUDIO_STARTED = "AUDIO_STARTED"
    AUDIO_COMPLETED = "AUDIO_COMPLETED"
    DISMISSED = "DISMISSED"
    FAILED = "FAILED"

class OutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"

class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    users: Mapped[List["User"]] = relationship("User", back_populates="department")
    stations: Mapped[List["Station"]] = relationship("Station", back_populates="department")
    alarm_permissions: Mapped[List["DepartmentAlarmPermission"]] = relationship("DepartmentAlarmPermission", back_populates="department", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    department_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("departments.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.OPERATOR.value, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    department: Mapped[Optional["Department"]] = relationship("Department", back_populates="users")
    created_alarms: Mapped[List["Alarm"]] = relationship("Alarm", back_populates="created_by_user")

class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    station_code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    department_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("departments.id"), nullable=True)
    location: Mapped[str] = mapped_column(String(150), default="", nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    device_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    websocket_connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    audio_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    client_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=StationStatus.OFFLINE.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    department: Mapped[Optional["Department"]] = relationship("Department", back_populates="stations")
    receiver_groups: Mapped[List["ReceiverGroup"]] = relationship(
        "ReceiverGroup", 
        secondary="receiver_group_stations", 
        back_populates="stations"
    )
    station_states: Mapped[List["AlarmStationState"]] = relationship("AlarmStationState", back_populates="station", cascade="all, delete-orphan")

class ReceiverGroup(Base):
    __tablename__ = "receiver_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    stations: Mapped[List["Station"]] = relationship(
        "Station", 
        secondary="receiver_group_stations", 
        back_populates="receiver_groups"
    )
    alarm_types: Mapped[List["AlarmType"]] = relationship("AlarmType", back_populates="receiver_group")

class ReceiverGroupStation(Base):
    __tablename__ = "receiver_group_stations"

    receiver_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("receiver_groups.id", ondelete="CASCADE"), primary_key=True
    )
    station_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stations.id", ondelete="CASCADE"), primary_key=True
    )

class AlarmType(Base):
    __tablename__ = "alarm_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    display_color: Mapped[str] = mapped_column(String(20), default="#dc2626", nullable=False)
    receiver_group_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("receiver_groups.id"), nullable=True)
    audio_sequence: Mapped[Optional[Any]] = mapped_column(JSON, default=list)
    allowed_department_ids: Mapped[Optional[Any]] = mapped_column(JSON, default=list) # Kept for backward compatibility
    repeat_count: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    repeat_interval_ms: Mapped[int] = mapped_column(Integer, default=1500, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    receiver_group: Mapped[Optional["ReceiverGroup"]] = relationship("ReceiverGroup", back_populates="alarm_types")
    alarms: Mapped[List["Alarm"]] = relationship("Alarm", back_populates="alarm_type")
    department_permissions: Mapped[List["DepartmentAlarmPermission"]] = relationship("DepartmentAlarmPermission", back_populates="alarm_type", cascade="all, delete-orphan")

class DepartmentAlarmPermission(Base):
    __tablename__ = "department_alarm_permissions"
    __table_args__ = (
        UniqueConstraint("department_id", "alarm_type_id", name="uq_department_alarm_permission"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    department_id: Mapped[int] = mapped_column(Integer, ForeignKey("departments.id", ondelete="CASCADE"), nullable=False, index=True)
    alarm_type_id: Mapped[int] = mapped_column(Integer, ForeignKey("alarm_types.id", ondelete="CASCADE"), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    department: Mapped["Department"] = relationship("Department", back_populates="alarm_permissions")
    alarm_type: Mapped["AlarmType"] = relationship("AlarmType", back_populates="department_permissions")

class Alarm(Base):
    __tablename__ = "alarms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    alarm_type_id: Mapped[int] = mapped_column(Integer, ForeignKey("alarm_types.id"), nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    source_department_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("departments.id"), nullable=True)
    source_location: Mapped[str] = mapped_column(String(150), default="", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=AlarmStatus.ACTIVE.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    server_sequence: Mapped[int] = mapped_column(Integer, index=True, default=0, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)

    alarm_type: Mapped["AlarmType"] = relationship("AlarmType", back_populates="alarms")
    created_by_user: Mapped[Optional["User"]] = relationship("User", back_populates="created_alarms")
    source_department: Mapped[Optional["Department"]] = relationship("Department")
    events: Mapped[List["AlarmEvent"]] = relationship("AlarmEvent", back_populates="alarm", cascade="all, delete-orphan")
    station_states: Mapped[List["AlarmStationState"]] = relationship("AlarmStationState", back_populates="alarm", cascade="all, delete-orphan")

class AlarmStationState(Base):
    __tablename__ = "alarm_station_states"
    __table_args__ = (
        UniqueConstraint("alarm_id", "station_id", name="uq_alarm_station_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    alarm_id: Mapped[int] = mapped_column(Integer, ForeignKey("alarms.id", ondelete="CASCADE"), nullable=False, index=True)
    station_id: Mapped[int] = mapped_column(Integer, ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(30), default=StationAlarmStateEnum.PENDING.value, nullable=False, index=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    displayed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    audio_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    audio_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    alarm: Mapped["Alarm"] = relationship("Alarm", back_populates="station_states")
    station: Mapped["Station"] = relationship("Station", back_populates="station_states")

class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    alarm_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("alarms.id", ondelete="CASCADE"), nullable=True, index=True)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=OutboxStatus.PENDING.value, nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

class AlarmEvent(Base):
    __tablename__ = "alarm_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    alarm_id: Mapped[int] = mapped_column(Integer, ForeignKey("alarms.id", ondelete="CASCADE"), nullable=False)
    station_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("stations.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    event_metadata: Mapped[Optional[Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    alarm: Mapped["Alarm"] = relationship("Alarm", back_populates="events")
    station: Mapped[Optional["Station"]] = relationship("Station")

class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    station_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("stations.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="INFO", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_metadata: Mapped[Optional[Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    station: Mapped[Optional["Station"]] = relationship("Station")

class AudioFile(Base):
    __tablename__ = "audio_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), default="audio/mpeg", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
