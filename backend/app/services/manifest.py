from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Document
from app.schemas import ManifestEntry, ManifestPreviewItem, ManifestPreviewResponse


class ManifestError(ValueError):
    pass


def load_manifest(payload: bytes) -> list[Any]:
    if len(payload) > 2 * 1024 * 1024:
        raise ManifestError("知识清单不能超过 2 MB")
    try:
        data = yaml.safe_load(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ManifestError("知识清单必须是有效的 UTF-8 YAML") from exc
    entries = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ManifestError("知识清单根节点必须是 sources 列表")
    if len(entries) > 1000:
        raise ManifestError("单次最多导入 1000 条资料")
    return entries


def preview_manifest(db: Session, entries: list[Any]) -> ManifestPreviewResponse:
    items: list[ManifestPreviewItem] = []
    valid_count = 0
    for row, raw in enumerate(entries, start=1):
        try:
            entry = ManifestEntry.model_validate(raw)
            source_url = str(entry.source_url) if entry.source_url else None
            # A new revision commonly keeps the same title, so title alone
            # must not make it a duplicate.  Match the same title + version,
            # exact source URL, or exact document number + version instead.
            predicates = [
                (Document.title == entry.title) & (Document.version == entry.version)
            ]
            if source_url:
                predicates.append(Document.source_url == source_url)
            if entry.document_no:
                predicates.append(
                    (Document.document_no == entry.document_no) & (Document.version == entry.version)
                )
            duplicate = db.scalar(select(Document.id).where(or_(*predicates)).limit(1))
            action = "duplicate" if duplicate else ("create" if source_url else "pending_source")
            items.append(
                ManifestPreviewItem(
                    row=row,
                    valid=True,
                    action=action,
                    entry=entry.model_dump(mode="json"),
                )
            )
            valid_count += 1
        except ValidationError as exc:
            items.append(
                ManifestPreviewItem(
                    row=row,
                    valid=False,
                    action="invalid",
                    entry=raw if isinstance(raw, dict) else {"value": raw},
                    errors=[error["msg"] for error in exc.errors()],
                )
            )
    return ManifestPreviewResponse(
        total=len(items), valid=valid_count, invalid=len(items) - valid_count, items=items
    )
