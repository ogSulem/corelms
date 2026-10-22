"""Access credentials are bound to both a login session and the current password."""
import hashlib
import hmac
import time
import uuid

from jose import jwt

from app.core.config import settings
from app.models.user import User


def password_version(user: User) -> str:
    return hmac.new(settings.jwt_secret_key.encode(), user.password_hash.encode(), hashlib.sha256).hexdigest()


def create_access_token(user: User, session_id: str, *, authenticated_password_version: str | None = None) -> str:
    now = time.time()
    return jwt.encode({
        "sub": str(user.id), "sid": session_id, "pv": authenticated_password_version or password_version(user),
        "role": user.role.value, "iat": now, "exp": now + settings.jwt_access_token_minutes * 60,
        "iss": settings.jwt_issuer, "jti": str(uuid.uuid4()),
    }, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
