import hmac
from datetime import date
from hashlib import sha256

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Cookie, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings


ADMIN_COOKIE = "solar_admin_session"
_password_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(settings.session_secret, salt="solar-admin-session")


def verify_admin_password(password: str) -> bool:
    if not settings.admin_password_hash:
        return False
    try:
        return _password_hasher.verify(settings.admin_password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_admin_session(username: str) -> str:
    return _serializer.dumps({"username": username, "scope": "admin"})


def require_admin(session: str | None = Cookie(default=None, alias=ADMIN_COOKIE)) -> str:
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录管理员账号")
    try:
        payload = _serializer.loads(session, max_age=settings.session_max_age_seconds)
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效") from exc
    if payload.get("scope") != "admin" or payload.get("username") != settings.admin_username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有管理员权限")
    return str(payload["username"])


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def daily_ip_hash(request: Request) -> str:
    raw = f"{date.today().isoformat()}:{client_ip(request)}".encode()
    return hmac.new(settings.rate_limit_salt.encode(), raw, sha256).hexdigest()


AdminUser = str
AdminDependency = Depends(require_admin)

