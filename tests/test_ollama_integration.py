from __future__ import annotations

import math

import pytest

from lodex.embedding import DEFAULT_DIMENSION, DEFAULT_MODEL, OllamaEmbedder


@pytest.mark.ollama
def test_local_qwen_embedding_contract() -> None:
    embedder = OllamaEmbedder(model=DEFAULT_MODEL, expected_dimension=DEFAULT_DIMENSION)

    result = embedder.embed_documents(
        [
            "The parser normalizes Codex session history.",
            "SQLite stores chunks for hybrid retrieval.",
        ]
    )

    assert len(result.embeddings) == 2
    assert all(len(vector) == 1_024 for vector in result.embeddings)
    assert all(all(math.isfinite(value) for value in vector) for vector in result.embeddings)
    norms = [math.sqrt(sum(value * value for value in vector)) for vector in result.embeddings]
    assert norms == pytest.approx([1.0, 1.0], abs=1e-5)
    assert result.model == "qwen3-embedding:0.6b"
    assert result.model_digest
