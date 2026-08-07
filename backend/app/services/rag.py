import re
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.schemas import Citation
from app.services.ai import AIClient, ai_client
from app.services.retrieval import RetrievedChunk, hybrid_retrieve


REFUSAL = "资料库中没有足够证据回答这个问题。你可以换一种问法，或请管理员补充相关资料。"


@dataclass(slots=True)
class RAGAnswer:
    content: str
    citations: list[Citation]
    prompt_tokens: int
    completion_tokens: int


def _citation(item: RetrievedChunk, index: int) -> Citation:
    excerpt = " ".join(item.chunk.content.split())
    return Citation(
        index=index,
        chunk_id=item.chunk.id,
        document_id=item.document.id,
        title=item.document.title,
        document_no=item.document.document_no,
        page_start=item.chunk.page_start,
        page_end=item.chunk.page_end,
        section=item.chunk.section_path,
        excerpt=excerpt[:360] + ("…" if len(excerpt) > 360 else ""),
        source_url=item.document.source_url,
    )


def _validated_answer(
    answer: str,
    evidence_count: int,
    *,
    allowed_titles: set[str] | None = None,
    allowed_pages: set[int] | None = None,
    allowed_files: set[str] | None = None,
) -> tuple[str, set[int]]:
    references = {int(value) for value in re.findall(r"\[(\d+)]", answer)}
    valid = {value for value in references if 1 <= value <= evidence_count}
    for invalid in references - valid:
        answer = answer.replace(f"[{invalid}]", "")
    # Citations shown by the UI always come from retrieved records.  Also
    # reject prose that invents a document title, filename or page number so a
    # valid marker cannot be attached to fabricated source metadata.
    mentioned_titles = set(re.findall(r"《([^》]{1,500})》", answer))
    mentioned_pages = {int(value) for value in re.findall(r"第\s*(\d+)\s*页", answer)}
    mentioned_files = set(
        re.findall(r"[\w.\-\u4e00-\u9fff]+\.(?:pdf|docx|xlsx|txt|md|html?)", answer, flags=re.IGNORECASE)
    )
    if (
        (allowed_titles is not None and not mentioned_titles.issubset(allowed_titles))
        or (allowed_pages is not None and not mentioned_pages.issubset(allowed_pages))
        or (allowed_files is not None and not mentioned_files.issubset(allowed_files))
    ):
        return REFUSAL, set()
    refusal_markers = ("没有足够证据", "无法根据", "资料不足", "无法确定")
    if not valid and not any(marker in answer for marker in refusal_markers):
        return REFUSAL, set()
    return answer.strip(), valid


def answer_question(
    db: Session,
    question: str,
    history: list[dict[str, str]],
    categories: list[str],
    region: str | None,
    client: AIClient = ai_client,
) -> RAGAnswer:
    evidence = hybrid_retrieve(db, question, categories, region, client)
    if not evidence or (all(item.rerank_score is not None for item in evidence) and max(item.rerank_score or 0 for item in evidence) < 2):
        return RAGAnswer(REFUSAL, [], 0, 0)

    context_parts = []
    for index, item in enumerate(evidence, start=1):
        metadata = [item.document.title]
        if item.document.document_no:
            metadata.append(item.document.document_no)
        if item.document.version:
            metadata.append(f"版本 {item.document.version}")
        if item.document.effective_at:
            metadata.append(f"生效日期 {item.document.effective_at.isoformat()}")
        if item.chunk.page_start:
            metadata.append(f"第 {item.chunk.page_start} 页")
        if item.chunk.section_path:
            metadata.append(item.chunk.section_path)
        context_parts.append(f"【证据 {index}｜{'｜'.join(metadata)}】\n{item.chunk.content}")

    system = (
        "你是分布式光伏知识库助手。只能依据用户消息中的证据回答，不得使用记忆补充政策、标准、"
        "设备参数或数字。每个重要结论后必须标注对应的 [证据编号]。证据不足时原样回答："
        f"“{REFUSAL}”不同版本冲突时，说明冲突并优先采用明确标记为现行且生效日期较新的资料。"
        "回答使用简洁、专业的中文；不得编造文件名、页码或引用编号。"
    )
    messages = [{"role": "system", "content": system}]
    messages.extend(history[-8:])
    messages.append(
        {
            "role": "user",
            "content": f"问题：{question}\n\n" + "\n\n".join(context_parts),
        }
    )
    completion = client.complete(messages)
    allowed_pages: set[int] = set()
    for item in evidence:
        if item.chunk.page_start:
            allowed_pages.update(
                range(item.chunk.page_start, (item.chunk.page_end or item.chunk.page_start) + 1)
            )
    content, cited = _validated_answer(
        completion.content,
        len(evidence),
        allowed_titles={item.document.title for item in evidence},
        allowed_pages=allowed_pages,
        allowed_files={item.document.local_file_name for item in evidence if item.document.local_file_name},
    )
    citations = [_citation(item, index) for index, item in enumerate(evidence, start=1) if index in cited]
    return RAGAnswer(content, citations, completion.prompt_tokens, completion.completion_tokens)
