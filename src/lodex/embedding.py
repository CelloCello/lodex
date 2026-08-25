"""Validated embeddings through a loopback-only Ollama client."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, cast
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

import httpx

from lodex.contracts import EmbeddingResult, OllamaStatus

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3-embedding:0.6b"
DEFAULT_DIMENSION = 1_024
DEFAULT_BATCH_SIZE = 16
DEFAULT_KEEP_ALIVE = "10m"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_INPUT_CHARS = 4_000
QUERY_INSTRUCTION = "Instruct: Retrieve relevant coding-session history for the query.\nQuery: "


class EmbeddingError(RuntimeError):
    """Base class for actionable embedding failures."""


class EmbeddingConfigurationError(EmbeddingError):
    """The embedding endpoint or settings violate Lodex's safety contract."""


class OllamaUnavailableError(EmbeddingError):
    """The local Ollama runtime could not serve a request."""


class OllamaBackendResetError(OllamaUnavailableError):
    """The Ollama model runner reset while serving an otherwise valid request."""


class ModelNotFoundError(EmbeddingError):
    """The configured embedding model is not installed."""


class EmbeddingContractError(EmbeddingError):
    """The provider response is incompatible with the stored vector contract."""


class OllamaClient(Protocol):
    """Subset of the official client used by Lodex and test fakes."""

    def version(self) -> object: ...

    def list(self) -> object: ...

    def embed(
        self,
        *,
        model: str,
        input: Sequence[str],
        truncate: bool,
        keep_alive: str,
    ) -> object: ...


class OfficialOllamaClient:
    """Adapter adding the server version endpoint to the official Python client."""

    def __init__(self, *, host: str, timeout_seconds: float) -> None:
        from ollama import Client

        self._host = host
        self._timeout_seconds = timeout_seconds
        self._client = Client(host=host, timeout=timeout_seconds)

    def version(self) -> object:
        request = Request(f"{self._host}/api/version", method="GET")
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=self._timeout_seconds) as response:
            payload = json.loads(response.read())
        if not isinstance(payload, Mapping):
            raise EmbeddingContractError("Ollama version response has an invalid shape")
        return payload

    def list(self) -> object:
        return self._client.list()

    def embed(
        self,
        *,
        model: str,
        input: Sequence[str],
        truncate: bool,
        keep_alive: str,
    ) -> object:
        return self._client.embed(
            model=model,
            input=input,
            truncate=truncate,
            keep_alive=keep_alive,
        )


def validate_loopback_host(host: str) -> str:
    """Return a normalized loopback URL or reject a remote/ambiguous endpoint."""

    candidate = host.strip()
    if not candidate:
        raise EmbeddingConfigurationError("OLLAMA_HOST must not be empty")
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise EmbeddingConfigurationError("OLLAMA_HOST must use http or https")
    if parsed.username or parsed.password:
        raise EmbeddingConfigurationError("OLLAMA_HOST must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise EmbeddingConfigurationError("OLLAMA_HOST must not contain a path, query, or fragment")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise EmbeddingConfigurationError(
            "Remote Ollama hosts are disabled; use localhost, 127.0.0.1, or ::1"
        )
    try:
        _ = parsed.port
    except ValueError as exc:
        raise EmbeddingConfigurationError(
            "OLLAMA_HOST port must be an integer between 1 and 65535"
        ) from exc
    return candidate.rstrip("/")


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _required_string(value: object, name: str) -> str:
    result = _field(value, name)
    return result if isinstance(result, str) else ""


class OllamaEmbedder:
    """Production embedder with preflight, batching, retry, and validation."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_OLLAMA_HOST,
        model: str = DEFAULT_MODEL,
        expected_dimension: int = DEFAULT_DIMENSION,
        batch_size: int = DEFAULT_BATCH_SIZE,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
        retry_count: int = 2,
        retry_base_seconds: float = 0.1,
        client: OllamaClient | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.host = validate_loopback_host(host)
        if expected_dimension <= 0:
            raise EmbeddingConfigurationError("expected_dimension must be positive")
        if batch_size <= 0:
            raise EmbeddingConfigurationError("batch_size must be positive")
        if max_input_chars <= 0:
            raise EmbeddingConfigurationError("max_input_chars must be positive")
        if retry_count < 0:
            raise EmbeddingConfigurationError("retry_count must be non-negative")
        self.model = model
        self.expected_dimension = expected_dimension
        self.batch_size = batch_size
        self.keep_alive = keep_alive
        self.max_input_chars = max_input_chars
        self.retry_count = retry_count
        self.retry_base_seconds = retry_base_seconds
        self._sleep = sleep
        self._client = client or cast(
            OllamaClient,
            OfficialOllamaClient(host=self.host, timeout_seconds=timeout_seconds),
        )

    def status(self) -> OllamaStatus:
        """Probe reachability, model identity, and embedding dimension."""

        try:
            version = self._server_version()
        except Exception as exc:  # status must return diagnostics, not a traceback
            return self._status_error(reachable=False, error=self._error_text(exc))

        try:
            digest = self._installed_model_digest()
        except Exception as exc:
            return self._status_error(reachable=True, version=version, error=self._error_text(exc))
        if digest is None:
            return OllamaStatus(
                host=self.host,
                reachable=True,
                version=version,
                model=self.model,
                model_installed=False,
                model_digest=None,
                dimension=None,
                expected_dimension=self.expected_dimension,
                compatible=False,
                error=f"Model {self.model!r} is not installed",
            )

        try:
            dimension = self._probe_dimension()
        except Exception as exc:
            return self._status_error(
                reachable=True,
                version=version,
                installed=True,
                digest=digest,
                error=self._error_text(exc),
            )
        compatible = dimension == self.expected_dimension
        return OllamaStatus(
            host=self.host,
            reachable=True,
            version=version,
            model=self.model,
            model_installed=True,
            model_digest=digest,
            dimension=dimension,
            expected_dimension=self.expected_dimension,
            compatible=compatible,
            error=None
            if compatible
            else f"Embedding dimension {dimension} does not match {self.expected_dimension}",
        )

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed raw document chunks while preserving input order."""

        raw_inputs = list(texts)
        self._validate_inputs(raw_inputs)
        if not raw_inputs:
            return self._result([], self._require_model_digest())
        digest = self._require_model_digest()
        vectors = self._embed_batches(raw_inputs)
        return self._result(vectors, digest)

    def embed_query(self, text: str) -> EmbeddingResult:
        """Embed a query with the fixed coding-history retrieval instruction."""

        self._validate_inputs([text])
        digest = self._require_model_digest()
        vectors = self._embed_batches([f"{QUERY_INSTRUCTION}{text}"])
        return self._result(vectors, digest)

    def _server_version(self) -> str:
        try:
            response = self._client.version()
        except Exception as exc:
            raise OllamaUnavailableError(self._error_text(exc)) from exc
        version = _required_string(response, "version")
        if not version and isinstance(response, str):
            version = response
        if not version:
            raise EmbeddingContractError("Ollama version response did not include a version")
        return version

    def _installed_model_digest(self) -> str | None:
        try:
            response = self._client.list()
        except Exception as exc:
            raise OllamaUnavailableError(self._error_text(exc)) from exc
        models = _field(response, "models", [])
        if not isinstance(models, Sequence) or isinstance(models, str | bytes):
            raise EmbeddingContractError("Ollama model list has an invalid shape")
        for item in models:
            name = _required_string(item, "model") or _required_string(item, "name")
            if name == self.model:
                digest = _required_string(item, "digest")
                if not digest:
                    raise EmbeddingContractError(
                        f"Ollama did not report a digest for model {self.model!r}"
                    )
                return digest
        return None

    def _require_model_digest(self) -> str:
        digest = self._installed_model_digest()
        if digest is None:
            raise ModelNotFoundError(
                f"Model {self.model!r} is not installed; run: ollama pull {self.model}"
            )
        return digest

    def _validate_inputs(self, inputs: Sequence[str]) -> None:
        for index, value in enumerate(inputs):
            if not isinstance(value, str):
                raise EmbeddingContractError(f"Embedding input {index} is not a string")
            if not value.strip():
                raise EmbeddingContractError(f"Embedding input {index} is empty")
            if len(value) > self.max_input_chars:
                raise EmbeddingContractError(
                    f"Embedding input {index} has {len(value)} characters; "
                    f"limit is {self.max_input_chars}. Input was not truncated."
                )

    def _embed_batches(self, inputs: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(inputs), self.batch_size):
            batch = inputs[start : start + self.batch_size]
            for vector in self._embed_batch(batch):
                if len(vector) != self.expected_dimension:
                    raise EmbeddingContractError(
                        f"Embedding dimension {len(vector)} does not match "
                        f"{self.expected_dimension}"
                    )
                vectors.append(vector)
        return vectors

    def _embed_batch(self, inputs: Sequence[str]) -> list[list[float]]:
        try:
            return self._parse_vectors(self._request_embed(inputs), len(inputs))
        except OllamaBackendResetError:
            if len(inputs) == 1:
                raise
            midpoint = len(inputs) // 2
            return self._embed_batch(inputs[:midpoint]) + self._embed_batch(inputs[midpoint:])

    def _probe_dimension(self) -> int:
        vectors = self._parse_vectors(
            self._request_embed(["Lodex embedding dimension probe"]),
            1,
        )
        return len(vectors[0])

    @staticmethod
    def _parse_vectors(response: object, expected_count: int) -> list[list[float]]:
        raw_embeddings = _field(response, "embeddings", [])
        if not isinstance(raw_embeddings, Sequence) or isinstance(raw_embeddings, str | bytes):
            raise EmbeddingContractError("Ollama embed response has an invalid shape")
        if len(raw_embeddings) != expected_count:
            raise EmbeddingContractError(
                f"Ollama returned {len(raw_embeddings)} embeddings for {expected_count} inputs"
            )
        vectors: list[list[float]] = []
        for raw_vector in raw_embeddings:
            if not isinstance(raw_vector, Sequence) or isinstance(raw_vector, str | bytes):
                raise EmbeddingContractError("Ollama returned a non-vector embedding")
            try:
                vector = [float(value) for value in raw_vector]
            except (TypeError, ValueError) as exc:
                raise EmbeddingContractError("Ollama returned a non-numeric embedding") from exc
            if not vector:
                raise EmbeddingContractError("Ollama returned an empty embedding")
            if not all(math.isfinite(value) for value in vector):
                raise EmbeddingContractError("Embedding contains a non-finite value")
            vectors.append(vector)
        return vectors

    def _request_embed(self, inputs: Sequence[str]) -> object:
        for attempt in range(self.retry_count + 1):
            try:
                return self._client.embed(
                    model=self.model,
                    input=inputs,
                    truncate=False,
                    keep_alive=self.keep_alive,
                )
            except Exception as exc:
                if attempt < self.retry_count and self._is_transient(exc):
                    self._sleep(self.retry_base_seconds * (2**attempt))
                    continue
                if self._is_backend_reset(exc):
                    raise OllamaBackendResetError(self._error_text(exc)) from exc
                if self._is_transient(exc) or isinstance(exc, ConnectionError | TimeoutError):
                    raise OllamaUnavailableError(self._error_text(exc)) from exc
                raise EmbeddingError(self._error_text(exc)) from exc
        raise AssertionError("unreachable")

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        return (
            isinstance(exc, TimeoutError | httpx.TimeoutException)
            or (isinstance(status_code, int) and 500 <= status_code < 600)
            or OllamaEmbedder._is_backend_reset(exc)
        )

    @staticmethod
    def _is_backend_reset(exc: Exception) -> bool:
        if getattr(exc, "status_code", None) != 400:
            return False
        message = OllamaEmbedder._error_text(exc).lower()
        return any(
            marker in message for marker in ("connection reset by peer", "eof", "health resp:")
        )

    def _result(self, vectors: Sequence[Sequence[float]], digest: str) -> EmbeddingResult:
        return EmbeddingResult(
            embeddings=tuple(tuple(vector) for vector in vectors),
            provider="ollama",
            model=self.model,
            model_digest=digest,
            dimension=self.expected_dimension,
        )

    def _status_error(
        self,
        *,
        reachable: bool,
        error: str,
        version: str | None = None,
        installed: bool = False,
        digest: str | None = None,
    ) -> OllamaStatus:
        return OllamaStatus(
            host=self.host,
            reachable=reachable,
            version=version,
            model=self.model,
            model_installed=installed,
            model_digest=digest,
            dimension=None,
            expected_dimension=self.expected_dimension,
            compatible=False,
            error=error,
        )

    @staticmethod
    def _error_text(exc: Exception) -> str:
        return str(exc) or exc.__class__.__name__
