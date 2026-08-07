import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.limiting import rate_limiter
from app.core.security import daily_ip_hash
from app.db import get_db
from app.models import Conversation, Feedback, Message
from app.schemas import ChatRequest, FeedbackRequest
from app.services.rag import answer_question


router = APIRouter(tags=["chat"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest, request: Request, db: Session = Depends(get_db)) -> StreamingResponse:
    if not settings.ai_configured:
        raise HTTPException(status_code=503, detail="管理员尚未配置 AI 服务")
    session_hash = daily_ip_hash(request)
    rate_limiter.check(session_hash)
    conversation: Conversation | None = None
    history: list[dict[str, str]] = []
    if payload.conversation_id:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == payload.conversation_id,
                Conversation.session_hash == session_hash,
                Conversation.expires_at > datetime.now(timezone.utc),
            )
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="会话不存在或已过期")
        previous = db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(8)
        ).all()
        history = [{"role": item.role, "content": item.content} for item in reversed(previous)]
    else:
        conversation = Conversation(
            session_hash=session_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.conversation_retention_days),
        )
        db.add(conversation)
        db.flush()
    if payload.history:
        history = [turn.model_dump() for turn in payload.history[-8:]]

    user_message = Message(conversation_id=conversation.id, role="user", content=payload.question)
    db.add(user_message)
    started = time.perf_counter()
    answer = answer_question(db, payload.question, history, payload.categories, payload.region)
    latency_ms = int((time.perf_counter() - started) * 1000)
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=answer.content,
        citations=[item.model_dump(mode="json") for item in answer.citations],
        prompt_tokens=answer.prompt_tokens,
        completion_tokens=answer.completion_tokens,
        latency_ms=latency_ms,
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    tokens = answer.prompt_tokens + answer.completion_tokens
    rate_limiter.add_tokens(tokens)

    def events():
        yield _sse("meta", {"conversation_id": conversation.id, "latency_ms": latency_ms})
        for index in range(0, len(answer.content), 18):
            yield _sse("delta", {"text": answer.content[index : index + 18]})
        for citation in answer.citations:
            yield _sse("citation", citation.model_dump(mode="json"))
        yield _sse(
            "done",
            {
                "message_id": assistant_message.id,
                "prompt_tokens": answer.prompt_tokens,
                "completion_tokens": answer.completion_tokens,
            },
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/feedback", status_code=201)
def submit_feedback(payload: FeedbackRequest, db: Session = Depends(get_db)) -> dict[str, bool]:
    if not db.get(Message, payload.message_id):
        raise HTTPException(status_code=404, detail="回答不存在")
    existing = db.scalar(select(Feedback).where(Feedback.message_id == payload.message_id))
    if existing:
        existing.helpful = payload.helpful
        existing.comment = payload.comment
    else:
        db.add(Feedback(**payload.model_dump()))
    db.commit()
    return {"ok": True}

