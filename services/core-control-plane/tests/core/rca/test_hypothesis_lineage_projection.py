from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

from fdai.core.rca.hypothesis import (
    CausalClosure,
    CausalEvidenceAssessment,
    CausalHypothesisRecord,
    build_causal_hypothesis,
    close_causal_hypothesis,
)
from fdai.core.rca.projection import CausalHypothesisProjector
from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

_NOW = datetime(2026, 8, 12, tzinfo=UTC)
_ProjectionCall = tuple[tuple[OntologyObjectRecord, ...], tuple[OntologyLinkRecord, ...]]


class _Store:
    def __init__(self) -> None:
        self.calls: list[_ProjectionCall] = []

    async def get_object(self, _object_id: str) -> OntologyObjectRecord | None:
        return None

    async def replace_subgraph(
        self,
        *,
        objects: tuple[OntologyObjectRecord, ...],
        links: tuple[OntologyLinkRecord, ...],
        **_kwargs: object,
    ) -> None:
        self.calls.append((objects, links))


def _hypothesis() -> CausalHypothesisRecord:
    return build_causal_hypothesis(
        incident_id="incident-1",
        cause_ref="run-1",
        effect_ref="effect-1",
        mechanism="scale_reduces_latency",
        graph_revision="graph-1",
        evidence_cutoff=_NOW,
        method_version="causal-v1",
        evidence_grade=CausalEvidenceGrade.PREDICTIVE_PRECEDENCE,
        assessment=CausalEvidenceAssessment(
            temporal_precedence=1.0,
            topological_reachability=1.0,
            mechanism_fit=1.0,
            intervention_consistency=0.5,
            evidence_completeness=1.0,
            supporting_refs=("support-1",),
            refuting_refs=("refute-1",),
        ),
        created_at=_NOW,
    )


async def test_late_revision_preserves_balanced_evidence_and_challenger_basis() -> None:
    store = _Store()
    prior = _hypothesis()
    revised = close_causal_hypothesis(
        prior,
        closure=CausalClosure.INCONCLUSIVE,
        outcome_ref="outcome-1",
        created_at=_NOW + timedelta(minutes=6),
    )

    async with asyncio.timeout(0.5):
        await CausalHypothesisProjector(store=cast(OntologyInstanceStore, store)).project(
            revised,
            finding_id="finding-1",
            supporting_evidence_ids=("support-1",),
            refuting_evidence_ids=("refute-1",),
            outcome_ids=("outcome-1",),
            previous_hypothesis_id=prior.hypothesis_id,
            informed_expected_effect_ids=("effect-1",),
        )

    _, links = store.calls[0]
    assert {(item.link_type, item.from_id, item.to_id) for item in links} >= {
        ("evidence_supports_hypothesis", "support-1", revised.hypothesis_id),
        ("evidence_refutes_hypothesis", "refute-1", revised.hypothesis_id),
        ("outcome_tests_hypothesis", "outcome-1", revised.hypothesis_id),
        (
            "hypothesis_precedes_hypothesis",
            prior.hypothesis_id,
            revised.hypothesis_id,
        ),
        (
            "hypothesis_informs_expected_effect",
            revised.hypothesis_id,
            "effect-1",
        ),
    }
    assert revised.closure is CausalClosure.INCONCLUSIVE
