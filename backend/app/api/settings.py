from datetime import datetime, timezone
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from app.database import get_db
from app.api.deps import get_current_active_admin
from app.models import IntegrationSettings, SystemEvent

router = APIRouter(prefix='/settings', tags=['System settings'])


class IntegrationInput(BaseModel):
    enabled: bool = False
    webhook_url: str = ''
    timeout_seconds: int = Field(default=4, ge=1, le=30)
    max_retries: int = Field(default=3, ge=1, le=10)

    @model_validator(mode='after')
    def validate_url(self):
        if self.enabled or self.webhook_url:
            url = urlsplit(self.webhook_url)
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
                raise ValueError('Webhook phải là HTTP/HTTPS URL không chứa user/password')
        return self


def output(row):
    return {'enabled': row.enabled if row else False, 'webhook_url': row.webhook_url if row else '',
            'timeout_seconds': row.timeout_seconds if row else 4, 'max_retries': row.max_retries if row else 3}


@router.get('/n8n')
async def read(db=Depends(get_db), admin=Depends(get_current_active_admin)):
    return output(await db.get(IntegrationSettings, 1))


@router.put('/n8n')
async def save(data: IntegrationInput, db=Depends(get_db), admin=Depends(get_current_active_admin)):
    row = await db.get(IntegrationSettings, 1)
    if row is None:
        row = IntegrationSettings(id=1, enabled=False)
        db.add(row)
    if data.enabled and row.enabled_since is None:
        row.enabled_since = datetime.now(timezone.utc)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    db.add(SystemEvent(event_type='INTEGRATION_CONFIGURED', severity='INFO', message='Admin updated n8n settings',
        event_metadata={'actor_id': admin.id, 'enabled': data.enabled}, created_at=datetime.now(timezone.utc)))
    await db.commit()
    return output(row)


@router.post('/n8n/test')
async def test(data: IntegrationInput, admin=Depends(get_current_active_admin)):
    if not data.webhook_url:
        raise HTTPException(422, 'Nhập webhook URL trước khi kiểm tra')
    try:
        async with httpx.AsyncClient(timeout=data.timeout_seconds) as client:
            response = await client.post(data.webhook_url, json={'event': 'REDCODE_CONNECTION_TEST', 'is_test': True})
            return {'success': response.is_success, 'http_status': response.status_code}
    except Exception:
        return {'success': False, 'message': 'Không kết nối được webhook'}
