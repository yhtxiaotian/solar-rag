import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


ValidityValue = Literal["active", "superseded", "expired", "draft", "unknown"]
VisibilityValue = Literal["public", "admin_only"]


class DocumentMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    category: str = Field(default="未分类", max_length=100)
    issuer: str | None = Field(default=None, max_length=255)
    document_no: str | None = Field(default=None, max_length=160)
    region: str = Field(default="中国", max_length=100)
    version: str | None = Field(default=None, max_length=100)
    published_at: date | None = None
    effective_at: date | None = None
    expires_at: date | None = None
    validity_status: ValidityValue = "unknown"
    supersedes: str | None = Field(default=None, max_length=160)
    source_url: HttpUrl | None = None
    local_file_name: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=30)
    notes: str | None = Field(default=None, max_length=4000)
    visibility: VisibilityValue = "public"

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip() for tag in value if tag.strip()))

    @model_validator(mode="after")
    def validate_dates(self) -> "DocumentMetadata":
        if self.expires_at and self.effective_at and self.expires_at < self.effective_at:
            raise ValueError("expires_at cannot be earlier than effective_at")
        return self


class ManifestEntry(DocumentMetadata):
    source_url: HttpUrl | None = None
    local_file_name: str | None = None


class ManifestPreviewItem(BaseModel):
    row: int
    valid: bool
    action: Literal["create", "duplicate", "pending_source", "invalid"]
    entry: dict
    errors: list[str] = Field(default_factory=list)


class ManifestPreviewResponse(BaseModel):
    total: int
    valid: int
    invalid: int
    items: list[ManifestPreviewItem]


class DocumentResponse(DocumentMetadata):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_url: str | None = None
    ingest_status: str
    error_message: str | None = None
    sha256: str | None = None
    file_size: int | None = None
    page_count: int | None = None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=500)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: uuid.UUID | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)
    categories: list[str] = Field(default_factory=list, max_length=10)
    region: str | None = Field(default=None, max_length=100)

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        return " ".join(value.split())


class FeedbackRequest(BaseModel):
    message_id: uuid.UUID
    helpful: bool
    comment: str | None = Field(default=None, max_length=1000)


class Citation(BaseModel):
    index: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    document_no: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    excerpt: str
    source_url: str | None = None

