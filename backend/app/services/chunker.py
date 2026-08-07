from dataclasses import dataclass

from app.core.config import settings


@dataclass(slots=True)
class ParsedBlock:
    content: str
    page: int | None = None
    section: str | None = None
    kind: str = "paragraph"


@dataclass(slots=True)
class ChunkDraft:
    content: str
    page_start: int | None
    page_end: int | None
    section_path: str | None


def _split_long_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    separators = ["\n\n", "。", "；", "\n", "，"]
    parts = [text]
    for separator in separators:
        next_parts: list[str] = []
        for part in parts:
            if len(part) <= max_chars:
                next_parts.append(part)
                continue
            fragments = part.split(separator)
            current = ""
            for fragment in fragments:
                candidate = f"{current}{separator if current else ''}{fragment}"
                if current and len(candidate) > max_chars:
                    next_parts.append(current.strip())
                    current = fragment
                else:
                    current = candidate
            if current.strip():
                next_parts.append(current.strip())
        parts = next_parts
    final: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            final.append(part)
        else:
            final.extend(part[index : index + max_chars] for index in range(0, len(part), max_chars))
    return [part.strip() for part in final if part.strip()]


def _table_segments(text: str, max_chars: int) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(text) <= max_chars or len(lines) < 3:
        return [text]
    header = lines[:2]
    segments: list[str] = []
    current = header.copy()
    for row in lines[2:]:
        if len("\n".join(current + [row])) > max_chars and len(current) > 2:
            segments.append("\n".join(current))
            current = header + [row]
        else:
            current.append(row)
    if len(current) > 2:
        segments.append("\n".join(current))
    return segments


def chunk_blocks(blocks: list[ParsedBlock]) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    buffer: list[str] = []
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None

    def flush(keep_overlap: bool = True) -> None:
        nonlocal buffer, page_start, page_end, section
        content = "\n\n".join(buffer).strip()
        if content:
            drafts.append(ChunkDraft(content, page_start, page_end, section))
        overlap = content[-settings.chunk_overlap_chars :] if keep_overlap and len(content) > settings.chunk_min_chars else ""
        buffer = [overlap] if overlap else []
        page_start = page_end if overlap else None
        if not overlap:
            page_end = None

    for block in blocks:
        clean = "\n".join(line.rstrip() for line in block.content.splitlines()).strip()
        if not clean:
            continue
        pieces = _table_segments(clean, settings.chunk_max_chars) if block.kind == "table" else _split_long_text(
            clean, settings.chunk_max_chars
        )
        for piece in pieces:
            # A Markdown table segment already respects the size limit and
            # repeats its header.  Keep it as an atomic chunk; prose overlap
            # would otherwise create headerless fragments between segments.
            if block.kind == "table":
                if buffer:
                    flush(keep_overlap=False)
                page_start = block.page
                page_end = block.page
                section = block.section or section
                buffer = [piece]
                flush(keep_overlap=False)
                continue
            if block.section and section and block.section != section and len("\n\n".join(buffer)) >= settings.chunk_min_chars:
                flush(keep_overlap=False)
            if buffer and len("\n\n".join(buffer + [piece])) > settings.chunk_target_chars:
                flush()
            if page_start is None:
                page_start = block.page
            page_end = block.page or page_end
            section = block.section or section
            buffer.append(piece)
            if len("\n\n".join(buffer)) >= settings.chunk_max_chars:
                flush()
    if len(buffer) == 1 and len(buffer[0]) <= settings.chunk_overlap_chars:
        buffer = []
    flush(keep_overlap=False)
    return drafts
