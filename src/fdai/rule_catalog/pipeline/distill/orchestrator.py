"""Build-time orchestrator for manual distillation (stitches the stages).

Design contract:
``docs/roadmap/rules-and-detection/manual-distillation.md`` § "The distillation
pipeline" and § "Ingesting from siloed sources". This module wires the seams and
deterministic stages built in M1-M4 into one build-time pass:

    list -> freshness diff -> triage filter -> exact dedupe -> classify ->
    prioritize -> fetch -> sensitivity scan -> distill -> coverage

The output is an inert :class:`DistillationPlan`: distilled candidates (still
subject to the downstream grounding / shadow / regression / promotion gates),
plus the HIL queue (sensitivity holds + uncertain classifications), the
deterministic drops, the retirement requests from deletions, and the snapshot to
persist for the next incremental run. Nothing here mutates the catalog or
executes - promotion stays a separate, explicit, human-gated step.

Layering: lives in the pipeline layer, composes the ``shared/providers`` seams
(:class:`ManualSource`, :class:`ManualClassifier`, :class:`Distiller`) with the
deterministic distill helpers. MUST NOT import ``core/``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from fdai.rule_catalog.pipeline.distill.freshness import (
    RetirementRequest,
    diff_snapshot,
    plan_retirements,
    snapshot_of,
)
from fdai.rule_catalog.pipeline.distill.sensitivity import scan_sensitivity
from fdai.rule_catalog.pipeline.distill.triage import (
    TriageDrop,
    TriagePolicy,
    dedupe_exact,
    prioritize,
    triage_filter,
)
from fdai.shared.providers.distiller import DistillationResult, Distiller
from fdai.shared.providers.manual_classifier import ManualClassifier, ProcedureVerdict
from fdai.shared.providers.manual_source import ManualCandidate, ManualSource


@dataclass(frozen=True, slots=True)
class HeldManual:
    """A candidate diverted to HIL rather than auto-distilled.

    ``reason`` is a compact, value-free tag (``sensitivity:secret,pii`` or
    ``classifier:uncertain``) - safe to log and surface, never the secret text.
    """

    candidate: ManualCandidate
    reason: str


@dataclass(frozen=True, slots=True)
class DistilledManual:
    """One manual that passed every gate and was distilled into candidates."""

    candidate: ManualCandidate
    result: DistillationResult


@dataclass(frozen=True, slots=True)
class DistillationPlan:
    """Inert output of one build-time distillation pass.

    ``distilled`` still faces the downstream grounding / shadow / regression /
    promotion gates before anything can enforce. ``held`` is the HIL queue,
    ``rejected`` is what the classifier judged not a procedure, ``filtered`` is
    the deterministic triage / dedupe drops, ``retirements`` tombstones rules
    from deleted manuals, and ``snapshot`` is persisted for the next run.

    ``suspected_source_outage`` is set when the source returned an empty listing
    while the prior snapshot was non-empty. That pattern (a failed mount, an auth
    lapse) is indistinguishable from "every manual was deleted", so the pass
    fails closed: no retirements are planned, nothing is distilled, and
    ``snapshot`` echoes the prior snapshot unchanged so the caller does not wipe
    it. The caller surfaces the outage instead of tombstoning the whole catalog.
    """

    distilled: tuple[DistilledManual, ...] = ()
    held: tuple[HeldManual, ...] = ()
    rejected: tuple[ManualCandidate, ...] = ()
    filtered: tuple[TriageDrop, ...] = ()
    retirements: tuple[RetirementRequest, ...] = ()
    snapshot: Mapping[str, str] = field(default_factory=dict)
    suspected_source_outage: bool = False

    @property
    def distilled_candidate_count(self) -> int:
        return sum(len(d.result.candidates) for d in self.distilled)


def _sensitivity_reason(labels: list[str]) -> str:
    return "sensitivity:" + ",".join(sorted(set(labels)))


async def build_distillation_plan(
    *,
    source: ManualSource,
    classifier: ManualClassifier,
    distiller: Distiller,
    policy: TriagePolicy | None = None,
    previous_snapshot: Mapping[str, str] | None = None,
    incident_refs: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> DistillationPlan:
    """Run one incremental, build-time distillation pass over ``source``.

    Only new or content-changed manuals (per the freshness diff) are processed;
    deletions become retirement requests. Every processed manual passes the
    deterministic triage filter and exact-dedupe, is classified, and - only when
    the classifier says PROCEDURE and the sensitivity scan is CLEAR - is
    distilled. Uncertain classifications and sensitivity holds route to HIL.
    """
    active_policy = policy or TriagePolicy()
    prior = previous_snapshot or {}

    current = await source.list_candidates()

    # Blast-radius guard: an empty listing over a non-empty prior snapshot is
    # indistinguishable from a source outage (failed mount / auth lapse). Fail
    # closed - never tombstone the whole distilled catalog on a transient empty
    # source. Preserve the prior snapshot so the next run recovers.
    if not current and prior:
        return DistillationPlan(suspected_source_outage=True, snapshot=dict(prior))

    snapshot = snapshot_of(current)
    delta = diff_snapshot(prior, current)
    retirements = plan_retirements(delta)

    triage = triage_filter(delta.upserted, active_policy, now=now)
    unique, dup_drops = dedupe_exact(triage.kept)
    filtered = triage.dropped + dup_drops

    classified = await classifier.classify(unique)
    procedures: list[ManualCandidate] = []
    rejected: list[ManualCandidate] = []
    held: list[HeldManual] = []
    for item in classified:
        if item.verdict is ProcedureVerdict.PROCEDURE:
            procedures.append(item.candidate)
        elif item.verdict is ProcedureVerdict.NOT_PROCEDURE:
            rejected.append(item.candidate)
        else:
            held.append(HeldManual(candidate=item.candidate, reason="classifier:uncertain"))

    distilled: list[DistilledManual] = []
    for candidate in prioritize(procedures, incident_refs=incident_refs):
        document = await source.fetch(candidate.doc_id)
        if document is None:
            # Vanished between list and fetch - nothing to compile, no error.
            continue
        report = scan_sensitivity(document)
        if not report.is_clear:
            reason = _sensitivity_reason([f.label for f in report.findings])
            held.append(HeldManual(candidate=candidate, reason=reason))
            continue
        result = await distiller.distill(document)
        distilled.append(DistilledManual(candidate=candidate, result=result))

    return DistillationPlan(
        distilled=tuple(distilled),
        held=tuple(held),
        rejected=tuple(rejected),
        filtered=filtered,
        retirements=retirements,
        snapshot=snapshot,
    )


__all__ = [
    "DistillationPlan",
    "DistilledManual",
    "HeldManual",
    "build_distillation_plan",
]
