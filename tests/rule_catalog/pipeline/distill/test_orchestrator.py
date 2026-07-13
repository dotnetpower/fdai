"""Tests for the build-time manual-distillation orchestrator (full stitch)."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.rule_catalog.pipeline.distill.orchestrator import build_distillation_plan
from fdai.rule_catalog.pipeline.distill.triage import TriagePolicy
from fdai.shared.providers.distiller import (
    CandidateKind,
    CoverageReport,
    DistillationResult,
    DistilledCandidate,
    ManualDocument,
)
from fdai.shared.providers.manual_classifier import ClassifiedManual, ProcedureVerdict
from fdai.shared.providers.manual_source import ManualCandidate


class FakeSource:
    def __init__(
        self,
        candidates: Sequence[ManualCandidate],
        docs: dict[str, ManualDocument],
    ) -> None:
        self._candidates = tuple(candidates)
        self._docs = docs

    async def list_candidates(self) -> Sequence[ManualCandidate]:
        return self._candidates

    async def fetch(self, doc_id: str) -> ManualDocument | None:
        return self._docs.get(doc_id)

    async def changes(self, since: str) -> Sequence[object]:  # noqa: ARG002
        return ()


class LabelClassifier:
    """PROCEDURE when labelled ``proc``, NOT_PROCEDURE when ``junk``, else UNCERTAIN."""

    async def classify(
        self, candidates: Sequence[ManualCandidate]
    ) -> Sequence[ClassifiedManual]:
        out: list[ClassifiedManual] = []
        for c in candidates:
            if "proc" in c.labels:
                verdict = ProcedureVerdict.PROCEDURE
            elif "junk" in c.labels:
                verdict = ProcedureVerdict.NOT_PROCEDURE
            else:
                verdict = ProcedureVerdict.UNCERTAIN
            out.append(ClassifiedManual(candidate=c, verdict=verdict))
        return tuple(out)


class OneRuleDistiller:
    async def distill(self, document: ManualDocument) -> DistillationResult:
        cand = DistilledCandidate(
            kind=CandidateKind.RULE,
            candidate_id=f"c-{document.doc_id}",
            source_ref=document.source_ref,
            source_section="S",
            source_lines=(1, 1),
        )
        return DistillationResult(
            candidates=(cand,), coverage=CoverageReport(total=1, covered=1)
        )


def _cand(
    doc_id: str, *, labels: tuple[str, ...] = (), sha: str | None = None
) -> ManualCandidate:
    return ManualCandidate(
        doc_id=doc_id,
        source_ref=f"drop://{doc_id}",
        labels=labels,
        content_sha=sha or f"sha-{doc_id}",
    )


def _doc(doc_id: str, text: str = "Restart the pod.") -> ManualDocument:
    return ManualDocument(doc_id=doc_id, text=text, source_ref=f"drop://{doc_id}")


async def test_full_flow_splits_by_verdict() -> None:
    cands = [
        _cand("run", labels=("proc",)),
        _cand("notes"),  # uncertain
        _cand("meeting", labels=("junk",)),
    ]
    docs = {"run": _doc("run"), "notes": _doc("notes"), "meeting": _doc("meeting")}
    plan = await build_distillation_plan(
        source=FakeSource(cands, docs),
        classifier=LabelClassifier(),
        distiller=OneRuleDistiller(),
    )
    assert [d.candidate.doc_id for d in plan.distilled] == ["run"]
    assert plan.distilled_candidate_count == 1
    assert [h.candidate.doc_id for h in plan.held] == ["notes"]
    assert plan.held[0].reason == "classifier:uncertain"
    assert [r.doc_id for r in plan.rejected] == ["meeting"]
    assert plan.snapshot == {
        "drop://run": "sha-run",
        "drop://notes": "sha-notes",
        "drop://meeting": "sha-meeting",
    }


async def test_sensitivity_hold_diverts_procedure_to_hil() -> None:
    cands = [_cand("run", labels=("proc",))]
    docs = {"run": _doc("run", text="Escalate to jane@contoso.example now.")}
    plan = await build_distillation_plan(
        source=FakeSource(cands, docs),
        classifier=LabelClassifier(),
        distiller=OneRuleDistiller(),
    )
    assert plan.distilled == ()
    assert len(plan.held) == 1
    assert plan.held[0].reason.startswith("sensitivity:")
    assert "email" in plan.held[0].reason


async def test_incremental_skips_unchanged() -> None:
    cands = [_cand("run", labels=("proc",), sha="v1")]
    docs = {"run": _doc("run")}
    previous = {"drop://run": "v1"}  # already distilled at v1
    plan = await build_distillation_plan(
        source=FakeSource(cands, docs),
        classifier=LabelClassifier(),
        distiller=OneRuleDistiller(),
        previous_snapshot=previous,
    )
    assert plan.distilled == ()  # unchanged -> not reprocessed
    assert plan.held == ()
    assert plan.rejected == ()


async def test_deletion_plans_retirement() -> None:
    cands = [_cand("kept", labels=("proc",), sha="v1")]
    docs = {"kept": _doc("kept")}
    previous = {"drop://kept": "v1", "drop://gone": "old"}
    plan = await build_distillation_plan(
        source=FakeSource(cands, docs),
        classifier=LabelClassifier(),
        distiller=OneRuleDistiller(),
        previous_snapshot=previous,
    )
    assert [r.source_ref for r in plan.retirements] == ["drop://gone"]


async def test_empty_source_over_nonempty_prior_is_outage_not_mass_deletion() -> None:
    # Blast-radius guard: a failed/empty source must not tombstone the whole
    # catalog. No retirements, nothing distilled, prior snapshot preserved.
    previous = {"drop://a": "1", "drop://b": "2", "drop://c": "3"}
    plan = await build_distillation_plan(
        source=FakeSource([], docs={}),
        classifier=LabelClassifier(),
        distiller=OneRuleDistiller(),
        previous_snapshot=previous,
    )
    assert plan.suspected_source_outage is True
    assert plan.retirements == ()
    assert plan.distilled == ()
    assert dict(plan.snapshot) == previous  # preserved, not wiped


async def test_empty_source_with_empty_prior_is_not_outage() -> None:
    # First run against an empty drop dir is legitimate, not an outage.
    plan = await build_distillation_plan(
        source=FakeSource([], docs={}),
        classifier=LabelClassifier(),
        distiller=OneRuleDistiller(),
    )
    assert plan.suspected_source_outage is False
    assert plan.snapshot == {}


async def test_vanished_document_is_skipped() -> None:
    cands = [_cand("run", labels=("proc",))]
    plan = await build_distillation_plan(
        source=FakeSource(cands, docs={}),  # listed but fetch returns None
        classifier=LabelClassifier(),
        distiller=OneRuleDistiller(),
    )
    assert plan.distilled == ()
    assert plan.held == ()


async def test_triage_policy_filters_before_classify() -> None:
    cands = [
        _cand("run", labels=("proc",)),
        _cand("draft", labels=("proc", "draft")),
    ]
    docs = {"run": _doc("run"), "draft": _doc("draft")}
    policy = TriagePolicy(excluded_labels=frozenset({"draft"}))
    plan = await build_distillation_plan(
        source=FakeSource(cands, docs),
        classifier=LabelClassifier(),
        distiller=OneRuleDistiller(),
        policy=policy,
    )
    assert [d.candidate.doc_id for d in plan.distilled] == ["run"]
    assert [f.candidate.doc_id for f in plan.filtered] == ["draft"]
    assert plan.filtered[0].reason == "carries excluded label"


async def test_exact_duplicates_are_filtered() -> None:
    cands = [
        _cand("a", labels=("proc",), sha="dup"),
        _cand("b", labels=("proc",), sha="dup"),
    ]
    docs = {"a": _doc("a"), "b": _doc("b")}
    plan = await build_distillation_plan(
        source=FakeSource(cands, docs),
        classifier=LabelClassifier(),
        distiller=OneRuleDistiller(),
    )
    # One survivor distilled, the other dropped as an exact duplicate.
    assert len(plan.distilled) == 1
    assert any(f.reason == "exact duplicate" for f in plan.filtered)
