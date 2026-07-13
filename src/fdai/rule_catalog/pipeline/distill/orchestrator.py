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

from collections.abc import Mapping, Sequence
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
from fdai.shared.providers.manual_classifier import (
    ClassifiedManual,
    ManualClassifier,
    ProcedureVerdict,
)
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


def _require_unique_identities(candidates: Sequence[ManualCandidate]) -> None:
    """Fail closed if a source lists a duplicate ``source_ref`` or ``doc_id``.

    The snapshot and retirement logic key on these identities; a duplicate would
    silently collide (last wins), dropping a manual from the snapshot and later
    mis-firing it as a deletion. A fork source that violates the uniqueness
    contract is a boundary error, not something to paper over.
    """
    seen_refs: set[str] = set()
    seen_ids: set[str] = set()
    for candidate in candidates:
        if candidate.source_ref in seen_refs:
            raise ValueError(
                f"ManualSource returned a duplicate source_ref: {candidate.source_ref!r}"
            )
        if candidate.doc_id in seen_ids:
            raise ValueError(
                f"ManualSource returned a duplicate doc_id: {candidate.doc_id!r}"
            )
        seen_refs.add(candidate.source_ref)
        seen_ids.add(candidate.doc_id)


def _require_classified_covers(
    inputs: Sequence[ManualCandidate],
    classified: Sequence[ClassifiedManual],
) -> None:
    """Fail closed if the classifier did not return exactly one verdict per input.

    A silently dropped candidate would get no verdict yet still be recorded in
    the snapshot as "seen", losing the manual forever; an extra or duplicated
    verdict would double-process one. The classifier is a fork seam, so its
    output is validated at this boundary rather than trusted.
    """
    input_refs = {c.source_ref for c in inputs}
    out_refs = [c.candidate.source_ref for c in classified]
    if len(out_refs) != len(input_refs) or set(out_refs) != input_refs:
        raise ValueError(
            "ManualClassifier.classify MUST return exactly one verdict per input "
            f"candidate (got {len(out_refs)} for {len(input_refs)} inputs)"
        )


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

    _require_unique_identities(current)

    delta = diff_snapshot(prior, current)
    retirements = plan_retirements(delta)

    triage = triage_filter(delta.upserted, active_policy, now=now)
    unique, dup_drops = dedupe_exact(triage.kept)
    filtered = triage.dropped + dup_drops

    classified = await classifier.classify(unique)
    _require_classified_covers(unique, classified)
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

    # Do not record sensitivity-held docs in the snapshot: they carry an
    # unresolved secret and were not distilled, so marking them "seen" would
    # drop them from the HIL queue on the next unchanged run. Excluding them
    # re-surfaces the secret every run until the content changes or a human
    # resolves it. Uncertain / rejected / distilled outcomes are content- or
    # decision-terminal and stay recorded so deletion tracking still works.
    sensitivity_held = {
        held_item.candidate.source_ref
        for held_item in held
        if held_item.reason.startswith("sensitivity:")
    }
    snapshot = {
        ref: sha for ref, sha in snapshot_of(current).items() if ref not in sensitivity_held
    }

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
