import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.security import require_admin
from app.db import get_db
from app.models import Chunk, Document, IngestStatus
from app.schemas import DocumentMetadata, DocumentResponse, ManifestPreviewResponse
from app.services.ingest import queue_document
from app.services.manifest import ManifestError, load_manifest, preview_manifest
from app.services.storage import save_upload


router = APIRouter(prefix="/admin", tags=["admin-documents"], dependencies=[Depends(require_admin)])


def _document_from_metadata(metadata: DocumentMetadata) -> Document:
    # Keep ``date`` objects intact for PostgreSQL DATE columns.  JSON mode is
    # only appropriate at the HTTP boundary and would turn them into strings.
    values = metadata.model_dump(mode="python")
    if values.get("source_url"):
        values["source_url"] = str(values["source_url"])
    return Document(**values)


@router.post("/documents/upload", response_model=DocumentResponse, status_code=201)
def upload_document(
    file: UploadFile = File(...),
    metadata_json: str = Form(...),
    db: Session = Depends(get_db),
) -> Document:
    try:
        metadata = DocumentMetadata.model_validate_json(metadata_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    stored = save_upload(file)
    duplicate = db.scalar(select(Document).where(Document.sha256 == stored.sha256).limit(1))
    if duplicate:
        raise HTTPException(status_code=409, detail=f"该文件已由《{duplicate.title}》收录")
    pending = db.scalar(
        select(Document)
        .where(
            Document.ingest_status == IngestStatus.PENDING_SOURCE.value,
            or_(
                Document.local_file_name == stored.original_name,
                and_(Document.title == metadata.title, Document.version == metadata.version),
            ),
        )
        .limit(1)
    )
    document = pending or _document_from_metadata(metadata)
    if pending:
        # The manifest remains the authoritative metadata record.  The upload
        # only supplies missing fields plus the file itself.
        submitted = metadata.model_dump(mode="python")
        for key, value in submitted.items():
            if value not in (None, "", []) and not getattr(document, key, None):
                setattr(document, key, str(value) if key == "source_url" else value)
    document.local_file_name = stored.original_name
    document.stored_path = str(stored.path)
    document.content_type = stored.content_type
    document.sha256 = stored.sha256
    document.file_size = stored.size
    document.ingest_status = IngestStatus.QUEUED.value
    if not pending:
        db.add(document)
    db.commit()
    db.refresh(document)
    queue_document(document.id)
    return document


@router.post("/manifests/import", response_model=ManifestPreviewResponse | dict)
def import_manifest(
    file: UploadFile = File(...),
    preview: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    try:
        entries = load_manifest(file.file.read())
    except ManifestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    report = preview_manifest(db, entries)
    if preview:
        return report
    if report.invalid:
        raise HTTPException(status_code=422, detail="清单含有无效条目，请修正后再导入")
    created: list[Document] = []
    for item in report.items:
        if item.action == "duplicate":
            continue
        metadata = DocumentMetadata.model_validate(item.entry)
        document = _document_from_metadata(metadata)
        document.ingest_status = (
            IngestStatus.QUEUED.value if document.source_url else IngestStatus.PENDING_SOURCE.value
        )
        db.add(document)
        created.append(document)
    db.commit()
    for document in created:
        db.refresh(document)
        if document.ingest_status == IngestStatus.QUEUED.value:
            queue_document(document.id)
    return {"created": len(created), "duplicates": sum(item.action == "duplicate" for item in report.items)}


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[Document]:
    query = select(Document).order_by(Document.created_at.desc())
    if status_filter:
        query = query.where(Document.ingest_status == status_filter)
    return list(db.scalars(query).all())


@router.patch("/documents/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: uuid.UUID,
    metadata: DocumentMetadata,
    db: Session = Depends(get_db),
) -> Document:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="资料不存在")
    values = metadata.model_dump(mode="python")
    for key, value in values.items():
        setattr(document, key, str(value) if key == "source_url" and value else value)
    db.commit()
    db.refresh(document)
    return document


@router.post("/documents/{document_id}/reindex", status_code=202)
def reindex_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, str]:
    document = db.get(Document, document_id)
    if not document or document.archived_at:
        raise HTTPException(status_code=404, detail="资料不存在")
    if not document.stored_path and not document.source_url:
        raise HTTPException(status_code=409, detail="请先上传文件或补充官方链接")
    document.ingest_status = IngestStatus.QUEUED.value
    document.error_message = None
    db.commit()
    queue_document(document.id)
    return {"status": "queued"}


@router.post("/documents/{document_id}/archive")
def archive_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, bool]:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="资料不存在")
    document.archived_at = datetime.now(timezone.utc)
    document.ingest_status = IngestStatus.ARCHIVED.value
    db.commit()
    return {"archived": True}


@router.get("/documents/{document_id}/preview")
def preview_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="资料不存在")
    chunks = db.scalars(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.ordinal).limit(8)
    ).all()
    return {
        "document": DocumentResponse.model_validate(document).model_dump(mode="json"),
        "chunks": [
            {
                "ordinal": chunk.ordinal,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section": chunk.section_path,
                "content": chunk.content,
            }
            for chunk in chunks
        ],
    }
