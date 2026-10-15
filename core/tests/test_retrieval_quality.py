from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from lodex_core.history.contracts import SessionKind
from lodex_core.history.retrieval import Retrieval
from lodex_core.history.storage import Storage

from .support.search import QueryEmbedder, build_corpus, insert, session


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


@pytest.mark.parametrize("kind", ["audit", "automation", "unknown"])
def test_relevant_non_direct_origins_remain_first_without_explicit_filter(
    tmp_path: Path, kind: SessionKind
) -> None:
    with Storage(tmp_path / "origins.db", dimension=3) as storage:
        relevant, project = session(
            tmp_path / "relevant.jsonl",
            session_id="relevant",
            created_at="2026-09-01",
            project="path:/project",
            texts=[("Historical evidence", "The requested result.")],
        )
        unrelated, _ = session(
            tmp_path / "unrelated.jsonl",
            session_id="unrelated",
            created_at="2026-09-01",
            project=project,
            texts=[("Another task", "An unrelated implementation.")],
        )
        insert(storage, replace(relevant, kind=kind), project, [(1.0, 0.0, 0.0)])
        insert(storage, replace(unrelated, kind="direct"), project, [(0.0, 1.0, 0.0)])
        retrieval = Retrieval(storage, QueryEmbedder({"semantic paraphrase": (1.0, 0.0, 0.0)}))
        hits = retrieval.search("semantic paraphrase", limit=2)
        assert [hit.session_id for hit in hits] == ["relevant", "unrelated"]
        assert retrieval.search("semantic paraphrase", kind=kind)[0].session_id == "relevant"
