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
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= max_receipts <= 65_536:
            raise ValueError("secured query receipt bound MUST be between 1 and 65536")
        self._max_receipts = max_receipts
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
        key = receipt.projected_result_digest
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
        if len(digests) != 1 or digests[0] not in self._results:
            raise PermissionError("function dependency does not identify one issued ObjectSet")
        result = self._results[digests[0]]
        if not self._admitted(result.receipt, self._decision_evidence.get(digests[0])):
            raise PermissionError("function dependency lacks verified decision evidence")
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
        issued = self._issued.get(expected_result_digest)
        retained = self._results.get(expected_result_digest)
        if issued is None or retained is None:
            return False
        return (
            receipt == issued.receipt == retained.receipt
            and receipt.projected_result_digest == expected_result_digest
            and receipt.ontology_release == expected_release
            and receipt.purpose == expected_purpose
            and invocation_context.purposes == (expected_purpose,)
            and expected_result_digest in invocation_context.evidence_refs
            and self._admitted(
                receipt,
                self._decision_evidence.get(expected_result_digest),
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
