from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from lodex.contracts import EmbeddingResult, OllamaStatus


def downgrade_schema(connection: sqlite3.Connection, version: int) -> None:
    """Recreate the pre-origin schema for migration tests without changing vectors."""
    assert version in (1, 2)
    connection.execute("DROP INDEX sessions_kind_idx")
    for column in ("kind", "provenance_json", "provenance_indexed"):
        connection.execute(f"ALTER TABLE sessions DROP COLUMN {column}")
    if version == 1:
        connection.execute("DROP INDEX sessions_source_idx")
        connection.execute("ALTER TABLE sessions DROP COLUMN source")
    connection.execute(f"PRAGMA user_version = {version}")
    connection.execute(
        "UPDATE metadata SET value = ? WHERE key = 'schema_version'", (str(version),)
    )
    connection.commit()


class FakeEmbedder:
    def __init__(
        self,
        dimension: int = 3,
        *,
        provider: str = "fake",
        model: str = "fake",
        digest: str = "fake-digest",
    ) -> None:
        self.dimension = dimension
        self.provider = provider
        self.model = model
        self.digest = digest
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
            model=self.model,
            model_installed=True,
            model_digest=self.digest,
            dimension=self.dimension,
            expected_dimension=self.dimension,
            compatible=True,
        )

    def _result(self, count: int) -> EmbeddingResult:
        vector = tuple(0.1 for _ in range(self.dimension))
        return EmbeddingResult(
            embeddings=tuple(vector for _ in range(count)),
            provider=self.provider,
            model=self.model,
            model_digest=self.digest,
            dimension=self.dimension,
        )
