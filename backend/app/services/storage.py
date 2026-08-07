import hashlib
import io
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt", ".md", ".html", ".htm"}
MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
}


@dataclass(slots=True)
class StoredFile:
    path: Path
    sha256: str
    size: int
    content_type: str
    original_name: str


def safe_filename(filename: str) -> str:
    base = Path(filename).name
    stem = re.sub(r"[^\w\-.\u4e00-\u9fff]+", "-", Path(base).stem, flags=re.UNICODE).strip("-.")
    suffix = Path(base).suffix.lower()
    return f"{stem[:120] or 'document'}{suffix}"


def _validate_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="仅支持 PDF、DOCX、XLSX、TXT、Markdown 和 HTML 文件",
        )
    return suffix


def _validate_signature(path: Path, suffix: str) -> str:
    header = path.read_bytes()[:16]
    if suffix == ".pdf" and not header.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="文件扩展名与实际 PDF 内容不一致")
    if suffix in {".docx", ".xlsx"}:
        if not zipfile.is_zipfile(path):
            raise HTTPException(status_code=415, detail="Office 文件格式无效")
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > 20_000:
                    raise HTTPException(status_code=413, detail="Office 文件包含过多内容")
                expanded = sum(item.file_size for item in entries)
                if expanded > settings.max_file_size_bytes * 10:
                    raise HTTPException(status_code=413, detail="Office 文件解压后体积过大")
                names = {item.filename for item in entries}
                required = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
                if required not in names:
                    raise HTTPException(status_code=415, detail="文件扩展名与实际 Office 内容不一致")
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=415, detail="Office 文件已损坏") from exc
    if suffix in {".txt", ".md", ".html", ".htm"} and b"\x00" in header:
        raise HTTPException(status_code=415, detail="文本文件包含二进制内容")
    return MIME_BY_EXTENSION[suffix]


def save_stream(stream, filename: str) -> StoredFile:  # type: ignore[no-untyped-def]
    suffix = _validate_extension(filename)
    original_name = safe_filename(filename)
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    # A random temporary name avoids concurrent uploads of identically named
    # files writing into the same path before hash-based deduplication.
    temp_path = settings.storage_path / f".upload-{uuid.uuid4().hex}"
    digest = hashlib.sha256()
    size = 0
    try:
        with temp_path.open("wb") as target:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_file_size_bytes:
                    raise HTTPException(status_code=413, detail=f"文件不能超过 {settings.max_file_size_mb} MB")
                digest.update(chunk)
                target.write(chunk)
        content_type = _validate_signature(temp_path, suffix)
        sha256 = digest.hexdigest()
        final_dir = settings.storage_path / sha256[:2]
        final_dir.mkdir(parents=True, exist_ok=True)
        final_path = final_dir / f"{sha256}{suffix}"
        if final_path.exists():
            temp_path.unlink(missing_ok=True)
        else:
            temp_path.replace(final_path)
        return StoredFile(final_path, sha256, size, content_type, original_name)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def save_upload(upload: UploadFile) -> StoredFile:
    return save_stream(upload.file, upload.filename or "document")


def save_bytes(data: bytes, filename: str) -> StoredFile:
    return save_stream(io.BytesIO(data), filename)


def remove_if_unreferenced(path: str | None) -> None:
    if not path:
        return
    candidate = Path(path).resolve()
    root = settings.storage_path.resolve()
    if root not in candidate.parents:
        return
    candidate.unlink(missing_ok=True)
