"""T0 deterministic engine - verdict and finding models.

The T0 tier resolves the majority of events without any LLM
(``docs/roadmap/phases/phase-1-rule-catalog-t0.md``). It emits a
:class:`Verdict` composed of zero-or-more :class:`Finding` records plus
an :class:`AuditHint` the audit-log writer persists.

Every T0 output is **shadow-mode by construction** in P1: the engine
judges and logs; it never mutates state. This module defines the data
types only - the orchestrator (:mod:`.engine`) and the rule-lookup index
(:mod:`.index`) are the callers.

Pipeline-stage vocabulary aligns with
``docs/roadmap/architecture/llm-strategy.md § Pipeline Stages``:

- ``L1_evaluate`` - rule evaluation (this module's normal happy path).
- ``L1_simulate`` - what-if / dry-run (wired in P1 W-3).
- ``abstain``    - terminal no-op that escalates to HIL, recorded here
  when no rule applies OR when a rule's check_logic cannot be evaluated
  deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from fdai.shared.contracts.models import Mode, Severity


class PipelineStage(StrEnum):
    """Audit vocabulary for the T0 layer.

    Kept as a StrEnum so audit-log entries serialize the same identifier
    the docs use. New stages are added conservatively - an unknown value
    is a schema break, not a silent no-op.
    """

    L1_EVALUATE = "L1_evaluate"
    L1_SIMULATE = "L1_simulate"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class Finding:
    """A rule match on a resource at a point in time.

    Mirrors ``ontology_finding`` in
    ``docs/roadmap/architecture/llm-strategy.md § Data Placement``. ``context`` is
    inert JSON-safe data (never instructions) that the audit store
    persists verbatim.
    """

    finding_id: str
    rule_id: str
    rule_version: str
    resource_id: str
    signal_id: str
    severity: Severity
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuditHint:
    """Payload the T0 engine hands to the audit-log writer.

    The writer persists an append-only entry; this record carries the
    exact fields the writer needs plus the citing rule ids so the
    decision path is reconstructable. Mode is always :attr:`Mode.SHADOW`
    in P1.
    """

    event_id: str
    pipeline_stage: PipelineStage
    tier: str  # "t0" - carried as a plain string to avoid Tier import loop.
    mode: Mode
    citing_rule_ids: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Verdict:
    """T0 engine output.

    ``findings`` is empty when no rule applied; ``audit_hint.pipeline_stage``
    then equals :attr:`PipelineStage.ABSTAIN`. When one or more rules
    matched, findings are ordered by (severity descending, rule_id) so
    downstream consumers can prioritise deterministically.
    """

    findings: tuple[Finding, ...] = ()
    audit_hint: AuditHint | None = None

    @property
    def matched(self) -> bool:
        return bool(self.findings)


__all__ = [
    "AuditHint",
    "Finding",
    "PipelineStage",
    "Verdict",
]
