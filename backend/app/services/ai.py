import hashlib
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings


class AIServiceError(RuntimeError):
    pass


@dataclass(slots=True)
class Completion:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class AIClient:
    def __init__(self) -> None:
        self.base_url = settings.ai_base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.ai_api_key}",
            "Content-Type": "application/json",
        }
        self._local_embedding_model: Any | None = None
        self._local_embedding_lock = threading.Lock()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not settings.ai_configured:
            raise AIServiceError("AI 服务尚未配置")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = httpx.post(
                    f"{self.base_url}{path}",
                    headers=self.headers,
                    json=payload,
                    timeout=settings.ai_timeout_seconds,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                # Authentication, validation and other permanent client errors
                # should surface immediately; only rate limits and 5xx retry.
                if exc.response.status_code < 500 and exc.response.status_code != 429:
                    break
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (2**attempt))
        raise AIServiceError(f"AI 服务调用失败：{last_error}") from last_error

    @staticmethod
    def _offline_embedding(text: str) -> list[float]:
        vector = [0.0] * settings.embedding_dimension
        normalized = re.sub(r"\s+", "", text.lower())
        grams = [normalized[index : index + 2] for index in range(max(1, len(normalized) - 1))]
        for gram in grams:
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % settings.embedding_dimension
            vector[index] += -1.0 if digest[0] & 1 else 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _local_embeddings(self, texts: list[str], *, query: bool) -> list[list[float]]:
        if self._local_embedding_model is None:
            with self._local_embedding_lock:
                if self._local_embedding_model is None:
                    try:
                        from fastembed import TextEmbedding
                    except ImportError as exc:
                        raise AIServiceError("本地 Embedding 依赖尚未安装") from exc
                    settings.local_embedding_cache_path.mkdir(parents=True, exist_ok=True)
                    self._local_embedding_model = TextEmbedding(
                        model_name=settings.embedding_model,
                        cache_dir=str(settings.local_embedding_cache_path),
                    )
        encoder = self._local_embedding_model.query_embed if query else self._local_embedding_model.embed
        try:
            vectors = [vector.tolist() for vector in encoder(texts)]
        except Exception as exc:
            raise AIServiceError(f"本地 Embedding 生成失败：{exc}") from exc
        if len(vectors) != len(texts):
            raise AIServiceError("本地 Embedding 返回数量与输入不一致")
        if any(len(vector) != settings.embedding_dimension for vector in vectors):
            raise AIServiceError("本地 Embedding 维度与 EMBEDDING_DIMENSION 不一致")
        return vectors

    def embeddings(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        if settings.ai_offline_mode:
            return [self._offline_embedding(text) for text in texts]
        if settings.embedding_provider == "local":
            return self._local_embeddings(texts, query=query)
        data = self._post(
            "/embeddings",
            {"model": settings.embedding_model, "input": texts, "encoding_format": "float"},
        )
        items = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item["embedding"] for item in items]
        if len(vectors) != len(texts):
            raise AIServiceError("Embedding 返回数量与输入不一致")
        if any(len(vector) != settings.embedding_dimension for vector in vectors):
            raise AIServiceError("Embedding 维度与 EMBEDDING_DIMENSION 不一致")
        return vectors

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1400,
        json_mode: bool = False,
    ) -> Completion:
        if settings.ai_offline_mode:
            context = messages[-1]["content"] if messages else ""
            if "【证据 1】" not in context:
                return Completion("资料库中没有足够证据回答这个问题。")
            first = context.split("【证据 1】", 1)[1].split("【证据 2】", 1)[0].strip()
            excerpt = first[-420:]
            return Completion(f"根据当前知识库资料，可以确认以下内容：{excerpt} [1]", 100, 80)
        payload: dict[str, Any] = {
            "model": model or settings.chat_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._post("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIServiceError("AI 服务返回格式无效") from exc
        usage = data.get("usage") or {}
        return Completion(
            content=content,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )

    def rerank(self, question: str, candidates: list[dict[str, str]]) -> dict[str, int]:
        if settings.ai_offline_mode:
            return {item["id"]: 2 for item in candidates}
        compact = [{"id": item["id"], "text": item["text"][:1200]} for item in candidates]
        prompt = (
            "请评估每条资料对问题的直接相关程度，0=无关，1=弱相关，2=相关，3=可直接回答。"
            "只返回 JSON：{\"items\":[{\"id\":\"...\",\"score\":0}]}。\n"
            f"问题：{question}\n候选资料：{json.dumps(compact, ensure_ascii=False)}"
        )
        try:
            result = self.complete(
                [{"role": "system", "content": "你是严谨的中文检索重排器。"}, {"role": "user", "content": prompt}],
                model=settings.rerank_model or settings.chat_model,
                temperature=0,
                max_tokens=800,
                json_mode=True,
            )
            raw = re.sub(r"^```(?:json)?|```$", "", result.content.strip(), flags=re.MULTILINE).strip()
            parsed = json.loads(raw)
            return {
                str(item["id"]): max(0, min(3, int(item["score"])))
                for item in parsed.get("items", [])
                if "id" in item and "score" in item
            }
        except (AIServiceError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return {}


ai_client = AIClient()
