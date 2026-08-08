import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import SessionLocal
from app.models import Chunk, Document, IngestStatus, ValidityStatus
from app.services.ai import ai_client
from app.services.chunker import chunk_blocks
from app.services.parser import parse_document
from app.services.retrieval import tokenize
from app.services.storage import save_bytes
from app.services.url_safety import download_public_file


def _is_newer(candidate: Document, existing: Document) -> bool:
    candidate_date = candidate.effective_at or candidate.published_at
    existing_date = existing.effective_at or existing.published_at
    if candidate_date and existing_date:
        return candidate_date >= existing_date
    return candidate.created_at >= existing.created_at


def _apply_version_status(db: Session, document: Document) -> None:
    if not document.document_no:
        return
    siblings = db.scalars(
        select(Document).where(
            Document.document_no == document.document_no,
            Document.id != document.id,
            Document.archived_at.is_(None),
        )
    ).all()
    for sibling in siblings:
        if _is_newer(document, sibling):
            if sibling.validity_status in {ValidityStatus.ACTIVE.value, ValidityStatus.UNKNOWN.value}:
                sibling.validity_status = ValidityStatus.SUPERSEDED.value
            if document.validity_status == ValidityStatus.UNKNOWN.value:
                document.validity_status = ValidityStatus.ACTIVE.value
        else:
            document.validity_status = ValidityStatus.SUPERSEDED.value


def process_document(document_id: str) -> None:
    db = SessionLocal()
    document: Document | None = None
    try:
        document = db.get(Document, uuid.UUID(document_id))
        if not document:
            return
        document.error_message = None
        if not document.stored_path:
            if not document.source_url:
                document.ingest_status = IngestStatus.PENDING_SOURCE.value
                db.commit()
                return
            document.ingest_status = IngestStatus.DOWNLOADING.value
            db.commit()
            downloaded = download_public_file(document.source_url)
            stored = save_bytes(downloaded.data, downloaded.filename)
            duplicate = db.scalar(
                select(Document).where(Document.sha256 == stored.sha256, Document.id != document.id).limit(1)
            )
            if duplicate:
                raise ValueError(f"该文件已由《{duplicate.title}》收录")
            document.stored_path = str(stored.path)
            document.local_file_name = stored.original_name
            document.sha256 = stored.sha256
            document.file_size = stored.size
            document.content_type = stored.content_type
            document.source_url = downloaded.final_url

        document.ingest_status = IngestStatus.PARSING.value
        db.commit()
        blocks = parse_document(Path(document.stored_path))
        drafts = chunk_blocks(blocks)
        if not drafts:
            raise ValueError("文档解析后没有可索引的正文")

        document.ingest_status = IngestStatus.INDEXING.value
        db.commit()
        vectors: list[list[float]] = []
        batch_size = 32
        for index in range(0, len(drafts), batch_size):
            vectors.extend(ai_client.embeddings([draft.content for draft in drafts[index : index + batch_size]]))

        db.execute(delete(Chunk).where(Chunk.document_id == document.id))
        for ordinal, (draft, vector) in enumerate(zip(drafts, vectors, strict=True)):
            db.add(
                Chunk(
                    document_id=document.id,
                    ordinal=ordinal,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    section_path=draft.section_path,
                    content=draft.content,
                    search_tokens=tokenize(draft.content),
                    embedding=vector,
                    embedding_model=(
                        "offline-hash"
                        if settings.ai_offline_mode
                        else f"{settings.embedding_provider}:{settings.embedding_model}"
                    ),
                    char_count=len(draft.content),
                )
            )
        document.page_count = max((block.page or 0 for block in blocks), default=0) or None
        document.chunk_count = len(drafts)
        document.ingest_status = IngestStatus.READY.value
        _apply_version_status(db, document)
        db.commit()
    except Exception as exc:
        db.rollback()
        if document:
            document.ingest_status = IngestStatus.FAILED.value
            document.error_message = str(exc)[:2000]
            db.add(document)
            db.commit()
    finally:
        db.close()


def queue_document(document_id: uuid.UUID) -> None:
    if settings.celery_always_eager:
        process_document(str(document_id))
    else:
        from app.tasks import ingest_document

        ingest_document.delay(str(document_id))
