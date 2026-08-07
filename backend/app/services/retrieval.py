import re
import uuid
from dataclasses import dataclass

import jieba
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Chunk, Document, IngestStatus, ValidityStatus, Visibility
from app.services.ai import AIClient, ai_client


@dataclass(slots=True)
class RetrievedChunk:
    chunk: Chunk
    document: Document
    fused_score: float
    rerank_score: int | None = None


def normalize_query(question: str) -> str:
    question = " ".join(question.split())
    question = re.sub(r"[Ｇｇ][Ｂｂ]\s*[／/]?\s*[Ｔｔ]", "GB/T", question)
    return question.strip()


def tokenize(text: str) -> str:
    words = [word.strip().lower() for word in jieba.cut_for_search(text) if word.strip()]
    identifiers = re.findall(r"[A-Za-z]{1,12}[A-Za-z0-9./_-]*\d[A-Za-z0-9./_-]*", text)
    return " ".join(dict.fromkeys(words + [item.lower() for item in identifiers]))


def _document_filters(categories: list[str], region: str | None):
    filters = [
        Document.ingest_status == IngestStatus.READY.value,
        Document.visibility == Visibility.PUBLIC.value,
        Document.validity_status.in_([ValidityStatus.ACTIVE.value, ValidityStatus.UNKNOWN.value]),
        Document.archived_at.is_(None),
    ]
    if categories:
        filters.append(Document.category.in_(categories))
    if region:
        filters.append(Document.region == region)
    return filters


def hybrid_retrieve(
    db: Session,
    question: str,
    categories: list[str] | None = None,
    region: str | None = None,
    client: AIClient = ai_client,
) -> list[RetrievedChunk]:
    categories = categories or []
    question = normalize_query(question)
    query_tokens = tokenize(question)
    query_vector = client.embeddings([question])[0]
    filters = _document_filters(categories, region)

    distance = Chunk.embedding.cosine_distance(query_vector).label("distance")
    dense_rows = db.execute(
        select(Chunk, Document, distance)
        .join(Document, Chunk.document_id == Document.id)
        .where(*filters)
        .order_by(distance)
        .limit(settings.retrieval_dense_limit)
    ).all()

    keyword_rows = []
    if query_tokens:
        query = func.plainto_tsquery("simple", query_tokens)
        rank = func.ts_rank_cd(func.to_tsvector("simple", Chunk.search_tokens), query).label("rank")
        keyword_rows = db.execute(
            select(Chunk, Document, rank)
            .join(Document, Chunk.document_id == Document.id)
            .where(*filters, func.to_tsvector("simple", Chunk.search_tokens).op("@@")(query))
            .order_by(rank.desc())
            .limit(settings.retrieval_keyword_limit)
        ).all()

    by_id: dict[uuid.UUID, RetrievedChunk] = {}
    k = 60
    for rank_index, row in enumerate(dense_rows, start=1):
        chunk, document, _ = row
        by_id[chunk.id] = RetrievedChunk(chunk, document, 1 / (k + rank_index))
    for rank_index, row in enumerate(keyword_rows, start=1):
        chunk, document, _ = row
        if chunk.id in by_id:
            by_id[chunk.id].fused_score += 1 / (k + rank_index)
        else:
            by_id[chunk.id] = RetrievedChunk(chunk, document, 1 / (k + rank_index))

    fused = sorted(by_id.values(), key=lambda item: item.fused_score, reverse=True)[
        : settings.retrieval_fused_limit
    ]
    scores = client.rerank(
        question,
        [
            {
                "id": str(item.chunk.id),
                "text": f"{item.document.title}\n{item.chunk.section_path or ''}\n{item.chunk.content}",
            }
            for item in fused
        ],
    )
    if scores:
        for item in fused:
            item.rerank_score = scores.get(str(item.chunk.id), 0)
        fused.sort(key=lambda item: (item.rerank_score or 0, item.fused_score), reverse=True)
    return fused[: settings.retrieval_context_limit]

