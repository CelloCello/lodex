from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
import pytest

from lodex.embedding import (
    QUERY_INSTRUCTION,
    EmbeddingConfigurationError,
    EmbeddingContractError,
    ModelNotFoundError,
    OllamaEmbedder,
    OllamaUnavailableError,
)


class TransientResponseError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class FakeOllamaClient:
    def __init__(
        self,
        *,
        dimension: int = 3,
        model: str = "test-model",
        digest: str = "sha256:test",
        failures: Sequence[Exception] = (),
    ) -> None:
        self.dimension = dimension
        self.model = model
        self.digest = digest
        self.failures = list(failures)
        self.embed_calls: list[dict[str, Any]] = []

    def version(self) -> object:
        return {"version": "0.32.3"}

    def list(self) -> object:
        models = [] if not self.model else [{"model": self.model, "digest": self.digest}]
        return {"models": models}

    def embed(
        self,
        *,
        model: str,
        input: Sequence[str],
        truncate: bool,
        keep_alive: str,
    ) -> object:
        self.embed_calls.append(
            {
                "model": model,
                "input": list(input),
                "truncate": truncate,
                "keep_alive": keep_alive,
            }
        )
        if self.failures:
            raise self.failures.pop(0)
        embeddings = []
        for text in input:
            marker = (
                float(int(text.rsplit("-", maxsplit=1)[-1])) if text.startswith("item-") else 1.0
            )
            embeddings.append([marker] + [0.0] * (self.dimension - 1))
        return {"embeddings": embeddings}


def make_embedder(client: FakeOllamaClient, **overrides: Any) -> OllamaEmbedder:
    return OllamaEmbedder(
        host="127.0.0.1:11434",
        model="test-model",
        expected_dimension=3,
        client=client,
        **overrides,
    )


def test_batch_ordering_and_provider_identity() -> None:
    client = FakeOllamaClient()
    embedder = make_embedder(client, batch_size=4)

    result = embedder.embed_documents([f"item-{index}" for index in range(10)])

    assert [vector[0] for vector in result.embeddings] == [float(i) for i in range(10)]
    assert len(client.embed_calls) == 3
    assert result.model_digest == "sha256:test"
    assert result.dimension == 3


def test_documents_remain_raw_and_query_gets_instruction() -> None:
    client = FakeOllamaClient()
    embedder = make_embedder(client)

    embedder.embed_documents(["raw document"])
    embedder.embed_query("why did this test fail?")

    assert client.embed_calls[0]["input"] == ["raw document"]
    assert client.embed_calls[1]["input"] == [f"{QUERY_INSTRUCTION}why did this test fail?"]
    assert all(call["truncate"] is False for call in client.embed_calls)
    assert all(call["keep_alive"] == "10m" for call in client.embed_calls)


def test_missing_model_has_pull_guidance() -> None:
    client = FakeOllamaClient(model="")
    embedder = make_embedder(client)

    with pytest.raises(ModelNotFoundError, match="ollama pull test-model"):
        embedder.embed_documents(["document"])


def test_timeout_retries_twice_then_preserves_result() -> None:
    client = FakeOllamaClient(failures=[httpx.ReadTimeout("slow"), TransientResponseError(503)])
    sleeps: list[float] = []
    embedder = make_embedder(client, sleep=sleeps.append)

    result = embedder.embed_documents(["document"])

    assert len(result.embeddings) == 1
    assert sleeps == [0.1, 0.2]
    assert len(client.embed_calls) == 3


def test_timeout_after_retries_is_actionable() -> None:
    client = FakeOllamaClient(
        failures=[
            httpx.ReadTimeout("slow"),
            httpx.ReadTimeout("slow"),
            httpx.ReadTimeout("slow"),
        ]
    )
    embedder = make_embedder(client, sleep=lambda _: None)

    with pytest.raises(OllamaUnavailableError, match="slow"):
        embedder.embed_documents(["document"])


def test_dimension_mismatch_and_non_finite_values_fail() -> None:
    mismatch = FakeOllamaClient(dimension=2)
    with pytest.raises(EmbeddingContractError, match="dimension 2"):
        make_embedder(mismatch).embed_documents(["document"])

    class NonFiniteClient(FakeOllamaClient):
        def embed(self, **kwargs: Any) -> object:
            return {"embeddings": [[1.0, float("nan"), 0.0]]}

    with pytest.raises(EmbeddingContractError, match="non-finite"):
        make_embedder(NonFiniteClient()).embed_documents(["document"])


def test_remote_host_is_rejected_before_client_use() -> None:
    with pytest.raises(EmbeddingConfigurationError, match="Remote Ollama hosts"):
        OllamaEmbedder(host="https://ollama.example.com", client=FakeOllamaClient())


def test_loopback_ipv6_and_localhost_are_allowed() -> None:
    assert make_embedder(FakeOllamaClient()).host == "http://127.0.0.1:11434"
    assert OllamaEmbedder(host="http://localhost:11434", client=FakeOllamaClient()).host
    assert OllamaEmbedder(host="http://[::1]:11434", client=FakeOllamaClient()).host


def test_status_reports_version_digest_dimension_and_compatibility() -> None:
    status = make_embedder(FakeOllamaClient()).status()

    assert status.reachable is True
    assert status.version == "0.32.3"
    assert status.model_installed is True
    assert status.model_digest == "sha256:test"
    assert status.dimension == 3
    assert status.compatible is True


def test_status_reports_actual_incompatible_dimension() -> None:
    status = make_embedder(FakeOllamaClient(dimension=2)).status()

    assert status.reachable is True
    assert status.dimension == 2
    assert status.expected_dimension == 3
    assert status.compatible is False
    assert status.error == "Embedding dimension 2 does not match 3"


def test_status_captures_unavailable_runtime() -> None:
    class UnavailableClient(FakeOllamaClient):
        def version(self) -> object:
            raise ConnectionError("not running")

    status = make_embedder(UnavailableClient()).status()

    assert status.reachable is False
    assert status.compatible is False
    assert status.error == "not running"


def test_truncate_false_and_oversize_input_is_rejected_before_request() -> None:
    client = FakeOllamaClient()
    embedder = make_embedder(client, max_input_chars=20)

    with pytest.raises(EmbeddingContractError, match="was not truncated"):
        embedder.embed_documents(["x" * 21])

    assert client.embed_calls == []
