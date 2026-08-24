"""Conversation-aware, paragraph-preserving character chunking."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from lodex.contracts import ChunkRecord, TurnRecord

DEFAULT_MAX_CHARS = 4_000
DEFAULT_OVERLAP_CHARS = 400
CHUNKING_VERSION = "1"


@dataclass(frozen=True, slots=True)
class TextSlice:
    """One slice of a source text with offsets into the original string."""

    text: str
    start: int
    end: int


def format_turn(turn: TurnRecord) -> str:
    """Render a normalized turn without introducing transcript metadata noise."""

    sections: list[str] = []
    if turn.user_text:
        sections.append(f"User:\n{turn.user_text}")
    if turn.assistant_text:
        sections.append(f"Assistant:\n{turn.assistant_text}")
    return "\n\n".join(sections)


def split_text(
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> tuple[TextSlice, ...]:
    """Split text at paragraph boundaries, with bounded character overlap."""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")
    if not text:
        return ()

    slices: list[TextSlice] = []
    start = 0
    length = len(text)
    while start < length:
        hard_end = min(start + max_chars, length)
        end = hard_end
        if hard_end < length:
            minimum_boundary = start + max(max_chars // 2, overlap_chars + 1)
            paragraph_end = text.rfind("\n\n", minimum_boundary, hard_end + 1)
            if paragraph_end >= minimum_boundary:
                end = paragraph_end + 2

        raw = text[start:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        clean_start = start + leading
        clean_end = start + trailing
        if clean_end > clean_start:
            slices.append(TextSlice(text[clean_start:clean_end], clean_start, clean_end))

        if end >= length:
            break
        next_start = max(0, end - overlap_chars)
        if next_start <= start:
            next_start = end
        start = next_start

    return tuple(slices)


def chunk_turn(
    turn: TurnRecord,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> tuple[ChunkRecord, ...]:
    """Create stable chunks for one semantic user/assistant turn."""

    text = format_turn(turn)
    slices = split_text(text, max_chars=max_chars, overlap_chars=overlap_chars)
    chunks: list[ChunkRecord] = []
    for index, text_slice in enumerate(slices):
        content_hash = hashlib.sha256(text_slice.text.encode()).hexdigest()
        identity = f"{turn.session_id}\0{turn.turn_id}\0{index}\0{content_hash}"
        chunk_id = hashlib.sha256(identity.encode()).hexdigest()
        chunks.append(
            ChunkRecord(
                chunk_id=chunk_id,
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                chunk_index=index,
                text=text_slice.text,
                char_start=text_slice.start,
                char_end=text_slice.end,
                content_hash=content_hash,
            )
        )
    return tuple(chunks)
