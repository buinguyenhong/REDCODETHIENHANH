from typing import List, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator

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

    # URL webhook của n8n. Hostname `n8n` là tên service/container trên Docker
    # network mà backend cùng tham gia — không phải localhost (trong container,
    # localhost là chính backend). Đổi path ở đây thì phải đổi path của Webhook
    # node trong workflow n8n cho khớp: lệch path trả 404, và 404 bị tính là một
    # lần gửi thất bại nên thông báo sẽ retry rồi cạn lượt (EXHAUSTED) trong im lặng.
    N8N_WEBHOOK_URL: str = "http://n8n:5678/webhook/redcode"
    N8N_ENABLED: bool = False
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
                raise ValueError(
                    'Production requires a postgresql+asyncpg:// DATABASE_URL and DEMO_MODE=false. '
                    'Khai báo DATABASE_URL trong .env trước khi khởi động.'
                )
            if len(self.SECRET_KEY) < 32 or self.SECRET_KEY.startswith(('redcode-secret', 'change-this')):
                raise ValueError('Production requires a unique SECRET_KEY of at least 32 characters')
            if '*' in self.ALLOWED_ORIGINS:
                raise ValueError('Production requires an explicit origin allowlist')
        if self.N8N_ENABLED and not self.N8N_WEBHOOK_URL.strip():
            raise ValueError('N8N_ENABLED=true requires N8N_WEBHOOK_URL')
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
