"""Bind reviewed Loki adversarial candidates and their frozen corpus."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fdai.agents import (
    MAX_GENERATED_SCENARIOS,
    ChaosScenarioCandidate,
    ChaosScheduleConfig,
    frozen_corpus_key,
)
from fdai.delivery.loki_scenario_evidence import ImmutableChaosScenarioSource
from fdai.runtime.bootstrap_chaos_schedule import parse_chaos_schedule_declaration

_PATH_ENV = "FDAI_LOKI_SCENARIO_EVIDENCE_PATH"
_DIGEST_ENV = "FDAI_LOKI_SCENARIO_EVIDENCE_SHA256"
_SOURCE_REVISION_ENV = "FDAI_SOURCE_REVISION"
_MAX_FILE_BYTES = 1024 * 1024
_MAX_CORPUS_RECORDS = 256
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class LokiScenarioBindings:
    generator: ImmutableChaosScenarioSource
    corpus: tuple[ChaosScheduleConfig, ...]


def build_loki_scenario_bindings(
    *,
    environment: Mapping[str, str],
    action_type_names: frozenset[str],
) -> LokiScenarioBindings | None:
    """Load one complete reviewed source or keep Loki generation unbound."""

    path_value = environment.get(_PATH_ENV, "").strip()
    expected_digest = environment.get(_DIGEST_ENV, "").strip()
    if not path_value and not expected_digest:
        return None
    if not path_value or not expected_digest:
        raise RuntimeError("Loki scenario evidence configuration is incomplete")
    source_revision = environment.get(_SOURCE_REVISION_ENV, "").strip()
    if not source_revision:
        raise RuntimeError("Loki scenario evidence requires FDAI_SOURCE_REVISION")
    path = Path(path_value)
    if not path.is_absolute():
        raise RuntimeError("Loki scenario evidence path MUST be absolute")
    try:
        content = _read_bounded_regular_file(path)
        if _SHA256.fullmatch(expected_digest) is None:
            raise ValueError("Loki scenario evidence digest MUST be lowercase SHA-256")
        if hashlib.sha256(content).hexdigest() != expected_digest:
            raise ValueError("Loki scenario evidence digest mismatch")
        raw = _object(_load_unique_json(content), "manifest")
        _exact_fields(
            raw,
            {
                "schema_version",
                "source_revision",
                "review_ref",
                "design_ref",
                "frozen_corpus",
                "candidates",
            },
            "manifest",
        )
        if raw["schema_version"] != "1.0.0":
            raise ValueError("unsupported Loki scenario evidence schema")
        if _text(raw, "source_revision") != source_revision:
            raise ValueError("Loki scenario evidence source revision differs")
        review_ref = _text(raw, "review_ref")
        design_ref = _text(raw, "design_ref")
        corpus_rows = _object_list(raw["frozen_corpus"], "frozen_corpus")
        candidate_rows = _object_list(raw["candidates"], "candidates")
        if not corpus_rows or len(corpus_rows) > _MAX_CORPUS_RECORDS:
            raise ValueError("Loki frozen corpus is outside its bounded range")
        if len(candidate_rows) > MAX_GENERATED_SCENARIOS:
            raise ValueError("Loki scenario candidates exceed the generation bound")
        corpus = tuple(
            parse_chaos_schedule_declaration(item, action_type_names=action_type_names)
            for item in corpus_rows
        )
        candidates = tuple(
            _candidate(item, action_type_names=action_type_names) for item in candidate_rows
        )
        if len({item.schedule_id for item in corpus}) != len(corpus):
            raise ValueError("Loki frozen corpus schedule ids MUST be unique")
        if len({frozen_corpus_key(item) for item in corpus}) != len(corpus):
            raise ValueError("Loki frozen corpus coverage identities MUST be unique")
        if len({item.scenario_id for item in candidates}) != len(candidates):
            raise ValueError("Loki scenario candidate ids MUST be unique")
        if len({frozen_corpus_key(item.schedule) for item in candidates}) != len(candidates):
            raise ValueError("Loki scenario candidate coverage identities MUST be unique")
    except ValueError as exc:
        raise RuntimeError("Loki scenario evidence is invalid") from exc
    return LokiScenarioBindings(
        generator=ImmutableChaosScenarioSource(
            design_ref=design_ref,
            review_ref=review_ref,
            candidates=candidates,
        ),
        corpus=corpus,
    )


def _candidate(
    raw: Mapping[str, object],
    *,
    action_type_names: frozenset[str],
) -> ChaosScenarioCandidate:
    _exact_fields(raw, {"scenario_id", "schedule", "evidence_refs"}, "candidate")
    refs = raw["evidence_refs"]
    if not isinstance(refs, list) or not refs:
        raise ValueError("Loki scenario candidate evidence_refs MUST be a non-empty array")
    evidence_refs = tuple(_canonical_text(item, "evidence_ref") for item in refs)
    if len(set(evidence_refs)) != len(evidence_refs):
        raise ValueError("Loki scenario candidate evidence_refs MUST be unique")
    return ChaosScenarioCandidate(
        scenario_id=_text(raw, "scenario_id"),
        schedule=parse_chaos_schedule_declaration(
            _object(raw["schedule"], "candidate schedule"),
            action_type_names=action_type_names,
        ),
        evidence_refs=evidence_refs,
    )


def _load_unique_json(content: bytes) -> object:
    def unique(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Loki scenario evidence contains duplicate keys")
            result[key] = value
        return result

    try:
        return json.loads(content, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Loki scenario evidence is not valid UTF-8 JSON") from exc


def _read_bounded_regular_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("Loki scenario evidence MUST be a regular file") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_FILE_BYTES:
            raise ValueError("Loki scenario evidence file is invalid or oversized")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read(_MAX_FILE_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(content) > _MAX_FILE_BYTES:
        raise ValueError("Loki scenario evidence file is invalid or oversized")
    return content


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"Loki scenario {label} MUST be an object")
    return value


def _object_list(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError(f"Loki scenario {label} MUST be an array")
    return tuple(_object(item, label) for item in value)


def _exact_fields(raw: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(raw) != expected:
        raise ValueError(f"Loki scenario {label} fields are incomplete or unknown")


def _text(raw: Mapping[str, object], field: str) -> str:
    return _canonical_text(raw.get(field), field)


def _canonical_text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"Loki scenario {field} MUST be canonical text")
    return value


__all__ = ["LokiScenarioBindings", "build_loki_scenario_bindings"]
