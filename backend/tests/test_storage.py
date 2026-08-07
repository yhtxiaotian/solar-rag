import io
import zipfile

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.services.storage import save_bytes


def test_pdf_signature_and_hash_deduplication(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_path", tmp_path)
    first = save_bytes(b"%PDF-1.7\nminimal", "政策.pdf")
    second = save_bytes(b"%PDF-1.7\nminimal", "重复.pdf")
    assert first.sha256 == second.sha256
    assert first.path == second.path
    assert first.path.exists()


def test_rejects_extension_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_path", tmp_path)
    with pytest.raises(HTTPException) as caught:
        save_bytes(b"not a pdf", "fake.pdf")
    assert caught.value.status_code == 415


def test_validates_office_container(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_path", tmp_path)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("word/document.xml", "<document />")
    stored = save_bytes(payload.getvalue(), "manual.docx")
    assert stored.content_type.endswith("wordprocessingml.document")

