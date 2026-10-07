from typing import List, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator
import os
import json
from pathlib import Path

# Installer-owned persistent configuration takes precedence over deployment env.
runtime_path = Path(os.getenv('REDCODE_RUNTIME_CONFIG', '/app/config/runtime.json'))
if runtime_path.is_file():
    runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
    for key in ('DATABASE_URL', 'SECRET_KEY', 'INITIAL_ADMIN_PASSWORD'):
        if key in runtime:
            os.environ[key] = runtime[key]

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DEMO_MODE: bool = True
    INITIAL_ADMIN_PASSWORD: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./redcode.db"
    SECRET_KEY: str = "redcode-secret-key-bvth-2026-production-baseline"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    HEARTBEAT_INTERVAL_SECONDS: int = 5
    STATION_OFFLINE_THRESHOLD_SECONDS: int = 15

    N8N_WEBHOOK_URL: str = "http://localhost:5678/webhook/redcode/alarm"
    N8N_TIMEOUT_SECONDS: int = 4
    N8N_MAX_RETRIES: int = 3

    ALLOWED_ORIGINS: Union[str, List[str]] = "*"
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    AUDIO_UPLOAD_DIR: str = "static/audio"

    @model_validator(mode='after')
    def production_configuration(self):
        if self.ENVIRONMENT == 'production':
            if self.DEMO_MODE or not self.DATABASE_URL.startswith('postgresql'):
                raise ValueError('Production requires PostgreSQL and DEMO_MODE=false')
            if len(self.SECRET_KEY) < 32 or self.SECRET_KEY.startswith(('redcode-secret', 'change-this')):
                raise ValueError('Production requires a unique SECRET_KEY of at least 32 characters')
            if '*' in self.ALLOWED_ORIGINS:
                raise ValueError('Production requires an explicit origin allowlist')
        return self

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v == "*":
                return ["*"]
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
