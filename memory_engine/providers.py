from __future__ import annotations

import json
from typing import Protocol

import requests


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class InferenceProvider(Protocol):
    def summarise(self, text: str, prompt: str) -> str:
        raise NotImplementedError


class HttpEmbeddingProvider:
    def __init__(self, url: str, model: str, timeout_seconds: float) -> None:
        self._url = url
        self._model = model
        self._timeout_seconds = timeout_seconds

    def embed(self, text: str) -> list[float]:
        response = requests.post(
            self._url,
            json={"model": self._model, "input": text},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        embedding = payload.get("embedding")
        if not isinstance(embedding, list):
            embeddings = payload.get("embeddings")
            if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
                embedding = embeddings[0]
        if not isinstance(embedding, list):
            data = payload.get("data")
            if isinstance(data, list) and data and isinstance(data[0], dict):
                embedding = data[0].get("embedding")
        if not isinstance(embedding, list):
            raise ValueError("Embedding response missing embedding list")
        return [float(value) for value in embedding]


class HttpInferenceProvider:
    def __init__(self, url: str, model: str, timeout_seconds: float) -> None:
        self._url = url
        self._model = model
        self._timeout_seconds = timeout_seconds

    def summarise(self, text: str, prompt: str) -> str:
        response = requests.post(
            self._url,
            json={
                "model": self._model,
                "prompt": f"{prompt}\n\n{text}",
                "input": text,
                "stream": False,
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            # Some local inference APIs stream line-delimited JSON; parse the last JSON object.
            payload = {}
            for line in response.text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue
        summary = payload.get("output")
        if not isinstance(summary, str):
            summary = payload.get("response")
        if not isinstance(summary, str):
            summary = payload.get("text")
        if not isinstance(summary, str):
            choices = payload.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                summary = choices[0].get("text") or choices[0].get("message", {}).get("content")
        if not isinstance(summary, str):
            raise ValueError("Inference response missing output string")
        return summary.strip()
