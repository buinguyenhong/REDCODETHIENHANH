from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator

# --- Auth ---
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"

# --- Departments ---
class DepartmentBase(BaseModel):
    code: str
    name: str
    enabled: bool = True

class DepartmentCreate(DepartmentBase):
    pass

class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None

class DepartmentOut(DepartmentBase):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- Users ---
class UserBase(BaseModel):
    username: str
    display_name: str
    department_id: Optional[int] = None
    role: Literal['ADMIN', 'OPERATOR'] = "OPERATOR"
    enabled: bool = True

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    department_id: Optional[int] = None
    role: Optional[Literal['ADMIN', 'OPERATOR']] = None
    enabled: Optional[bool] = None
    password: Optional[str] = None

class UserOut(UserBase):
    id: int
    last_login_at: Optional[datetime] = None
    created_at: datetime
    department: Optional[DepartmentOut] = None
    model_config = ConfigDict(from_attributes=True)

# --- Stations ---
class StationRegister(BaseModel):
    station_code: str
    name: str
    department_id: Optional[int] = None
    location: str = ""
    device_token: Optional[str] = None # Generated securely by server if omitted
    receiver_group_ids: Optional[List[int]] = None
    enabled: bool = True

class StationHeartbeat(BaseModel):
    station_code: str
    device_token: str
    audio_ready: bool = False
    client_ready: bool = True
    ip_address: Optional[str] = None

class StationDismiss(BaseModel):
    alarm_id: int
    station_code: str
    device_token: str # Strictly required for authentication
    note: Optional[str] = ""

class StationOut(BaseModel):
    id: int
    station_code: str
    name: str
    department_id: Optional[int] = None
    location: str
    ip_address: Optional[str] = None
    enabled: bool
    last_seen_at: Optional[datetime] = None
    websocket_connected: bool
    audio_ready: bool
    client_ready: bool
    status: str
    department: Optional[DepartmentOut] = None
    receiver_groups: List["ReceiverGroupOut"] = []
    created_at: datetime
    raw_device_token: Optional[str] = None # Populated once on registration / rotation
    model_config = ConfigDict(from_attributes=True)

# --- Receiver Groups ---
class ReceiverGroupBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = ""
    enabled: bool = True

class ReceiverGroupCreate(ReceiverGroupBase):
    station_ids: Optional[List[int]] = None

class ReceiverGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    station_ids: Optional[List[int]] = None

class ReceiverGroupOut(ReceiverGroupBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- Alarm Types ---
class AlarmTypeBase(BaseModel):
    code: str
    name: str
    description: Optional[str] = ""
    enabled: bool = True
    priority: int = 1
    display_color: str = "#dc2626"
    receiver_group_id: Optional[int] = None
    audio_sequence: Optional[List[str]] = []
    allowed_department_ids: Optional[List[int]] = []
    repeat_count: int = Field(default=3, ge=1, le=100)
    repeat_interval_ms: int = Field(default=1500, ge=0, le=600000)
    validity_seconds: int = Field(default=300, ge=10, le=86400)

    @field_validator('audio_sequence')
    @classmethod
    def local_audio(cls, value):
        if value and any(not path.startswith('/assets/audio/') or '..' in path or '?' in path for path in value):
            raise ValueError('Audio sequence must use local /assets/audio/ paths')
        return value

class AlarmTypeCreate(AlarmTypeBase):
    pass

class AlarmTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    display_color: Optional[str] = None
    receiver_group_id: Optional[int] = None
    audio_sequence: Optional[List[str]] = None
    allowed_department_ids: Optional[List[int]] = None
    repeat_count: Optional[int] = Field(default=None, ge=1, le=100)
    repeat_interval_ms: Optional[int] = Field(default=None, ge=0, le=600000)
    validity_seconds: Optional[int] = Field(default=None, ge=10, le=86400)
    _local_audio = field_validator('audio_sequence')(AlarmTypeBase.local_audio.__func__)

class AlarmTypeOut(AlarmTypeBase):
    id: int
    receiver_group: Optional[ReceiverGroupOut] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- Department Alarm Permissions ---
class DepartmentAlarmPermissionCreate(BaseModel):
    department_id: int
    alarm_type_id: int
    enabled: bool = True

class DepartmentAlarmPermissionOut(BaseModel):
    id: int
    department_id: int
    alarm_type_id: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- Alarm Station States ---
class AlarmStationStateOut(BaseModel):
    id: int
    alarm_id: int
    station_id: int
    state: str
    received_at: Optional[datetime] = None
    displayed_at: Optional[datetime] = None
    audio_started_at: Optional[datetime] = None
    audio_completed_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- Alarms ---
class AlarmCreate(BaseModel):
    alarm_type_id: int
    source_department_id: Optional[int] = None
    source_location: str = ""
    note: str = ""
    idempotency_key: Optional[str] = None

class AlarmEventOut(BaseModel):
    id: int
    alarm_id: int
    station_id: Optional[int] = None
    event_type: str
    event_time: datetime
    event_metadata: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(from_attributes=True)

class AlarmOut(BaseModel):
    id: int
    alarm_type_id: int
    created_by_user_id: Optional[int] = None
    source_department_id: Optional[int] = None
    source_location: str
    note: str
    status: str
    server_sequence: int
    idempotency_key: Optional[str] = None
    created_at: datetime
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    alarm_type: Optional[AlarmTypeOut] = None
    source_department: Optional[DepartmentOut] = None
    created_by_user: Optional[UserOut] = None
    events: List[AlarmEventOut] = []
    station_states: List[AlarmStationStateOut] = []
    model_config = ConfigDict(from_attributes=True)

    @field_validator('created_at', 'activated_at', 'expires_at', 'cancelled_at', mode='before')
    @classmethod
    def utc_timestamps(cls, value):
        return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value

# --- Notification Outbox ---
class NotificationOutboxOut(BaseModel):
    id: int
    event_type: str
    alarm_id: Optional[int] = None
    payload: Dict[str, Any]
    status: str
    attempt_count: int
    next_attempt_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    sent_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

# --- Audio Files ---
class AudioFileCreate(BaseModel):
    code: str
    name: str
    file_path: str
    mime_type: str = "audio/mpeg"
    enabled: bool = True

class AudioFileOut(BaseModel):
    id: int
    code: str
    name: str
    file_path: str
    mime_type: str
    enabled: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# --- Health ---
class HealthResponse(BaseModel):
    status: str
    database: str
    websocket: str
    n8n: str
    active_stations: int
    total_stations: int
