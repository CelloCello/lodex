from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from lodex_core.history.contracts import (
    SESSION_KINDS,
)
from lodex_core.history.retrieval import Retrieval, RetrievalError, fts_query
from lodex_core.history.storage import Storage

from .support.search import QueryEmbedder, build_corpus, insert, session


@pytest.mark.parametrize("lexical_only", [True, False])
def test_kind_filter_combines_with_project_and_date_and_keeps_unknown(
    tmp_path: Path, lexical_only: bool
) -> None:
    with Storage(tmp_path / "kinds.db", dimension=3) as storage:
        for kind in SESSION_KINDS:
            for suffix, project, date in (
                ("match", "path:/target", "2026-09-01"),
                ("wrong-project", "path:/elsewhere", "2026-09-01"),
                ("wrong-date", "path:/target", "2026-08-01"),
            ):
                record, _ = session(
                    tmp_path / f"{kind}-{suffix}.jsonl",
                    session_id=f"{kind}-{suffix}",
                    created_at=date,
                    project=project,
                    texts=[("needle", "Answer")],
                )
                insert(storage, replace(record, kind=kind), project, [(1.0, 0.0, 0.0)])
        retrieval = Retrieval(storage, QueryEmbedder({"needle": (1.0, 0.0, 0.0)}))
        for kind in SESSION_KINDS:
            hits = retrieval.search(
                "needle",
                kind=kind,
                source="codex",
                project="path:/target",
                since="2026-09-01",
                until="2026-09-01",
                lexical_only=lexical_only,
            )
            assert [hit.session_id for hit in hits] == [f"{kind}-match"]
            assert hits[0].kind == kind
        with pytest.raises(RetrievalError, match="Unknown session kind"):
            retrieval.search("needle", kind="invalid")
        storage.mark_missing(set(), source="codex")
        stats = storage.status().session_kind_stats
        assert stats is not None
        assert stats.total_sessions == 0
        assert all(count == 0 for count in stats.counts.values())


def test_vector_kind_filter_expands_past_unrelated_origin_candidates(tmp_path: Path) -> None:
    with Storage(tmp_path / "pool.db", dimension=3) as storage:
        for index in range(105):
            record, project = session(
                tmp_path / f"{index}.jsonl",
                session_id=str(index),
                created_at="2026-09-01",
                project="path:/target",
                texts=[("A task", "A response")],
            )
            insert(storage, replace(record, kind="direct"), project, [(1.0, 0.0, 0.0)])
        audit, project = session(
            tmp_path / "audit.jsonl",
            session_id="audit",
            created_at="2026-09-01",
            project="path:/target",
            texts=[("Permission request", "Approved")],
        )
        insert(storage, replace(audit, kind="audit"), project, [(0.0, 1.0, 0.0)])
        hits = storage.vector_candidates((1.0, 0.0, 0.0), limit=1, kind="audit")
        assert [hit["session_id"] for hit in hits] == ["audit"]


def test_unfiltered_search_expands_past_missing_candidates(tmp_path: Path) -> None:
    with Storage(tmp_path / "missing-pool.db", dimension=3) as storage:
        stale, project = session(
            tmp_path / "stale.jsonl",
            session_id="stale",
            created_at="2026-09-01",
            project="path:/project",
            texts=[(f"Old task {i}", "Answer") for i in range(310)],
        )
        insert(storage, stale, project, [(1.0, 0.0, 0.0)] * 310)
        live_path = tmp_path / "live.jsonl"
        live, _ = session(
            live_path,
            session_id="live",
            created_at="2026-09-01",
            project=project,
            texts=[("Current task", "Answer")],
        )
        insert(storage, live, project, [(0.0, 1.0, 0.0)])
        storage.mark_missing({str(live_path)}, source="codex")
        retrieval = Retrieval(storage, QueryEmbedder({"semanticneedle": (1.0, 0.0, 0.0)}))

        assert [hit.session_id for hit in retrieval.search("semanticneedle")] == ["live"]
        assert [hit.session_id for hit in retrieval.search("semanticneedle", source="codex")] == [
            "live"
        ]
        storage.mark_missing(set(), source="codex")
        assert retrieval.search("semanticneedle") == ()


@pytest.mark.parametrize("exclude_missing", [False, True])
def test_eligible_candidates_beyond_vec0_k_limit(tmp_path: Path, exclude_missing: bool) -> None:
    with Storage(tmp_path / "large-pool.db", dimension=3) as storage:
        direct, project = session(
            tmp_path / "direct.jsonl",
            session_id="direct",
            created_at="2026-09-01",
            project="path:/project",
            texts=[(f"Direct task {i}", "Result") for i in range(4100)],
        )
        insert(storage, replace(direct, kind="direct"), project, [(1.0, 0.0, 0.0)] * 4100)
        audit, _ = session(
            tmp_path / "audit.jsonl",
            session_id="audit",
            created_at="2026-09-01",
            project=project,
            texts=[("Audit A", "Evidence"), ("Audit B", "More evidence")],
        )
        insert(storage, replace(audit, kind="audit"), project, [(0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)])
        if exclude_missing:
            storage.mark_missing({str(tmp_path / "audit.jsonl")}, source="codex")
        hits = storage.vector_candidates(
            (1.0, 0.0, 0.0),
            limit=2,
            kind=None if exclude_missing else "audit",
            project=None if exclude_missing else project,
        )
        assert [hit["turn_id"] for hit in hits] == ["audit-turn-0", "audit-turn-1"]
        assert [hit["distance"] for hit in hits] == pytest.approx([2**0.5, 2])


def test_hybrid_search_ranks_identifier_and_semantic_query(tmp_path: Path) -> None:
    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        chunk_ids = build_corpus(storage, tmp_path)
        embedder = QueryEmbedder(
            {
                "StorageCompatibilityError": (0.0, 0.0, 1.0),
                "避免索引寫到一半": (0.9, 0.1, 0.0),
            }
        )
        retrieval = Retrieval(storage, embedder)

        lexical = retrieval.search("StorageCompatibilityError", limit=3)
        semantic = retrieval.search("避免索引寫到一半", limit=3)

        assert lexical[0].chunk_id == chunk_ids["a"][0]
        assert lexical[0].source == "codex"
        assert lexical[0].lexical_rank == 1
        assert chunk_ids["a"][1] in {hit.chunk_id for hit in semantic[:3]}


def test_project_date_filters_and_empty_results(tmp_path: Path) -> None:
    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        build_corpus(storage, tmp_path)
        retrieval = Retrieval(storage, QueryEmbedder({}))

        filtered = retrieval.search(
            "transaction",
            project="path:/project-a",
            since="2026-08-01",
            until="2026-08-31",
        )
        empty = retrieval.search("transaction", project="path:/missing")
        wrong_source = retrieval.search("transaction", source="other-agent")

        assert filtered
        assert all(hit.project == "path:/project-a" for hit in filtered)
        assert empty == ()
        assert wrong_source == ()


def test_explicit_lexical_search_does_not_call_embedder(tmp_path: Path) -> None:
    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        chunk_ids = build_corpus(storage, tmp_path)
        embedder = QueryEmbedder({})
        retrieval = Retrieval(storage, embedder)

        results = retrieval.search("StorageCompatibilityError", lexical_only=True)

        assert results[0].chunk_id == chunk_ids["a"][0]
        assert results[0].vector_rank is None
        assert results[0].lexical_rank == 1
        assert embedder.query_calls == []


def test_filtered_vector_search_expands_past_global_candidate_pool(tmp_path: Path) -> None:
    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        decoys, decoy_project = session(
            tmp_path / "decoys.jsonl",
            session_id="decoys",
            created_at="2026-08-10T00:00:00+00:00",
            project="path:/decoys",
            texts=tuple((f"decoy {index}", "globally closer") for index in range(301)),
        )
        wanted, wanted_project = session(
            tmp_path / "wanted.jsonl",
            session_id="wanted",
            created_at="2026-08-10T00:00:00+00:00",
            project="path:/wanted",
            texts=(("wanted", "filtered result"),),
        )
        insert(storage, decoys, decoy_project, tuple((1.0, 0.0, 0.0) for _ in range(301)))
        wanted_ids = insert(storage, wanted, wanted_project, ((0.0, 1.0, 0.0),))

        candidates = storage.vector_candidates(
            (1.0, 0.0, 0.0),
            limit=30,
            project="path:/wanted",
        )

        assert [candidate["chunk_id"] for candidate in candidates] == [wanted_ids[0]]


def test_show_expands_only_bounded_neighboring_turns(tmp_path: Path) -> None:
    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        chunk_ids = build_corpus(storage, tmp_path)
        retrieval = Retrieval(storage, QueryEmbedder({}))

        shown = retrieval.show(chunk_ids["a"][1], context=1)

        assert shown.matched_turn_id == "session-a-turn-1"
        assert [turn.ordinal for turn in shown.turns] == [0, 1, 2]


def test_fts_escaping_and_invalid_filters_are_actionable(tmp_path: Path) -> None:
    assert fts_query('storage.py OR "unterminated') == '"storage.py" OR "OR" OR "unterminated"'
    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        build_corpus(storage, tmp_path)
        retrieval = Retrieval(storage, QueryEmbedder({}))

        with pytest.raises(RetrievalError, match="Invalid ISO"):
            retrieval.search("query", since="not-a-date")
        with pytest.raises(RetrievalError, match="positive"):
            retrieval.search("query", limit=0)
