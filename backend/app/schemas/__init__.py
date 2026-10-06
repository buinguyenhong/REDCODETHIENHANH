from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

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
    role: str = "OPERATOR"
    enabled: bool = True

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    department_id: Optional[int] = None
    role: Optional[str] = None
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
    device_token: str
    receiver_group_ids: Optional[List[int]] = None

class StationHeartbeat(BaseModel):
    station_code: str
    device_token: str
    audio_ready: bool = False
    client_ready: bool = True
    ip_address: Optional[str] = None

class StationDismiss(BaseModel):
    alarm_id: int
    station_code: str
    device_token: Optional[str] = None
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
    repeat_count: int = 3
    repeat_interval_ms: int = 1500

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
    repeat_count: Optional[int] = None
    repeat_interval_ms: Optional[int] = None

class AlarmTypeOut(AlarmTypeBase):
    id: int
    receiver_group: Optional[ReceiverGroupOut] = None
    created_at: datetime
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
    display_completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    alarm_type: Optional[AlarmTypeOut] = None
    source_department: Optional[DepartmentOut] = None
    created_by_user: Optional[UserOut] = None
    events: List[AlarmEventOut] = []
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
