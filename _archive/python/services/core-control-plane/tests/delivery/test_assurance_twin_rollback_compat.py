"""Rows this release writes keep the exact shapes the previous release reads.

Core and the Operator deploy separately and either can roll back. The previous release
recomputes evidence digests over every top-level field it does not know as provenance,
so a new top-level field would turn its readers' view of these rows into digest
mismatches, publisher failures, or replay conflicts. The key sets below were captured
from the previous release's own ledger, conflict, and outbox writers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.assurance_twin import build_posture_assessment_report
from fdai.core.assurance_twin.posture_activity import (
    build_change_review_activity,
    build_posture_report_activity,
)
from fdai.delivery import assurance_twin_publication
from fdai.delivery.persistence import state_store_assurance_twin_posture as ledger_module
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    StateStoreAssuranceTwinPostureLedger,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.projection import Finding, ResourceRef
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_operator_service import assurance_twin_posture_projection as operator_projection
from fdai_service_contracts import OperationalFreshness

from tests.delivery.assurance_twin_review_harness import (
    PublicAccessPolicy,
    TwinHarness,
    proposal,
    reviewed_effect,
    what_if,
)

_PROVENANCE = frozenset(
    {
        "activity_id",
        "correlation_id",
        "evidence_digest",
        "evidence_source_revision",
        "source_confirmed",
        "conflict",
        "revision",
        "publication_outbox",
    }
)
_POSTURE = frozenset(
    {
        "activity_id",
        "blocks_action",
        "correlation_id",
        "evidence_digest",
        "evidence_source_revision",
        "findings",
        "freshness",
        "generated_at",
        "highest_severity",
        "mode",
        "publication_outbox",
        "reason_codes",
        "resource_count",
        "revision",
        "rule_count",
        "scope",
        "severity_counts",
        "source_confirmed",
        "verdict",
    }
)
_REVIEW = frozenset(
    {
        "activity_id",
        "correlation_id",
        "evidence_digest",
        "evidence_source_revision",
        "findings",
        "freshness",
        "generated_at",
        "metadata",
        "mode",
        "pr_ref",
        "publication_outbox",
        "reason_codes",
        "review_key",
        "revision",
        "source_confirmed",
        "verdict",
    }
)
_PLACEHOLDER = frozenset(
    {
        "conflict",
        "evidence_digest",
        "evidence_source_revision",
        "findings",
        "freshness",
        "generated_at",
        "mode",
        "publication_outbox",
        "reason_codes",
        "revision",
    }
)
_OUTBOX = frozenset({"activity", "evidence_digest", "owner_agent", "published", "record_revision"})
_T1, _T2 = "2026-09-28T01:00:00+00:00", "2026-09-28T01:05:00+00:00"


def test_every_digest_reader_excludes_the_previous_release_provenance_exactly() -> None:
    assert ledger_module._PROVENANCE_FIELDS == _PROVENANCE
    assert assurance_twin_publication._PROVENANCE == _PROVENANCE
    assert operator_projection._PROVENANCE_FIELDS == _PROVENANCE


async def _record_posture(ledger: StateStoreAssuranceTwinPostureLedger, at: str, rule: str) -> None:
    findings = (
        (
            Finding(
                rule_id=rule,
                resource=ResourceRef("object-storage", "s"),
                severity="high",
                reason="r",
                evidence_refs=("e:1",),
            ),
        )
        if rule
        else ()
    )
    report = build_posture_assessment_report(
        scope="scope-a", generated_at=at, mode=Mode.SHADOW, findings=findings
    )
    activity = build_posture_report_activity(
        report, correlation_id="p", freshness=OperationalFreshness.FRESH
    )
    await ledger.record_posture_report(
        report,
        freshness="fresh",
        activity_id=activity.activity_id,
        correlation_id="p",
        evidence_source_revision=f"s-{at}-{rule}",
        source_confirmed=True,
        activity=activity,
    )


async def test_posture_rows_keep_the_previous_release_key_sets() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    key = "runtime:assurance-twin-posture:scope-a"
    shapes: list[frozenset[str]] = []

    await _record_posture(ledger, _T1, "")
    row = await store.read_state(key)
    assert row is not None and frozenset(row["publication_outbox"]) == _OUTBOX
    shapes.append(frozenset(row))
    await ledger.mark_published(
        key, owner="Heimdall", revision=row["revision"], digest=row["evidence_digest"]
    )
    await _record_posture(ledger, _T2, "")
    shapes.append(frozenset(await store.read_state(key) or {}))
    await _record_posture(ledger, _T2, "rule.y")
    tombstone = frozenset(await store.read_state(key) or {})
    await ledger.mark_source_conflict(
        owner="Heimdall",
        source_key="scope-b",
        generated_at=_T1,
        source_revision="s-9",
        rejected_evidence_digest="sha256:" + "0" * 64,
        correlation_id="p",
    )
    placeholder = frozenset(await store.read_state("runtime:assurance-twin-posture:scope-b") or {})

    assert shapes == [_POSTURE, _POSTURE]
    assert tombstone == _POSTURE | {"conflict"}
    assert placeholder == _PLACEHOLDER | {"scope"}


async def test_review_rows_keep_the_previous_release_key_sets() -> None:
    now = datetime.now(UTC) - timedelta(seconds=1)
    twin, bus = TwinHarness(now, effects=(reviewed_effect(),)), InMemoryEventBus()
    item = proposal()
    await twin.intake.submit(proposal=item, what_if=what_if(item, now), correlation_id="c-1")
    assert (await twin.producer.review_pending()).recorded == 1
    assert await twin.writer.process(await twin.relayed_request(bus))
    key = f"runtime:assurance-twin-review:{item.proposal_ref}"
    confirmed = await twin.store.read_state(key)
    assert confirmed is not None and frozenset(confirmed["publication_outbox"]) == _OUTBOX

    twin.evaluator.activate(
        PublicAccessPolicy(denied_values=frozenset({"enabled", "disabled"}), generation="9"),
        generation_time=now - timedelta(seconds=30),
    )
    later = what_if(item, now, observed_at=now - timedelta(seconds=10))
    await twin.intake.submit(proposal=item, what_if=later, correlation_id="c-2")
    assert (await twin.producer.review_pending()).recorded == 1
    assert await twin.writer.process(await twin.relayed_request(bus))
    superseded = await twin.store.read_state(key)
    assert superseded is not None and superseded["verdict"] == "blocked"

    assert frozenset(confirmed) == _REVIEW
    assert frozenset(superseded) == _REVIEW
    assert frozenset(await _tombstoned_review()) == _REVIEW | {"conflict"}
    await twin.ledger.mark_source_conflict(
        owner="Forseti",
        source_key="action-proposal:" + "b" * 64,
        generated_at=_T1,
        source_revision="r-9",
        rejected_evidence_digest="sha256:" + "0" * 64,
        correlation_id="c",
    )
    placeholder = await twin.store.read_state(
        "runtime:assurance-twin-review:action-proposal:" + "b" * 64
    )
    assert frozenset(placeholder or {}) == _PLACEHOLDER | {"review_key"}


async def _tombstoned_review() -> dict[str, Any]:
    store = InMemoryStateStore()
    ledger = StateStoreAssuranceTwinPostureLedger(store=store)
    ref = "action-proposal:" + "c" * 64
    for verdict, source in (("clear", "r-1"), ("needs_review", "r-2")):
        review = IacReview(
            pr_ref=ref,
            review_key=ref,
            findings=(),
            verdict=verdict,
            mode=Mode.SHADOW,
            generated_at=_T1,
            metadata={"evidence_kind": "typed_action_proposal"},
        )
        activity = build_change_review_activity(
            review, correlation_id="c", freshness=OperationalFreshness.FRESH
        )
        await ledger.record_proposal_review(
            review,
            freshness="fresh",
            activity_id=activity.activity_id,
            correlation_id="c",
            evidence_source_revision=source,
            source_confirmed=True,
            activity=activity,
        )
    row = await store.read_state(f"runtime:assurance-twin-review:{ref}")
    assert row is not None and row["conflict"] is not None
    return dict(row)
