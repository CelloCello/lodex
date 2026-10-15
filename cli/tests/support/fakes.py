from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from lodex_core.history.contracts import EmbeddingResult, OllamaStatus


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


def run_gated_mcp_server(
    gate_directory: str,
    *,
    hold_count: int = 1,
    worker_limit: int = 40,
    fail_after_release: bool = False,
) -> None:
    """Run stdio with bounded workers and hold the first SQLite operations open."""
    import json
    import threading
    import time
    from pathlib import Path
    from typing import Any, Self

    import anyio
    import pytest

    from lodex_cli.mcp_server import create_server
    from lodex_core.history import queries, storage

    gate = Path(gate_directory)
    main_thread = threading.get_ident()
    opened = 0
    counter_lock = threading.Lock()

    class GatedStorage(storage.Storage):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.owner_thread = threading.get_ident()
            self.operation_id = 0
            super().__init__(*args, **kwargs)

        def __enter__(self) -> Self:
            nonlocal opened
            assert threading.get_ident() == self.owner_thread
            with counter_lock:
                opened += 1
                self.operation_id = opened
            (gate / f"opened-{self.operation_id}").touch()
            if self.operation_id <= hold_count:
                started = "started" if self.operation_id == 1 else f"started-{self.operation_id}"
                (gate / started).write_text(
                    json.dumps(
                        {
                            "worker": self.owner_thread,
                            "main": main_thread,
                        }
                    )
                )
                deadline = time.monotonic() + 15
                while not (gate / "release").exists():
                    if time.monotonic() >= deadline:
                        self.close()
                        raise TimeoutError("Test did not release the SQLite operation")
                    time.sleep(0.01)
                if fail_after_release:
                    self.close()
                    raise RuntimeError("Delayed SQLite failure")
            return self

        def close(self) -> None:
            assert threading.get_ident() == self.owner_thread
            super().close()
            if 0 < self.operation_id <= hold_count:
                closed = "closed" if self.operation_id == 1 else f"closed-{self.operation_id}"
                (gate / closed).touch()

    fake = FakeEmbedder(dimension=3, provider="ollama", model="test-model", digest="sha256:test")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(queries, "Storage", GatedStorage)
        patch.setattr(storage, "Storage", GatedStorage)
        patch.setattr(queries, "create_embedder", lambda config: fake)

        async def serve() -> None:
            await create_server(worker_limit=worker_limit).run_stdio_async()

        anyio.run(serve)
