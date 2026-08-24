from __future__ import annotations

from collections.abc import Sequence

from lodex.contracts import EmbeddingResult, OllamaStatus


class FakeEmbedder:
    def __init__(self, dimension: int = 3) -> None:
        self.dimension = dimension
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        values = list(texts)
        self.document_calls.append(values)
        return self._result(len(values))

    def embed_query(self, text: str) -> EmbeddingResult:
        self.query_calls.append(text)
        return self._result(1)

    def status(self) -> OllamaStatus:
        return OllamaStatus(
            host="fake://local",
            reachable=True,
            version="test",
            model="fake",
            model_installed=True,
            model_digest="fake-digest",
            dimension=self.dimension,
            expected_dimension=self.dimension,
            compatible=True,
        )

    def _result(self, count: int) -> EmbeddingResult:
        vector = tuple(0.1 for _ in range(self.dimension))
        return EmbeddingResult(
            embeddings=tuple(vector for _ in range(count)),
            provider="fake",
            model="fake",
            model_digest="fake-digest",
            dimension=self.dimension,
        )
