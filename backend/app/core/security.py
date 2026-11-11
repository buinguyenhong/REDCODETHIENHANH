import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import jwt
import bcrypt
from app.config import settings

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def hash_device_token(token: str) -> str:
    # Use SHA-256 for deterministic indexing/lookup of device token
    return hashlib.sha256(f"{token}:{settings.SECRET_KEY}".encode("utf-8")).hexdigest()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except Exception:
        return None


def extract_client_ip(request_or_ws: Any) -> Optional[str]:
    """Lấy địa chỉ IP thực của máy trạm phía sau Nginx reverse proxy.

    Ưu tiên header ``X-Forwarded-For`` (lấy địa chỉ đầu tiên) rồi ``X-Real-IP``
    do Nginx truyền vào, trước khi rơi về ``client.host`` trực tiếp.
    """
    headers = getattr(request_or_ws, "headers", None)
    if headers:
        forwarded_for = headers.get("x-forwarded-for")
        if forwarded_for:
            first_ip = forwarded_for.split(",")[0].strip()
            if first_ip:
                return first_ip
        real_ip = headers.get("x-real-ip")
        if real_ip and real_ip.strip():
            return real_ip.strip()
    client = getattr(request_or_ws, "client", None)
    host = getattr(client, "host", None)
    return host if isinstance(host, str) and host.strip() else None
