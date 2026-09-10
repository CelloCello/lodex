from __future__ import annotations

import json
from pathlib import Path

import pytest

from lodex.codex_parser import parse_codex_session

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("fixture", "users", "answers"),
    [
        (
            "approval-audit.jsonl",
            ["ApprovalAuditFixture: assess the proposed read of README.md."],
            ["The proposed action only reads a project file."],
        ),
        (
            "automation.jsonl",
            ["AutomationFixture: summarize changes since the last check.", ""],
            ["The parser now preserves requests.", "No additional changes."],
        ),
        (
            "unknown-origin.jsonl",
            ["UnknownOriginFixture: explain the decision."] * 2,
            ["Keep retrieval local.", "Local storage supports offline retrieval."],
        ),
    ],
)
def test_transcript_origins_preserve_content_without_classification(
    fixture: str, users: list[str], answers: list[str]
) -> None:
    session = parse_codex_session(FIXTURES / fixture)
    assert [turn.user_text for turn in session.turns] == users
    assert [turn.assistant_text for turn in session.turns] == answers
    assert [turn.ordinal for turn in session.turns] == list(range(len(users)))
    assert len({turn.turn_id for turn in session.turns}) == len(users)
    assert all(turn.status == "completed" for turn in session.turns)
    assert not session.warnings


def test_response_only_users_preserve_legacy_boundaries_and_filter_blocks(tmp_path: Path) -> None:
    path = tmp_path / "response-only.jsonl"
    records = [
        {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "# AGENTS.md instructions\n<INSTRUCTIONS>\ninternal\n</INSTRUCTIONS>",
                },
                {
                    "type": "input_text",
                    "text": "<environment_context>internal</environment_context>",
                },
                {"type": "input_image", "image_url": "ignored"},
                {"type": "input_text", "text": "Find the requirement"},
                {"type": "input_text", "text": "and its decision"},
            ],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": "Found it"},
            ],
        },
        {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Follow up"},
            ],
        },
    ]
    path.write_text("\n".join(json.dumps({"type": "response_item", "payload": p}) for p in records))
    session = parse_codex_session(path)
    assert [t.user_text for t in session.turns] == [
        "Find the requirement\nand its decision",
        "Follow up",
    ]
    assert [t.status for t in session.turns] == ["completed", "active"]


@pytest.mark.parametrize("sources", [("event", "response"), ("response", "event")])
def test_user_dedup_preserves_repetition_and_mixed_steering(
    tmp_path: Path, sources: tuple[str, str]
) -> None:
    path = tmp_path / "mixed.jsonl"
    records: list[dict[str, object]] = [
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "one"}},
    ]
    for message, representations in [
        ("Do it", sources),
        ("Do it", sources),
        ("Response-only steering", ("response",)),
        ("Event-only steering", ("event",)),
    ]:
        for source in representations:
            records.append(
                {"type": "event_msg", "payload": {"type": "user_message", "message": message}}
                if source == "event"
                else {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": message}],
                    },
                }
            )
    records.append({"type": "event_msg", "payload": {"type": "task_complete"}})
    path.write_text("\n".join(json.dumps(r) for r in records))
    session = parse_codex_session(path)
    assert len(session.turns) == 1
    assert session.turns[0].user_text == (
        "Do it\n\nDo it\n\nResponse-only steering\n\nEvent-only steering"
    )


def test_completed_turn_metadata_and_stable_order() -> None:
    session = parse_codex_session(FIXTURES / "completed.jsonl")

    assert session.session_id == "session-completed"
    assert session.cwd == "/work/example"
    assert session.metadata["cli_version"] == "1.2.3"
    assert len(session.turns) == 1
    turn = session.turns[0]
    assert turn.turn_id == "turn-completed"
    assert turn.ordinal == 0
    assert turn.status == "completed"
    assert turn.user_text == "How does the parser work?"
    assert turn.assistant_text == "It normalizes safe transcript turns."


def test_excluded_internal_and_tool_content() -> None:
    session = parse_codex_session(FIXTURES / "completed.jsonl")
    corpus = "\n".join(f"{turn.user_text}\n{turn.assistant_text}" for turn in session.turns)

    assert "secret developer instructions" not in corpus
    assert "duplicated injected user wrapper" not in corpus
    assert "private chain of thought" not in corpus
    assert "private reasoning" not in corpus
    assert "I am checking" not in corpus
    assert "Still checking" not in corpus
    assert "very large tool output" not in corpus


def test_aborted_turn_is_retained_with_status() -> None:
    session = parse_codex_session(FIXTURES / "aborted.jsonl")

    assert len(session.turns) == 1
    assert session.turns[0].status == "aborted"
    assert session.turns[0].assistant_text == ""


def test_active_turn_is_flushed_at_eof_without_commentary() -> None:
    session = parse_codex_session(FIXTURES / "active.jsonl")

    assert len(session.turns) == 1
    assert session.turns[0].status == "active"
    assert session.turns[0].assistant_text == ""


def test_historical_agent_message_without_phase_is_final_fallback() -> None:
    session = parse_codex_session(FIXTURES / "historical-no-phase.jsonl")

    assert session.session_id == "session-historical"
    assert session.turns[0].status == "completed"
    assert session.turns[0].assistant_text == "The old implementation used a fallback event."
    assert session.turns[0].turn_id.startswith("turn-")


def test_legacy_session_without_task_events_preserves_each_turn() -> None:
    session = parse_codex_session(FIXTURES / "legacy-multi-turn.jsonl")

    assert len(session.turns) == 2
    assert [turn.ordinal for turn in session.turns] == [0, 1]
    assert [turn.status for turn in session.turns] == ["completed", "completed"]
    assert [turn.user_text for turn in session.turns] == [
        "Explain the first implementation",
        "What changed later?",
    ]
    assert [turn.assistant_text for turn in session.turns] == [
        "The first implementation used files.",
        "The later implementation used SQLite.",
    ]
    assert session.turns[0].turn_id != session.turns[1].turn_id
    assert "environment_context" not in "\n".join(turn.user_text for turn in session.turns)


def test_modern_user_steering_is_accumulated_in_one_turn() -> None:
    session = parse_codex_session(FIXTURES / "modern-steering.jsonl")

    assert len(session.turns) == 1
    assert session.turns[0].turn_id == "turn-steering"
    assert session.turns[0].status == "completed"
    assert session.turns[0].user_text == ("Implement the parser\n\nAlso preserve steering messages")


def test_forked_session_normalizes_parent_turns_to_canonical_session_id() -> None:
    session = parse_codex_session(FIXTURES / "forked-session.jsonl")

    assert session.session_id == "child-session"
    assert session.created_at == "2026-08-21T01:00:00Z"
    assert [turn.turn_id for turn in session.turns] == ["parent-turn", "child-turn"]
    assert {turn.session_id for turn in session.turns} == {"child-session"}


def test_archived_path_is_normalized_as_archived() -> None:
    session = parse_codex_session(FIXTURES / "archived_sessions" / "archived.jsonl")

    assert session.archived is True
    assert session.turns[0].assistant_text == "Archived answer"


def test_malformed_and_unknown_records_warn_but_valid_turn_survives() -> None:
    session = parse_codex_session(FIXTURES / "truncated.jsonl")

    assert len(session.turns) == 1
    assert session.turns[0].user_text == "Keep valid records"
    assert session.turns[0].assistant_text == "This final line is still retained."
    assert {warning.code for warning in session.warnings} == {
        "malformed_json",
        "unknown_record_type",
    }


def test_known_schema_noise_is_ignored_and_unknown_types_are_aggregated() -> None:
    session = parse_codex_session(FIXTURES / "schema-noise.jsonl")

    assert len(session.turns) == 1
    assert session.turns[0].user_text == "Keep only meaningful content"
    assert session.turns[0].assistant_text == "Meaningful content is retained."
    assert [(warning.code, warning.line_number) for warning in session.warnings] == [
        ("unknown_event_type", 9),
        ("unknown_response_type", 11),
    ]


def test_content_hash_and_synthetic_id_are_deterministic() -> None:
    first = parse_codex_session(FIXTURES / "historical-no-phase.jsonl")
    second = parse_codex_session(FIXTURES / "historical-no-phase.jsonl")

    assert first.turns[0].turn_id == second.turns[0].turn_id
    assert first.turns[0].content_hash == second.turns[0].content_hash
