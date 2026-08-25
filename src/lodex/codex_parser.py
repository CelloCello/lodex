"""Tolerant, read-only normalization of Codex JSONL sessions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from lodex.contracts import ParseWarning, SessionRecord, TurnRecord, TurnStatus

_KNOWN_TOP_LEVEL = {
    "inter_agent_communication_metadata",
    "session_meta",
    "turn_context",
    "event_msg",
    "response_item",
    "world_state",
    "compacted",
}
_IGNORED_EVENT_TYPES = {
    "agent_reasoning",
    "context_compacted",
    "dynamic_tool_call_request",
    "dynamic_tool_call_response",
    "error",
    "exec_command_end",
    "image_generation_end",
    "item_completed",
    "mcp_tool_call_end",
    "patch_apply_end",
    "sub_agent_activity",
    "thread_name_updated",
    "thread_rolled_back",
    "thread_settings_applied",
    "token_count",
    "web_search_end",
}
_IGNORED_RESPONSE_TYPES = {
    "agent_message",
    "custom_tool_call",
    "custom_tool_call_output",
    "function_call",
    "function_call_output",
    "ghost_snapshot",
    "image_generation_call",
    "reasoning",
    "tool_search_call",
    "tool_search_output",
    "web_search_call",
}
_ABORT_EVENT_TYPES = {"task_aborted", "task_cancelled", "turn_aborted"}
_INTERNAL_ENVIRONMENT_CONTEXT = re.compile(
    r"\A<environment_context>[\s\S]*</environment_context>\Z"
)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _content_hash(user_text: str, assistant_text: str) -> str:
    canonical = f"user\0{user_text}\0assistant\0{assistant_text}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def _append_text(existing: str, message: str) -> str:
    return f"{existing}\n\n{message}" if existing else message


def _is_internal_user_message(message: str) -> bool:
    return bool(_INTERNAL_ENVIRONMENT_CONTEXT.fullmatch(message))


def _message_text(payload: Mapping[str, Any]) -> str:
    blocks = payload.get("content")
    if not isinstance(blocks, list):
        return ""
    texts: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") not in {"output_text", "text"}:
            continue
        value = _text(block.get("text"))
        if value:
            texts.append(value)
    return "\n".join(texts)


@dataclass(slots=True)
class _TurnBuilder:
    turn_id: str
    started_at: str | None
    ordinal: int
    explicit_lifecycle: bool = False
    last_activity_at: str | None = None
    user_text: str = ""
    assistant_text: str = ""
    assistant_fallback: str = ""

    @property
    def has_content(self) -> bool:
        return bool(self.user_text or self.assistant_text or self.assistant_fallback)

    @property
    def has_assistant(self) -> bool:
        return bool(self.assistant_text or self.assistant_fallback)


class CodexSessionParser:
    """Parse one Codex session without mutating or locking its source file."""

    def parse(self, source: str | Path) -> SessionRecord:
        path = Path(source)
        warnings: list[ParseWarning] = []
        metadata: dict[str, str] = {}
        session_id = self._session_id_from_path(path)
        created_at: str | None = None
        cwd: str | None = None
        has_session_meta = False
        turns: list[TurnRecord] = []
        current: _TurnBuilder | None = None
        unknown_warning_keys: set[tuple[str, str]] = set()

        def warn_unknown(
            line_number: int,
            code: str,
            record_kind: str,
            message: str,
        ) -> None:
            key = (code, record_kind)
            if key in unknown_warning_keys:
                return
            unknown_warning_keys.add(key)
            warnings.append(ParseWarning(line_number, code, message))

        def ensure_turn(line_number: int, timestamp: str | None, turn_id: str = "") -> _TurnBuilder:
            nonlocal current
            if current is None:
                stable_id = turn_id or self._synthetic_turn_id(session_id, line_number)
                current = _TurnBuilder(
                    stable_id,
                    timestamp,
                    len(turns),
                    last_activity_at=timestamp,
                )
            return current

        def flush(status: TurnStatus, completed_at: str | None = None) -> None:
            nonlocal current
            if current is None:
                return
            if current.has_content:
                assistant = current.assistant_text or current.assistant_fallback
                turns.append(
                    TurnRecord(
                        session_id=session_id,
                        turn_id=current.turn_id,
                        ordinal=current.ordinal,
                        status=status,
                        started_at=current.started_at,
                        completed_at=completed_at,
                        user_text=current.user_text,
                        assistant_text=assistant,
                        content_hash=_content_hash(current.user_text, assistant),
                    )
                )
            current = None

        def flush_implicit_or_active() -> None:
            if current is not None and not current.explicit_lifecycle and current.has_assistant:
                flush("completed", current.last_activity_at)
            else:
                flush("active")

        with path.open("r", encoding="utf-8") as transcript:
            for line_number, raw_line in enumerate(transcript, start=1):
                if not raw_line.strip():
                    continue
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    warnings.append(ParseWarning(line_number, "malformed_json", str(exc)))
                    continue
                if not isinstance(record, Mapping):
                    warnings.append(
                        ParseWarning(line_number, "invalid_record", "JSONL record is not an object")
                    )
                    continue

                record_type = _text(record.get("type"))
                timestamp = _text(record.get("timestamp")) or None
                payload_value = record.get("payload")
                payload = payload_value if isinstance(payload_value, Mapping) else {}

                if record_type == "session_meta":
                    if has_session_meta:
                        continue
                    candidate_id = _text(payload.get("id")) or _text(payload.get("session_id"))
                    if candidate_id:
                        session_id = candidate_id
                    created_at = _text(payload.get("timestamp")) or timestamp or created_at
                    cwd = _text(payload.get("cwd")) or cwd
                    for key in ("cli_version", "model_provider", "originator", "source"):
                        value = _text(payload.get(key))
                        if value:
                            metadata[key] = value
                    has_session_meta = True
                    continue

                if record_type == "turn_context":
                    cwd = _text(payload.get("cwd")) or cwd
                    context_turn_id = _text(payload.get("turn_id"))
                    if current is not None and context_turn_id:
                        current.turn_id = context_turn_id
                    continue

                if record_type == "event_msg":
                    event_type = _text(payload.get("type"))
                    if event_type == "task_started":
                        flush_implicit_or_active()
                        turn_id = _text(payload.get("turn_id"))
                        current = _TurnBuilder(
                            turn_id or self._synthetic_turn_id(session_id, line_number),
                            _text(payload.get("started_at")) or timestamp,
                            len(turns),
                            explicit_lifecycle=True,
                            last_activity_at=timestamp,
                        )
                    elif event_type == "user_message":
                        message = _text(payload.get("message"))
                        if not message or _is_internal_user_message(message):
                            continue
                        if (
                            current is not None
                            and not current.explicit_lifecycle
                            and current.has_assistant
                        ):
                            flush("completed", current.last_activity_at)
                        builder = ensure_turn(line_number, timestamp, _text(payload.get("turn_id")))
                        builder.user_text = _append_text(builder.user_text, message)
                        builder.last_activity_at = timestamp or builder.last_activity_at
                    elif event_type == "agent_message":
                        phase = _text(payload.get("phase"))
                        if phase in {"", "final_answer"}:
                            builder = ensure_turn(
                                line_number, timestamp, _text(payload.get("turn_id"))
                            )
                            message = _text(payload.get("message"))
                            if message:
                                builder.assistant_fallback = _append_text(
                                    builder.assistant_fallback, message
                                )
                                builder.last_activity_at = timestamp or builder.last_activity_at
                    elif event_type == "task_complete":
                        builder = ensure_turn(line_number, timestamp, _text(payload.get("turn_id")))
                        fallback = _text(payload.get("last_agent_message"))
                        if fallback and not builder.assistant_fallback:
                            builder.assistant_fallback = fallback
                        flush("completed", _text(payload.get("completed_at")) or timestamp)
                    elif event_type in _ABORT_EVENT_TYPES:
                        ensure_turn(line_number, timestamp, _text(payload.get("turn_id")))
                        flush("aborted", timestamp)
                    elif event_type not in _IGNORED_EVENT_TYPES:
                        unknown_event_type = event_type or "<missing>"
                        warn_unknown(
                            line_number,
                            "unknown_event_type",
                            unknown_event_type,
                            f"Unsupported event_msg payload type: {unknown_event_type}",
                        )
                    continue

                if record_type == "response_item":
                    item_type = _text(payload.get("type"))
                    if item_type == "message":
                        role = _text(payload.get("role"))
                        phase = _text(payload.get("phase"))
                        is_legacy_assistant = phase == "" and (
                            current is None or not current.explicit_lifecycle
                        )
                        if role == "assistant" and (phase == "final_answer" or is_legacy_assistant):
                            message = _message_text(payload)
                            if message:
                                builder = ensure_turn(line_number, timestamp)
                                builder.assistant_text = _append_text(
                                    builder.assistant_text, message
                                )
                                builder.last_activity_at = timestamp or builder.last_activity_at
                    elif item_type not in _IGNORED_RESPONSE_TYPES:
                        unknown_item_type = item_type or "<missing>"
                        warn_unknown(
                            line_number,
                            "unknown_response_type",
                            unknown_item_type,
                            f"Unsupported response_item payload type: {unknown_item_type}",
                        )
                    continue

                if record_type not in _KNOWN_TOP_LEVEL:
                    unknown_record_type = record_type or "<missing>"
                    warn_unknown(
                        line_number,
                        "unknown_record_type",
                        unknown_record_type,
                        f"Unsupported record type: {unknown_record_type}",
                    )

        flush_implicit_or_active()
        return SessionRecord(
            session_id=session_id,
            source="codex",
            source_path=str(path.resolve()),
            created_at=created_at,
            cwd=cwd,
            archived="archived_sessions" in path.parts,
            turns=tuple(replace(turn, session_id=session_id) for turn in turns),
            warnings=tuple(warnings),
            metadata=metadata,
        )

    @staticmethod
    def _synthetic_turn_id(session_id: str, line_number: int) -> str:
        value = hashlib.sha256(f"{session_id}:{line_number}".encode()).hexdigest()[:16]
        return f"turn-{value}"

    @staticmethod
    def _session_id_from_path(path: Path) -> str:
        stem = path.stem
        marker = "rollout-"
        if stem.startswith(marker):
            candidate = stem.rsplit("-", maxsplit=5)
            if len(candidate) >= 5:
                return "-".join(candidate[-5:])
        return stem


def parse_codex_session(source: str | Path) -> SessionRecord:
    """Convenience wrapper around :class:`CodexSessionParser`."""

    return CodexSessionParser().parse(source)
