from __future__ import annotations

from typing import Any, cast

import pytest

from fdai.core.conversation_assurance import (
    AdequacyCandidateKind,
    AdequacyReviewState,
    OntologyAdequacyReview,
)
from fdai.delivery.persistence import StateStoreOntologyAdequacyReviewSink


class _Store:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}
        self.audits: list[dict[str, Any]] = []

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: dict[str, Any],
        audit_entry: dict[str, Any],
    ) -> bool:
        if key in self.values:
            return False
        self.values[key] = dict(value)
        self.audits.append(dict(audit_entry))
        return True

    async def read_state(self, key: str) -> dict[str, Any] | None:
        return self.values.get(key)


def _review() -> OntologyAdequacyReview:
    return OntologyAdequacyReview(
        review_id="ontology-adequacy:" + "a" * 64,
        attribution_id="answer-failure:" + "b" * 64,
        state=AdequacyReviewState.HELD,
        candidate_kind=AdequacyCandidateKind.DYNAMIC_MODEL,
        competency_question_digest="c" * 64,
        ontology_release="sha256:" + "d" * 64,
        graph_revision="graph-1",
        evidence_refs=("evidence:1",),
        reason_codes=("gap_not_reproduced",),
    )


async def test_state_store_sink_is_idempotent_and_audited() -> None:
    store = _Store()
    sink = StateStoreOntologyAdequacyReviewSink(cast(Any, store))

    await sink.submit(_review())
    await sink.submit(_review())

    assert len(store.values) == 1
    assert len(store.audits) == 1
    assert store.audits[0]["actor"] == "Muninn"
    assert store.audits[0]["mode"] == "shadow"


async def test_state_store_sink_rejects_idempotency_conflict() -> None:
    store = _Store()
    sink = StateStoreOntologyAdequacyReviewSink(cast(Any, store))
    await sink.submit(_review())
    key = next(iter(store.values))
    store.values[key]["state"] = "ready"

    with pytest.raises(ValueError, match="idempotency conflict"):
        await sink.submit(_review())
