from __future__ import annotations

from pathlib import Path

from lodex.retrieval import Retrieval
from lodex.storage import Storage
from tests.test_search import QueryEmbedder, build_corpus


def test_synthetic_lexical_top1_and_semantic_top3(tmp_path: Path) -> None:
    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        chunk_ids = build_corpus(storage, tmp_path)
        retrieval = Retrieval(
            storage,
            QueryEmbedder(
                {
                    "src/lodex/storage.py": (0.0, 0.0, 1.0),
                    "如何避免建立一半的索引": (0.9, 0.1, 0.0),
                }
            ),
        )

        lexical = retrieval.search("src/lodex/storage.py", limit=3)
        semantic = retrieval.search("如何避免建立一半的索引", limit=3)

        assert lexical[0].chunk_id == chunk_ids["a"][0]
        assert chunk_ids["a"][1] in {hit.chunk_id for hit in semantic[:3]}
