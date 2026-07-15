"""Optional local semantic entailment verifier for Command Deck shadow checks."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import math
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol

SemanticVerdict = Literal["entailed", "contradicted", "unknown", "unavailable"]


@dataclass(frozen=True, slots=True)
class SemanticVerification:
    verdict: SemanticVerdict
    provider: str
    model_id: str | None
    latency_ms: int
    entailment_score: float | None = None
    contradiction_score: float | None = None
    reason_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "provider": self.provider,
            "model_id": self.model_id,
            "latency_ms": self.latency_ms,
            "entailment_score": self.entailment_score,
            "contradiction_score": self.contradiction_score,
            "reason_code": self.reason_code,
        }


class SemanticVerifier(Protocol):
    async def verify(self, *, premise: str, hypothesis: str) -> SemanticVerification: ...


@dataclass(frozen=True, slots=True)
class OnnxSemanticVerifierConfig:
    model_path: Path
    tokenizer_path: Path
    model_sha256: str
    tokenizer_sha256: str
    model_id: str
    entailment_index: int
    contradiction_index: int
    threshold: float = 0.8
    max_length: int = 256

    def __post_init__(self) -> None:
        if not _is_sha256(self.model_sha256) or not _is_sha256(self.tokenizer_sha256):
            raise ValueError("semantic verifier artifact hashes MUST be 64 lowercase hex chars")
        if self.entailment_index < 0 or self.contradiction_index < 0:
            raise ValueError("semantic verifier label indexes MUST be non-negative")
        if self.entailment_index == self.contradiction_index:
            raise ValueError("semantic verifier label indexes MUST be distinct")
        if not 0.5 <= self.threshold <= 1.0:
            raise ValueError("semantic verifier threshold MUST be in [0.5, 1.0]")
        if self.max_length < 16 or self.max_length > 1024:
            raise ValueError("semantic verifier max_length MUST be in [16, 1024]")


class OnnxSemanticVerifier:
    """Lazy CPU ONNX NLI inference; optional packages load on first use."""

    def __init__(self, config: OnnxSemanticVerifierConfig) -> None:
        self._config = config
        self._load_lock = Lock()
        self._session: Any = None
        self._tokenizer: Any = None
        self._numpy: Any = None

    async def verify(self, *, premise: str, hypothesis: str) -> SemanticVerification:
        started = time.monotonic()
        try:
            return await asyncio.to_thread(self._verify_sync, premise, hypothesis, started)
        except ModuleNotFoundError:
            return _unavailable(started, "optional_package_missing", self._config.model_id)
        except (OSError, RuntimeError, ValueError):
            return _unavailable(started, "semantic_inference_failed", self._config.model_id)

    def _verify_sync(
        self,
        premise: str,
        hypothesis: str,
        started: float,
    ) -> SemanticVerification:
        self._ensure_loaded()
        encoding = self._tokenizer.encode(premise, hypothesis)
        feed_values = {
            "input_ids": self._numpy.asarray([encoding.ids], dtype=self._numpy.int64),
            "attention_mask": self._numpy.asarray(
                [encoding.attention_mask], dtype=self._numpy.int64
            ),
            "token_type_ids": self._numpy.asarray([encoding.type_ids], dtype=self._numpy.int64),
        }
        input_names = {item.name for item in self._session.get_inputs()}
        if "input_ids" not in input_names:
            raise ValueError("semantic ONNX model lacks input_ids")
        feed = {name: value for name, value in feed_values.items() if name in input_names}
        outputs = self._session.run(None, feed)
        if not outputs:
            raise ValueError("semantic ONNX model returned no output")
        logits = self._numpy.asarray(outputs[0]).reshape(-1)
        max_index = max(self._config.entailment_index, self._config.contradiction_index)
        if logits.size <= max_index:
            raise ValueError("semantic ONNX output does not contain configured labels")
        scores = _softmax([float(value) for value in logits])
        entailment = scores[self._config.entailment_index]
        contradiction = scores[self._config.contradiction_index]
        if entailment >= self._config.threshold:
            verdict: SemanticVerdict = "entailed"
        elif contradiction >= self._config.threshold:
            verdict = "contradicted"
        else:
            verdict = "unknown"
        return SemanticVerification(
            verdict=verdict,
            provider="onnx-local",
            model_id=self._config.model_id,
            latency_ms=int((time.monotonic() - started) * 1000),
            entailment_score=entailment,
            contradiction_score=contradiction,
        )

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        with self._load_lock:
            if self._session is not None:
                return
            _verify_file(self._config.model_path, self._config.model_sha256)
            _verify_file(self._config.tokenizer_path, self._config.tokenizer_sha256)
            numpy = importlib.import_module("numpy")
            tokenizers = importlib.import_module("tokenizers")
            onnxruntime = importlib.import_module("onnxruntime")
            tokenizer = tokenizers.Tokenizer.from_file(str(self._config.tokenizer_path))
            tokenizer.enable_truncation(max_length=self._config.max_length)
            tokenizer.enable_padding(length=self._config.max_length)
            session = onnxruntime.InferenceSession(
                str(self._config.model_path),
                providers=["CPUExecutionProvider"],
            )
            self._numpy = numpy
            self._tokenizer = tokenizer
            self._session = session


def semantic_verifier_from_env(
    env: Mapping[str, str] | None = None,
) -> SemanticVerifier | None:
    """Build a lazy provider only when every artifact setting is present."""

    source = os.environ if env is None else env
    keys = {
        "model_path": source.get("FDAI_SEMANTIC_VERIFIER_MODEL_PATH", "").strip(),
        "tokenizer_path": source.get("FDAI_SEMANTIC_VERIFIER_TOKENIZER_PATH", "").strip(),
        "model_sha256": source.get("FDAI_SEMANTIC_VERIFIER_MODEL_SHA256", "").strip(),
        "tokenizer_sha256": source.get("FDAI_SEMANTIC_VERIFIER_TOKENIZER_SHA256", "").strip(),
        "model_id": source.get("FDAI_SEMANTIC_VERIFIER_MODEL_ID", "").strip(),
    }
    if not any(keys.values()):
        return None
    if not all(keys.values()):
        raise ValueError("semantic verifier env configuration MUST be complete")
    return OnnxSemanticVerifier(
        OnnxSemanticVerifierConfig(
            model_path=Path(keys["model_path"]),
            tokenizer_path=Path(keys["tokenizer_path"]),
            model_sha256=keys["model_sha256"],
            tokenizer_sha256=keys["tokenizer_sha256"],
            model_id=keys["model_id"],
            entailment_index=_env_int(source, "FDAI_SEMANTIC_VERIFIER_ENTAILMENT_INDEX"),
            contradiction_index=_env_int(source, "FDAI_SEMANTIC_VERIFIER_CONTRADICTION_INDEX"),
            threshold=_env_float(source, "FDAI_SEMANTIC_VERIFIER_THRESHOLD", 0.8),
            max_length=_env_int(source, "FDAI_SEMANTIC_VERIFIER_MAX_LENGTH", 256),
        )
    )


def semantic_premise(view_context: Mapping[str, Any], max_chars: int = 12_000) -> str:
    """Build bounded NLI premise text from the supplied evidence projection."""

    projection = {
        key: view_context.get(key)
        for key in (
            "routeId",
            "routeLabel",
            "purpose",
            "headline",
            "facts",
            "records",
            "_operational_evidence",
            "_tool_evidence",
            "_agent_evidence",
            "_concept_evidence",
        )
        if key in view_context
    }
    raw = str(projection) if not projection else _canonical_json(projection)
    return raw[:max_chars]


def unavailable_semantic_verification(reason: str) -> SemanticVerification:
    return SemanticVerification(
        verdict="unavailable",
        provider="none",
        model_id=None,
        latency_ms=0,
        reason_code=reason,
    )


def _canonical_json(value: Mapping[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _verify_file(path: Path, expected_sha256: str) -> None:
    if not path.is_file():
        raise OSError("semantic verifier artifact is missing")
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        while chunk := artifact.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise ValueError("semantic verifier artifact hash mismatch")


def _softmax(values: list[float]) -> list[float]:
    maximum = max(values)
    exponentials = [math.exp(value - maximum) for value in values]
    total = sum(exponentials)
    return [value / total for value in exponentials]


def _unavailable(started: float, reason: str, model_id: str) -> SemanticVerification:
    return SemanticVerification(
        verdict="unavailable",
        provider="onnx-local",
        model_id=model_id,
        latency_ms=int((time.monotonic() - started) * 1000),
        reason_code=reason,
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _env_int(source: Mapping[str, str], key: str, default: int | None = None) -> int:
    raw = source.get(key, "").strip()
    if not raw:
        if default is None:
            raise ValueError(f"{key} MUST be configured")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} MUST be an integer") from exc


def _env_float(source: Mapping[str, str], key: str, default: float) -> float:
    raw = source.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} MUST be numeric") from exc


__all__ = [
    "OnnxSemanticVerifier",
    "OnnxSemanticVerifierConfig",
    "SemanticVerification",
    "SemanticVerifier",
    "semantic_premise",
    "semantic_verifier_from_env",
    "unavailable_semantic_verification",
]
