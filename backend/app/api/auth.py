from fastapi import APIRouter, Depends, Response, status

from app.core.config import settings
from app.core.security import ADMIN_COOKIE, create_admin_session, require_admin, verify_admin_password
from app.schemas import LoginRequest


router = APIRouter(prefix="/admin", tags=["admin-auth"])


@router.post("/login")
def login(payload: LoginRequest, response: Response) -> dict[str, str]:
    if payload.username != settings.admin_username or not verify_admin_password(payload.password):
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return {"detail": "账号或密码错误"}
    response.set_cookie(
        ADMIN_COOKIE,
        create_admin_session(payload.username),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return {"username": payload.username}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(username: str = Depends(require_admin)) -> dict[str, str]:
    return {"username": username}

