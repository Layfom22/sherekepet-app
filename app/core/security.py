from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import bcrypt
import jwt

from app.core.config import settings
from app.core.timezone import get_lima_now


def hash_pin(pin: str) -> str:
    """Genera hash seguro para el PIN utilizando bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pin.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    """Verifica si el PIN plano coincide con el hash almacenado."""
    if not hashed_pin:
        return False
    try:
        return bcrypt.checkpw(plain_pin.encode("utf-8"), hashed_pin.encode("utf-8"))
    except Exception:
        return False


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """Genera un JWT firmado con los datos del usuario y tiempo de expiración."""
    to_encode = data.copy()
    now = get_lima_now()
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": now
    })
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decodifica y valida un JWT retornando su payload."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except jwt.PyJWTError:
        return None
