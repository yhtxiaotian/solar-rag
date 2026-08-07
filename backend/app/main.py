import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import delete

from app.api import auth, chat, documents
from app.core.config import settings
from app.db import SessionLocal, init_db
from app.models import Conversation


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("solar-rag")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        db.execute(delete(Conversation).where(Conversation.expires_at < datetime.now(timezone.utc)))
        db.commit()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def security_and_logging(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    logger.info(
        json.dumps(
            {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            },
            ensure_ascii=False,
        )
    )
    return response


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception):
    logger.exception("unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "服务暂时不可用，请稍后重试"})


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(documents.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)

