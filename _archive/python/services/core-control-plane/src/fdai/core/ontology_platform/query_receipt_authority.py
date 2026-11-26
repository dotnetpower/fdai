"""Bounded issuance authority for secured ObjectSet query receipts."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.contracts.models import OntologyReleaseRef
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)

from .functions import FunctionInvocationContext
from .query_gateway import SecuredObjectSetQueryReceipt, SecuredObjectSetQueryResult


@dataclass(frozen=True, slots=True)
class _IssuedReceipt:
    receipt: SecuredObjectSetQueryReceipt


class SecuredQueryReceiptAuthority:
    """Issue and authenticate bounded query receipts without granting authority."""

    def __init__(
        self,
        *,
        max_receipts: int = 4096,
        max_presentation_age_seconds: int = 90,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= max_receipts <= 65_536:
            raise ValueError("secured query receipt bound MUST be between 1 and 65536")
        if not 1 <= max_presentation_age_seconds <= 3600:
            raise ValueError("presentation receipt age MUST be between 1 and 3600 seconds")
        self._max_receipts = max_receipts
        self._max_presentation_age_seconds = max_presentation_age_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._verification_context = object()
        self._issued: OrderedDict[str, _IssuedReceipt] = OrderedDict()
        self._results: dict[str, SecuredObjectSetQueryResult] = {}
        self._decision_evidence: dict[str, DecisionEvidenceAdmission | None] = {}

    @property
    def verification_context(self) -> object:
        """Return the opaque context bound into contextual ontology functions."""

        return self._verification_context

    def issue(
        self,
        result: SecuredObjectSetQueryResult,
        decision_evidence: DecisionEvidenceAdmission | None = None,
    ) -> None:
        """Retain one result and its independently verified admission when available."""

        receipt = result.receipt
        key = _receipt_key(receipt)
        issued = _IssuedReceipt(receipt=receipt)
        existing = self._issued.get(key)
        if existing is not None and existing != issued:
            raise ValueError("secured query receipt digest conflicts with issued content")
        self._issued[key] = issued
        self._results[key] = SecuredObjectSetQueryResult.model_validate(
            result.model_dump(mode="json")
        )
        self._decision_evidence[key] = decision_evidence
        self._issued.move_to_end(key)
        while len(self._issued) > self._max_receipts:
            evicted, _ = self._issued.popitem(last=False)
            self._results.pop(evicted, None)
            self._decision_evidence.pop(evicted, None)

    def resolve(self, evidence_refs: tuple[str, ...]) -> SecuredObjectSetQueryResult:
        """Return one issued secured result named by a dependency evidence ref."""

        result = self._resolve_issued(evidence_refs)
        digest = _receipt_key(result.receipt)
        if not self._admitted(result.receipt, self._decision_evidence.get(digest)):
            raise PermissionError("function dependency lacks verified decision evidence")
        return result

    def resolve_presentation_read(
        self,
        evidence_refs: tuple[str, ...],
        *,
        invocation_context: FunctionInvocationContext,
        expected_release: OntologyReleaseRef,
        expected_purpose: str,
    ) -> SecuredObjectSetQueryResult:
        """Authenticate one issued result for a no-authority presentation read."""

        result = self._resolve_issued(evidence_refs, invocation_context=invocation_context)
        receipt = result.receipt
        if (
            expected_purpose != "operations-review"
            or invocation_context.caller_agent != "Bragi"
            or invocation_context.caller_role != receipt.caller_role
            or invocation_context.principal_scope_digest != receipt.principal_scope_digest
            or (
                invocation_context.principal_ref is not None
                and receipt.principal_scope_digest is None
            )
            or invocation_context.purposes != (expected_purpose,)
            or receipt.ontology_release != expected_release
            or receipt.purpose != expected_purpose
            or result.materialization.definition.purpose != expected_purpose
        ):
            raise PermissionError("presentation read dependency scope does not match")
        age = (self._now() - receipt.observation_cutoff).total_seconds()
        if receipt.principal_scope_digest is not None and not (
            0 <= age <= self._max_presentation_age_seconds
        ):
            raise PermissionError("presentation read dependency is outside its validity window")
        return result

    def _resolve_issued(
        self,
        evidence_refs: tuple[str, ...],
        *,
        invocation_context: FunctionInvocationContext | None = None,
    ) -> SecuredObjectSetQueryResult:
        """Resolve one exact process-issued result without deciding its downstream use."""

        output_digests = tuple(
            ref.removeprefix("ontology-object-set-output:")
            for ref in evidence_refs
            if ref.startswith("ontology-object-set-output:")
        )
        lineage_digests = tuple(
            ref.removeprefix("ontology-object-set:")
            for ref in evidence_refs
            if ref.startswith("ontology-object-set:")
        )
        digests = output_digests or lineage_digests
        if len(digests) != 1:
            raise PermissionError("function dependency does not identify one issued ObjectSet")
        candidates = tuple(
            result
            for result in self._results.values()
            if result.receipt.projected_result_digest == digests[0]
            and (
                invocation_context is None
                or (
                    result.receipt.caller_role == invocation_context.caller_role
                    and result.receipt.principal_scope_digest
                    == invocation_context.principal_scope_digest
                )
            )
        )
        if len(candidates) != 1:
            raise PermissionError("function dependency does not identify one issued ObjectSet")
        result = candidates[0]
        return SecuredObjectSetQueryResult.model_validate(result.model_dump(mode="json"))

    def verify(
        self,
        *,
        receipt: SecuredObjectSetQueryReceipt,
        invocation_context: FunctionInvocationContext,
        expected_release: OntologyReleaseRef,
        expected_purpose: str,
        expected_result_digest: str,
        verification_context: object,
    ) -> bool:
        """Authenticate an issued receipt against its exact invocation tuple."""

        if verification_context is not self._verification_context:
            return False
        key = _receipt_key(receipt)
        issued = self._issued.get(key)
        retained = self._results.get(key)
        if issued is None or retained is None:
            return False
        return (
            receipt == issued.receipt == retained.receipt
            and receipt.projected_result_digest == expected_result_digest
            and receipt.ontology_release == expected_release
            and receipt.purpose == expected_purpose
            and invocation_context.purposes == (expected_purpose,)
            and invocation_context.caller_role == receipt.caller_role
            and invocation_context.principal_scope_digest == receipt.principal_scope_digest
            and expected_result_digest in invocation_context.evidence_refs
            and self._admitted(
                receipt,
                self._decision_evidence.get(key),
            )
        )

    def _admitted(
        self,
        receipt: SecuredObjectSetQueryReceipt,
        admission: DecisionEvidenceAdmission | None,
    ) -> bool:
        if admission is None:
            return False
        reasons = assess_decision_evidence_admission(
            admission,
            expected_evidence_digest=receipt.projected_result_digest,
            expected_scope_digest=secured_query_scope_digest(receipt),
            expected_purpose_id=receipt.purpose,
            expected_source_revision=receipt.ontology_release.digest,
            evaluated_at=self._now(),
        )
        return not reasons


def _receipt_key(receipt: SecuredObjectSetQueryReceipt) -> str:
    return content_digest(
        {"result": receipt.projected_result_digest, "scope": secured_query_scope_digest(receipt)}
    )


def secured_query_scope_digest(receipt: SecuredObjectSetQueryReceipt) -> str:
    """Return the canonical role, purpose, release, and source-generation scope."""

    return content_digest(
        {
            "caller_role": receipt.caller_role.value,
            "ontology_release": receipt.ontology_release.model_dump(mode="json"),
            "principal_scope_digest": receipt.principal_scope_digest,
            "purpose": receipt.purpose,
            "source_generation": receipt.source_generation,
        }
    )


__all__ = ["SecuredQueryReceiptAuthority", "secured_query_scope_digest"]
