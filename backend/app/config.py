from typing import List, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
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
