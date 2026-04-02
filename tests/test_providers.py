from __future__ import annotations

from dataclasses import dataclass

from memory_engine.providers import HttpEmbeddingProvider, HttpInferenceProvider


@dataclass
class DummyResponse:
    payload: dict | None = None
    text: str = ""
    json_error: Exception | None = None

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        if self.json_error is not None:
            raise self.json_error
        if self.payload is None:
            return {}
        return self.payload


def test_embedding_provider_supports_openai_style_data_list(monkeypatch) -> None:
    def fake_post(url, json, timeout):  # noqa: ANN001
        return DummyResponse(payload={"data": [{"embedding": [0.1, 0.2]}]})

    monkeypatch.setattr("requests.post", fake_post)
    provider = HttpEmbeddingProvider(url="http://127.0.0.1:1", model="m", timeout_seconds=1)
    assert provider.embed("hello") == [0.1, 0.2]


def test_embedding_provider_supports_embeddings_plural(monkeypatch) -> None:
    def fake_post(url, json, timeout):  # noqa: ANN001
        return DummyResponse(payload={"embeddings": [[0.3, 0.4]]})

    monkeypatch.setattr("requests.post", fake_post)
    provider = HttpEmbeddingProvider(url="http://127.0.0.1:1", model="m", timeout_seconds=1)
    assert provider.embed("hello") == [0.3, 0.4]


def test_inference_provider_supports_response_key(monkeypatch) -> None:
    def fake_post(url, json, timeout):  # noqa: ANN001
        return DummyResponse(payload={"response": "summary text"})

    monkeypatch.setattr("requests.post", fake_post)
    provider = HttpInferenceProvider(url="http://127.0.0.1:1", model="m", timeout_seconds=1)
    assert provider.summarise("hello", "summarise this in 20 lines or less") == "summary text"


def test_inference_provider_supports_line_delimited_json(monkeypatch) -> None:
    def fake_post(url, json, timeout):  # noqa: ANN001
        return DummyResponse(
            json_error=ValueError("bad json"),
            text='{"response":"partial","done":false}\n{"response":"final summary","done":true}',
        )

    monkeypatch.setattr("requests.post", fake_post)
    provider = HttpInferenceProvider(url="http://127.0.0.1:1", model="m", timeout_seconds=1)
    assert provider.summarise("hello", "summarise this in 20 lines or less") == "final summary"
