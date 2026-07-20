"""Construction helpers shared by the architecture behavior seed catalog."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from fdai.shared.providers.behavior_knowledge import (
    BehaviorContent,
    BehaviorSource,
    BehaviorSpec,
)

EXTRACTOR_VERSION = "architecture-behavior-seed-v1"

ARCHITECTURE_SOURCE_PATHS = frozenset(
    {
        ".github/instructions/app-shape.instructions.md",
        "src/fdai/agents/bragi.py",
        "src/fdai/agents/var.py",
        "src/fdai/agents/vidar.py",
        "src/fdai/core/event_ingest/__init__.py",
        "src/fdai/core/executor/executor.py",
        "src/fdai/core/quality_gate/gate.py",
        "src/fdai/core/risk_gate/gate.py",
        "src/fdai/core/trust_router/__init__.py",
        "tests/agents/test_chat_to_pipeline_e2e.py",
        "tests/agents/test_conversational_port.py",
        "tests/agents/test_wave3_pipeline.py",
        "tests/core/event_ingest/test_event_ingest.py",
        "tests/core/executor/test_executor.py",
        "tests/core/quality_gate/test_gate.py",
        "tests/core/risk_gate/test_gate.py",
        "tests/core/trust_router/test_trust_router.py",
        "tests/delivery/read_api/test_local.py",
    }
)


def source(
    blob_shas: Mapping[str, str],
    source_kind: str,
    path: str,
    symbol: str,
    line_start: int,
    line_end: int,
    *,
    authority_role: str | None = None,
) -> BehaviorSource:
    return BehaviorSource(
        source_kind=source_kind,  # type: ignore[arg-type]
        path=path,
        symbol=symbol,
        line_start=line_start,
        line_end=line_end,
        blob_sha=blob_shas[path],
        authority_role=authority_role
        or ("verification" if source_kind == "test" else "implementation"),  # type: ignore[arg-type]
    )


def spec(
    *,
    behavior_id: str,
    subject_id: str,
    status: str,
    owner: str,
    aliases: tuple[str, ...],
    trigger: tuple[str, ...],
    preconditions: tuple[str, ...],
    steps: tuple[str, ...],
    outcomes: tuple[str, ...],
    exclusions: tuple[str, ...],
    safety: tuple[str, ...],
    ko: BehaviorContent,
    sources: tuple[BehaviorSource, ...],
    indexed_commit: str,
) -> BehaviorSpec:
    return BehaviorSpec(
        behavior_id=behavior_id,
        subject_kind="architecture_behavior",
        subject_id=subject_id,
        status=status,  # type: ignore[arg-type]
        owner=owner,
        question_aliases=aliases,
        trigger=trigger,
        preconditions=preconditions,
        steps=steps,
        outcomes=outcomes,
        exclusions=exclusions,
        safety=safety,
        sources=sources,
        indexed_commit=indexed_commit,
        extractor_version=EXTRACTOR_VERSION,
        source_manifest_hash=_manifest_hash(sources),
        localized={"ko": ko},
    )


def content(
    *,
    trigger: tuple[str, ...],
    preconditions: tuple[str, ...],
    steps: tuple[str, ...],
    outcomes: tuple[str, ...],
    exclusions: tuple[str, ...],
    safety: tuple[str, ...],
) -> BehaviorContent:
    return BehaviorContent(
        trigger=trigger,
        preconditions=preconditions,
        steps=steps,
        outcomes=outcomes,
        exclusions=exclusions,
        safety=safety,
    )


def _manifest_hash(sources: Sequence[BehaviorSource]) -> str:
    payload = [item.manifest_record() for item in sources]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ARCHITECTURE_SOURCE_PATHS",
    "EXTRACTOR_VERSION",
    "content",
    "source",
    "spec",
]
