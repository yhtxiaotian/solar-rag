import httpx

from app.core.config import settings
from app.services.ai import AIClient


def test_offline_embeddings_are_deterministic(monkeypatch):
    monkeypatch.setattr(settings, "ai_offline_mode", True)
    client = AIClient()
    first, second = client.embeddings(["分布式光伏并网", "分布式光伏并网"])
    assert first == second
    assert len(first) == settings.embedding_dimension


def test_ai_request_retries_transient_failure(monkeypatch):
    monkeypatch.setattr(settings, "ai_offline_mode", False)
    monkeypatch.setattr(settings, "embedding_provider", "openai")
    monkeypatch.setattr(settings, "ai_base_url", "https://ai.example/v1")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr(settings, "chat_model", "chat")
    monkeypatch.setattr(settings, "embedding_model", "embedding")
    monkeypatch.setattr("app.services.ai.time.sleep", lambda _: None)
    calls = 0

    def fake_post(url, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("temporary connection failure")
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"data": [{"index": 0, "embedding": [0.0] * settings.embedding_dimension}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    assert len(AIClient().embeddings(["光伏"])[0]) == settings.embedding_dimension
    assert calls == 2


def test_local_embedding_uses_query_encoder(monkeypatch):
    monkeypatch.setattr(settings, "ai_offline_mode", False)
    monkeypatch.setattr(settings, "embedding_provider", "local")
    client = AIClient()

    class Vector:
        def tolist(self):
            return [0.0] * settings.embedding_dimension

    class LocalModel:
        def embed(self, texts):
            return [Vector() for _ in texts]

        def query_embed(self, texts):
            return [Vector() for _ in texts]

    client._local_embedding_model = LocalModel()
    assert len(client.embeddings(["光伏问题"], query=True)[0]) == settings.embedding_dimension
