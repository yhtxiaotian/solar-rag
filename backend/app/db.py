from collections.abc import Generator

from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    type_annotation_map = {list[float]: Vector(settings.embedding_dimension)}


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _set_pgvector(connection, _record) -> None:  # type: ignore[no-untyped-def]
    # pgvector registers through SQLAlchemy's type; extension creation happens at startup.
    del connection


def init_db() -> None:
    from app import models  # noqa: F401

    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    Base.metadata.create_all(bind=engine)
    configured_model = (
        "offline-hash"
        if settings.ai_offline_mode
        else f"{settings.embedding_provider}:{settings.embedding_model.strip()}"
    )
    if not configured_model:
        return
    fingerprint = f"{configured_model}\n{settings.embedding_dimension}"
    with SessionLocal() as db:
        locked = db.get(models.SystemSetting, "embedding_configuration")
        if locked and locked.value != fingerprint:
            previous_model, _, previous_dimension = locked.value.partition("\n")
            raise RuntimeError(
                "Embedding 配置与现有知识库不一致："
                f"当前数据库锁定 {previous_model}/{previous_dimension}，"
                f"环境变量为 {configured_model}/{settings.embedding_dimension}。"
                "请先执行全库重新向量化并重建索引。"
            )
        if not locked:
            db.add(models.SystemSetting(key="embedding_configuration", value=fingerprint))
            db.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
