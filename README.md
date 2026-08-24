# Lodex

Lodex is a local-first retrieval tool for Codex session history. The current
implementation covers Codex transcript normalization, conversation-aware
chunking, and embeddings through a loopback-only Ollama connection.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
```

Check the local Ollama embedding contract:

```bash
uv run lodex status
uv run lodex status --json
```

The default model is `qwen3-embedding:0.6b` with 1024 dimensions. Lodex rejects
non-loopback `OLLAMA_HOST` values so transcript text cannot be sent to a remote
embedding endpoint by mistake.

