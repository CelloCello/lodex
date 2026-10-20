from __future__ import annotations

from pathlib import Path

from lodex_core.history.contracts import SessionRecord, TurnRecord
from lodex_core.history.indexer import Indexer
from lodex_core.history.sources import SessionCandidate
from lodex_core.history.storage import Storage

from .support.fakes import FakeEmbedder


class FakeAgentSource:
    name = "fake-agent"

    def __init__(self, transcript: Path) -> None:
        self.transcript = transcript

    def available(self) -> bool:
        return True

    def discover(self) -> tuple[SessionCandidate, ...]:
        return (
            SessionCandidate(
                path=self.transcript,
                source_session_id="native-session",
                created_at="2026-08-20T00:00:00Z",
            ),
        )

    def resolve(self, target: str) -> SessionCandidate:
        assert target == "native-session"
        return self.discover()[0]

    def parse(self, path: Path) -> SessionRecord:
        assert path == self.transcript
        turn = TurnRecord(
            session_id="fake-agent:native-session",
            turn_id="fake-agent:native-turn",
            ordinal=0,
            status="completed",
            started_at="2026-08-20T00:00:01Z",
            completed_at="2026-08-20T00:00:02Z",
            user_text="What did the fake agent do?",
            assistant_text="It proved the indexer accepts a source adapter.",
            content_hash="fake-turn-hash",
        )
        return SessionRecord(
            session_id=turn.session_id,
            source=self.name,
            source_path=str(path),
            created_at="2026-08-20T00:00:00Z",
            cwd=str(path.parent),
            archived=False,
            turns=(turn,),
        )

    def relocated(self, missing_path: Path) -> SessionCandidate | None:
        return None


def test_indexer_accepts_a_non_codex_source_adapter(tmp_path: Path) -> None:
    transcript = tmp_path / "session.transcript"
    transcript.write_text("agent-specific format", encoding="utf-8")
    embedder = FakeEmbedder(dimension=3)

    with Storage(tmp_path / "lodex.db", dimension=3) as storage:
        summary = Indexer(
            storage,
            embedder,
            source=FakeAgentSource(transcript),
        ).index(target="native-session")

        assert summary.source == "fake-agent"
        assert summary.embedded_chunks == 1
        stored = storage.get_session("fake-agent:native-session")
        assert stored is not None
        assert stored.source == "fake-agent"
