"""Read independently admitted alert evidence without producing verification or authority.

Only governed producers write these private records. Binding digests are not verification;
the injected shared admission provider must resolve the exact independently verified receipt.
No provider, directory, model, credential, or synthetic fallback is created here.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import datetime

from fdai_service_contracts.alert_noise import AlertEvidence, digest_record
from fdai_service_contracts.alert_noise_evaluation import EvaluationReceipt
from fdai_service_contracts.alert_noise_plan import AlertTreatment
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.delivery.alert_noise_records import (
    AdmittedAlertRecord as AdmittedAlertRecord,
)
from fdai.delivery.alert_noise_records import (
    alert_scope_digest as alert_scope_digest,
)
from fdai.delivery.alert_noise_records import (
    exact_alert_model as exact_alert_model,
)
from fdai.delivery.alert_noise_records import (
    read_admitted_alert_record as read_admitted_alert_record,
)
from fdai.shared.providers.alert_noise import AlertEvidenceSource
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.state_store import StateStore

ALERT_SCOPE_EVIDENCE_PURPOSE = "alert-noise-scope-evidence"
ALERT_EVALUATION_PURPOSE = "alert-noise-evaluation"
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
_PRINCIPAL = re.compile(r"principal:[a-f0-9]{64}")
_SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}")


def alert_evidence_binding_digest(*, base_digest: str, evidence: AlertEvidence) -> str:
    """Hash enrichment plus its exact native base, excluding only the recursive revision field."""
    if _DIGEST.fullmatch(base_digest) is None:
        raise AlertExecutionHeld("alert_evidence_base_invalid")
    body = evidence.model_dump(mode="json")
    body["stamp"].pop("revision")
    return content_digest({"base_digest": base_digest, "evidence": body})


class AdmittedAlertEvidenceSource:
    """Enrich the real reader only from a current independently verified private supplement.

    Key: alert-noise:scope-evidence:<scope_ref>. Payload: {base_digest, evidence}, where
    evidence is a full AlertEvidence and its revision is alert_evidence_binding_digest.
    Known classification and all native configuration remain immutable. Unknown classification,
    ownership, incident state, directory/delivery evidence and reverse coverage require the DE
    producer's independent proof. An absent supplement returns the actual partial base unchanged.
    """

    def __init__(
        self,
        *,
        inner: AlertEvidenceSource,
        store: StateStore,
        admissions: DecisionEvidenceAdmissionProvider | None,
        scope_ref: str,
        tenant_ref: str,
        source_revision: str,
        clock: Callable[[], datetime],
    ) -> None:
        """Bind one real reader and its independent admission source to an exact opaque scope."""
        self._scope = alert_scope_digest(tenant_ref=tenant_ref, scope_ref=scope_ref)
        if _SOURCE.fullmatch(source_revision) is None:
            raise ValueError("alert evidence source revision MUST be explicit")
        self._inner, self._store, self._admissions = inner, store, admissions
        self._scope_ref, self._tenant_ref = scope_ref, tenant_ref
        self._revision, self._clock = source_revision, clock

    async def collect(self, *, now: datetime) -> AlertEvidence:
        """Collect native evidence first; never replace a failed read with a ledger-only answer."""
        try:
            async with asyncio.timeout(65):
                return await self._collect(now)
        except AlertExecutionHeld:
            raise
        except Exception:
            raise AlertExecutionHeld("alert_evidence_unavailable") from None

    async def _collect(self, now: datetime) -> AlertEvidence:
        base = AlertEvidence.model_validate(await self._inner.collect(now=now))
        if (
            base.stamp.synthetic
            or base.stamp.scope_ref != self._scope_ref
            or base.stamp.tenant_ref != self._tenant_ref
            or not base.stamp.current_at(now)
            or any(
                _PRINCIPAL.fullmatch(ref) is None
                for audience in base.audiences
                for ref in audience.member_refs
            )
            or any(
                row.acknowledger_ref is not None
                and _PRINCIPAL.fullmatch(row.acknowledger_ref) is None
                for row in base.deliveries
            )
        ):
            raise AlertExecutionHeld("alert_native_evidence_invalid")
        record = await read_admitted_alert_record(
            self._store,
            self._admissions,
            "alert-noise:scope-evidence:" + self._scope_ref,
            ALERT_SCOPE_EVIDENCE_PURPOSE,
            self._scope,
            self._revision,
            self._clock(),
        )
        if not base.stamp.current_at(self._clock()):
            raise AlertExecutionHeld("alert_native_evidence_expired")
        if record is None:
            return base
        payload = record.payload
        if set(payload) != {"base_digest", "evidence"} or payload["base_digest"] != digest_record(
            base
        ):
            raise AlertExecutionHeld("alert_supplement_base_mismatch")
        enriched = exact_alert_model(AlertEvidence, payload["evidence"])
        self._require_supplement(base, enriched, record)
        record.require_current(now=self._clock())
        return enriched

    def _require_supplement(
        self, base: AlertEvidence, enriched: AlertEvidence, record: AdmittedAlertRecord
    ) -> None:
        before, after = base.stamp, enriched.stamp
        if (
            after.source != before.source
            or after.scope_ref != before.scope_ref
            or after.tenant_ref != before.tenant_ref
            or after.observed_at != before.observed_at
            or after.recorded_at < before.recorded_at
            or not after.current_at(self._clock())
            or after.recorded_at > record.admission.verified_at
            or after.valid_until > min(before.valid_until, record.admission.valid_until)
            or after.coverage != "complete"
            or after.reasons
            or after.synthetic
            or enriched.history_coverage != "complete"
            or enriched.delivery_coverage != "complete"
            or after.revision
            != alert_evidence_binding_digest(base_digest=digest_record(base), evidence=enriched)
            or (enriched.window_start, enriched.window_end) != (base.window_start, base.window_end)
            or enriched.processing_rules != base.processing_rules
        ):
            raise AlertExecutionHeld("alert_supplement_binding_mismatch")
        allowed = {
            "service_ref",
            "classification",
            "ownership_verified",
            "iac_owned",
            "active_incident",
        }
        if len(base.rules) != len(enriched.rules) or len(base.groups) != len(enriched.groups):
            raise AlertExecutionHeld("alert_supplement_configuration_changed")
        for old, new in zip(base.rules, enriched.rules, strict=True):
            if old.model_dump(exclude=allowed) != new.model_dump(exclude=allowed) or (
                old.classification != "unknown" and old.classification != new.classification
            ):
                raise AlertExecutionHeld("alert_supplement_configuration_changed")
        for old_group, new_group in zip(base.groups, enriched.groups, strict=True):
            if (
                old_group.model_dump(exclude={"rule_refs", "reverse_complete"})
                != new_group.model_dump(exclude={"rule_refs", "reverse_complete"})
                or not set(old_group.rule_refs).issubset(new_group.rule_refs)
                or not set(new_group.rule_refs).issubset(row.ref for row in enriched.rules)
                or not new_group.reverse_complete
            ):
                raise AlertExecutionHeld("alert_supplement_dependencies_changed")
        if tuple(row.ref for row in base.audiences) != tuple(row.ref for row in enriched.audiences):
            raise AlertExecutionHeld("alert_supplement_audiences_changed")
        for old_audience, new_audience in zip(base.audiences, enriched.audiences, strict=True):
            if (
                new_audience.kind != old_audience.kind
                or new_audience.coverage != "complete"
                or not set(old_audience.member_refs).issubset(new_audience.member_refs)
                or (
                    old_audience.coverage == "complete"
                    and set(old_audience.member_refs) != set(new_audience.member_refs)
                )
                or any(_PRINCIPAL.fullmatch(ref) is None for ref in new_audience.member_refs)
            ):
                raise AlertExecutionHeld("alert_supplement_directory_mismatch")
        deliveries = {row.ref: row for row in enriched.deliveries}
        if any(deliveries.get(row.ref) != row for row in base.deliveries) or any(
            row.acknowledger_ref is not None and _PRINCIPAL.fullmatch(row.acknowledger_ref) is None
            for row in enriched.deliveries
        ):
            raise AlertExecutionHeld("alert_supplement_history_changed")


def alert_evaluation_key(*, evidence: AlertEvidence, treatment: AlertTreatment) -> str:
    """Address one exact pre-plan comparison, never a latest rule-only evaluation result."""
    return "alert-noise:evaluation:" + content_digest(
        {
            "evidence_digest": digest_record(evidence),
            "treatment_digest": digest_record(treatment),
        }
    )


class StateStoreAlertEvaluationReader:
    """Read reviewed comparisons with payload {evidence_digest, treatment_digest, comparison}."""

    def __init__(
        self,
        *,
        store: StateStore,
        admissions: DecisionEvidenceAdmissionProvider | None,
        scope_ref: str,
        tenant_ref: str,
        source_revision: str,
        clock: Callable[[], datetime],
    ) -> None:
        """Bind reviewed comparison reads without installing a producer or default admission."""
        self._scope = alert_scope_digest(tenant_ref=tenant_ref, scope_ref=scope_ref)
        if _SOURCE.fullmatch(source_revision) is None:
            raise ValueError("alert evaluation source revision MUST be explicit")
        self._store, self._admissions, self._revision = store, admissions, source_revision
        self._clock = clock

    async def read(
        self, *, evidence: AlertEvidence, treatment: AlertTreatment, now: datetime
    ) -> EvaluationReceipt | None:
        """Return a current exact admitted threshold comparison; missing review stays unknown."""
        result = await self.read_admitted(evidence=evidence, treatment=treatment, now=now)
        return result[0] if result is not None else None

    async def read_admitted(
        self, *, evidence: AlertEvidence, treatment: AlertTreatment, now: datetime
    ) -> tuple[EvaluationReceipt, AdmittedAlertRecord] | None:
        """Retain admission and comparison for a later synchronous expiry check."""
        evidence, treatment = (
            AlertEvidence.model_validate(evidence),
            AlertTreatment.model_validate(treatment),
        )
        if treatment.kind != "evaluation":
            return None
        if (
            alert_scope_digest(
                tenant_ref=evidence.stamp.tenant_ref, scope_ref=evidence.stamp.scope_ref
            )
            != self._scope
            or evidence.stamp.synthetic
            or evidence.stamp.coverage != "complete"
            or not evidence.stamp.current_at(now)
        ):
            raise AlertExecutionHeld("alert_evaluation_scope_mismatch")
        record = await read_admitted_alert_record(
            self._store,
            self._admissions,
            alert_evaluation_key(evidence=evidence, treatment=treatment),
            ALERT_EVALUATION_PURPOSE,
            self._scope,
            self._revision,
            now,
        )
        if record is None:
            return None
        payload = record.payload
        if (
            set(payload) != {"evidence_digest", "treatment_digest", "comparison"}
            or payload["evidence_digest"] != digest_record(evidence)
            or payload["treatment_digest"] != digest_record(treatment)
        ):
            raise AlertExecutionHeld("alert_evaluation_binding_mismatch")
        comparison = exact_alert_model(EvaluationReceipt, payload["comparison"])
        rule = next((row for row in evidence.rules if row.ref == treatment.target_ref), None)
        at = self._clock()
        if (
            at < now
            or not evidence.stamp.current_at(at)
            or rule is None
            or rule.kind not in {"metric", "log"}
            or comparison.rule_ref != rule.ref
            or comparison.rule_revision != rule.revision
            or comparison.baseline != rule.evaluation
            or comparison.treatment != treatment.evaluation
            or not comparison.accepted
            or not comparison.evaluated_at <= at < comparison.expires_at
            or comparison.evaluated_at > record.admission.verified_at
            or comparison.baseline.model_dump(exclude={"threshold"})
            != comparison.treatment.model_dump(exclude={"threshold"})
            or comparison.baseline.threshold == comparison.treatment.threshold
        ):
            raise AlertExecutionHeld("alert_evaluation_comparison_mismatch")
        record.require_current(now=at)
        return comparison, record
