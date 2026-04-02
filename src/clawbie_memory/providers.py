from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import requests


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        """Return embedding vector for input text."""


class InferenceProvider(Protocol):
    def summarize(self, text: str, prompt: str) -> str:
        """Return model-generated summary/reflection text."""


@dataclass
class HttpEmbeddingClient:
    host: str
    model: str
    timeout_seconds: int = 20

    def embed(self, text: str) -> list[float]:
        payload = {"model": self.model, "input": text}
        response = requests.post(self.host, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        body = response.json()

        if isinstance(body.get("embedding"), list):
            return [float(v) for v in body["embedding"]]
        data = body.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict) and isinstance(data[0].get("embedding"), list):
            return [float(v) for v in data[0]["embedding"]]
        raise ValueError("embedding host response missing embedding")


@dataclass
class HttpInferenceClient:
    host: str
    model: str
    timeout_seconds: int = 30

    def summarize(self, text: str, prompt: str) -> str:
        # Prompt text is exact and controlled by ingestion service requirements.
        payload = {"model": self.model, "prompt": prompt, "input": text}
        response = requests.post(self.host, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        body = response.json()

        if isinstance(body.get("response"), str):
            return body["response"].strip()
        if isinstance(body.get("text"), str):
            return body["text"].strip()

        choices = body.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            text_candidate = choices[0].get("text") or choices[0].get("message", {}).get("content")
            if isinstance(text_candidate, str):
                return text_candidate.strip()

        raise ValueError("inference host response missing summary text")
