"""Forseti-owned typed-proposal review evidence for the durable Twin repository."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.core.assurance_twin.proposal_effects import PredictedChangeSet
from fdai.core.assurance_twin.report import build_posture_assessment_report
from fdai.core.assurance_twin.typed_proposal import (
    TYPED_PROPOSAL_EVIDENCE_KIND,
    target_material,
)
from fdai.delivery.assurance_twin_evidence_clock import (
    AssuranceTwinEvidenceClockContentionError,
    StateStoreTwinEvidenceClock,
)
from fdai.delivery.assurance_twin_evidence_codec import (
    rule_assessment_body,
    valid_digest,
    validate_common,
    validate_findings,
)
from fdai.delivery.assurance_twin_writers import AssuranceTwinPublishRequest, request_key
from fdai.delivery.persistence.state_store_assurance_twin_posture import (
    _change_review_body,
    evidence_body_digest,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.iac_review import IacReview
from fdai.shared.providers.projection import Finding
from fdai.shared.providers.state_store import StateStore

_LOG = logging.getLogger(__name__)
_PREFIX = "runtime:assurance-twin-evidence:"


class AssuranceTwinReviewEvidenceMixin:
    """Record exact typed-proposal reviews; Terraform plans are never an input."""

    _store: StateStore
    _clock: StateStoreTwinEvidenceClock

    async def review_evidence_state(
        self,
        request: AssuranceTwinPublishRequest,
    ) -> Mapping[str, Any] | None:
        """Return the raw retained review evidence row for Forseti's follow-up."""

        return await self._store.read_state(_state_key(request))

    async def retire_unconfirmed_request(self, request: AssuranceTwinPublishRequest) -> bool:
        """Stop relaying review evidence that the writer can no longer commit.

        Returns ``True`` when the exact unconfirmed request is, or already was,
        superseded. A request the writer already confirmed is never retired; the
        compare-and-set loses to a concurrent confirmation instead.
        """

        key = _state_key(request)
        current = await self._store.read_state(key)
        if current is None or current.get("writer_status") == "confirmed":
            return False
        if current.get("request_status") == "superseded":
            return True
        revision = current.get("revision")
        if (
            current.get("request_status") != "pending"
            or not isinstance(revision, int)
            or isinstance(revision, bool)
        ):
            return False
        return await self._store.compare_and_set_state_with_audit(
            key,
            {**dict(current), "revision": revision + 1, "request_status": "superseded"},
            expected_revision=revision,
            audit_entry={
                "kind": "assurance_twin_evidence_request_superseded",
                "producer_principal": "Forseti",
                "idempotency_key": request.idempotency_key,
                "source_revision": request.source_revision,
                "execution_authority": False,
            },
        )

    async def _write_exact(
        self,
        request: AssuranceTwinPublishRequest,
        value: Mapping[str, Any],
    ) -> AssuranceTwinPublishRequest:
        raise NotImplementedError

    async def record_review(
        self,
        *,
        review_key: str,
        change_set: PredictedChangeSet,
        source_revision: str,
        findings: tuple[Finding, ...],
        evaluated_rule_ids: tuple[str, ...],
        rule_coverage_refs: tuple[str, ...],
        rule_set_revision: str,
        rule_generation_revision: str,
        generated_at: datetime,
        fresh_until: datetime,
        correlation_id: str,
    ) -> AssuranceTwinPublishRequest:
        """Record one complete typed-proposal review for a content-free request.

        The review body names the proposal ref as its opaque change handle. Findings
        may cite only the proposal's own targets, and the verdict is derived from
        the complete finding set, never supplied by the caller.
        """

        validate_common(
            source_key=review_key,
            source_revision=source_revision,
            evaluated_rule_ids=evaluated_rule_ids,
            coverage_refs=rule_coverage_refs,
            generated_at=generated_at,
            fresh_until=fresh_until,
            correlation_id=correlation_id,
        )
        validate_findings(findings, evaluated_rule_ids)
        if not valid_digest(rule_set_revision) or not valid_digest(rule_generation_revision):
            raise ValueError("Assurance Twin Rule generation revision is invalid")
        proposal = change_set.proposal
        if any(finding.resource not in proposal.targets for finding in findings):
            raise ValueError("Assurance Twin review findings exceed the proposal targets")
        request = AssuranceTwinPublishRequest(
            kind="review",
            source_key=review_key,
            source_revision=source_revision,
            correlation_id=correlation_id,
            idempotency_key=request_key("review", review_key, source_revision),
        )
        generated_at = await self._clock.stable_generated_at(
            request,
            proposed=generated_at,
            fresh_until=fresh_until,
        )
        validate_common(
            source_key=review_key,
            source_revision=source_revision,
            evaluated_rule_ids=evaluated_rule_ids,
            coverage_refs=rule_coverage_refs,
            generated_at=generated_at,
            fresh_until=fresh_until,
            correlation_id=correlation_id,
        )
        generated = generated_at.astimezone(UTC).isoformat()
        judged = build_posture_assessment_report(
            scope=proposal.proposal_ref,
            generated_at=generated,
            mode=Mode.SHADOW,
            findings=findings,
        )
        what_if_digest = change_set.what_if.what_if_digest
        effect_digest = change_set.effect.effect_digest
        review = IacReview(
            pr_ref=proposal.proposal_ref,
            review_key=review_key,
            findings=findings,
            verdict=judged.verdict.value,
            mode=Mode.SHADOW,
            generated_at=generated,
            metadata={
                "source_revision": source_revision,
                "evidence_kind": TYPED_PROPOSAL_EVIDENCE_KIND,
                "action_type": proposal.action_type,
                "action_type_version": proposal.action_type_version,
                "proposal_digest": proposal.proposal_digest,
                "what_if_digest": what_if_digest,
                "effect_digest": effect_digest,
                "change_digest": change_set.change_digest,
                "inventory_revision": change_set.inventory_revision,
            },
        )
        evidence_refs = sorted(
            {
                proposal.proposal_digest,
                what_if_digest,
                effect_digest,
                change_set.change_digest,
                *change_set.what_if.evidence_refs,
            }
        )
        body = _change_review_body(review, freshness="fresh", reason_codes=())
        value = {
            "kind": "assurance_twin_retained_review",
            "revision": 1,
            "request": request.model_dump(mode="json"),
            "request_status": "pending",
            "writer_status": "pending",
            "source_revision": source_revision,
            "fresh_until": fresh_until.astimezone(UTC).isoformat(),
            "coverage_refs": sorted({*rule_coverage_refs, *evidence_refs}),
            "complete": True,
            "conflict": False,
            "rule_assessment": rule_assessment_body(
                source_revision=source_revision,
                findings=findings,
                evaluated_rule_ids=evaluated_rule_ids,
                coverage_refs=rule_coverage_refs,
                rule_set_revision=rule_set_revision,
                rule_generation_revision=rule_generation_revision,
                inventory_revision=change_set.inventory_revision,
            ),
            "typed_proposal": {
                "source_revision": source_revision,
                "proposal_ref": proposal.proposal_ref,
                "action_type": proposal.action_type,
                "action_type_version": proposal.action_type_version,
                "proposal_digest": proposal.proposal_digest,
                "parameters_digest": proposal.parameters_digest,
                "targets": target_material(proposal.targets),
                "what_if_digest": what_if_digest,
                "effect_digest": effect_digest,
                "change_digest": change_set.change_digest,
                "inventory_revision": change_set.inventory_revision,
                "evidence_refs": evidence_refs,
                "complete": True,
            },
            "record": body,
            "evidence_digest": evidence_body_digest(body),
        }
        written = await self._write_exact(request, value)
        try:
            await self._clock.release(request)
        except AssuranceTwinEvidenceClockContentionError:
            _LOG.warning(
                "assurance_twin_evidence_clock_release_deferred",
                extra={"kind": request.kind},
            )
        return written


def _state_key(request: AssuranceTwinPublishRequest) -> str:
    return f"{_PREFIX}{request.idempotency_key.removeprefix('sha256:')}"


__all__ = ["AssuranceTwinReviewEvidenceMixin"]
