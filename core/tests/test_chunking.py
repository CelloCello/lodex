from __future__ import annotations

from itertools import pairwise

from lodex_core.history.chunking import chunk_turn, format_turn, split_text
from lodex_core.history.contracts import TurnRecord


def make_turn(user: str, assistant: str) -> TurnRecord:
    return TurnRecord(
        session_id="session-1",
        turn_id="turn-1",
        ordinal=0,
        status="completed",
        started_at=None,
        completed_at=None,
        user_text=user,
        assistant_text=assistant,
        content_hash="source-hash",
    )


def test_short_turn_remains_one_semantic_chunk() -> None:
    turn = make_turn("Where is the config?", "It is in config.py.")

    chunks = chunk_turn(turn)

    assert len(chunks) == 1
    assert chunks[0].text == format_turn(turn)
    assert chunks[0].chunk_index == 0
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == len(format_turn(turn))


def test_oversized_turn_splits_at_paragraph_boundaries_with_overlap() -> None:
    paragraphs = [f"paragraph-{index} " + ("x" * 90) for index in range(12)]
    text = "\n\n".join(paragraphs)

    slices = split_text(text, max_chars=400, overlap_chars=60)

    assert len(slices) > 1
    assert all(len(part.text) <= 400 for part in slices)
    assert all(part.text.endswith("x") for part in slices)
    for previous, current in pairwise(slices):
        assert current.start < previous.end
        assert previous.end - current.start <= 60


def test_no_paragraph_boundary_falls_back_to_hard_limit() -> None:
    slices = split_text("x" * 950, max_chars=400, overlap_chars=50)

    assert [len(part.text) for part in slices] == [400, 400, 250]
    assert [part.start for part in slices] == [0, 350, 700]


def test_chunk_ids_are_stable_and_content_sensitive() -> None:
    turn = make_turn("Question", "Answer")

    first = chunk_turn(turn)
    second = chunk_turn(turn)
    changed = chunk_turn(make_turn("Question", "Different answer"))

    assert first == second
    assert first[0].chunk_id != changed[0].chunk_id


def test_invalid_chunk_settings_are_rejected() -> None:
    for max_chars, overlap in ((0, 0), (100, -1), (100, 100)):
        try:
            split_text("content", max_chars=max_chars, overlap_chars=overlap)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid chunk settings must fail")
