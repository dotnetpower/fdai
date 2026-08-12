"""Bounded issuance authority for secured ObjectSet query receipts."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from fdai.shared.contracts.models import OntologyReleaseRef

from .functions import FunctionInvocationContext
from .query_gateway import SecuredObjectSetQueryReceipt, SecuredObjectSetQueryResult


@dataclass(frozen=True, slots=True)
class _IssuedReceipt:
    ontology_release: OntologyReleaseRef
    purpose: str
    result_digest: str


class SecuredQueryReceiptAuthority:
    """Issue and authenticate bounded query receipts without granting authority."""

    def __init__(self, *, max_receipts: int = 4096) -> None:
        if not 1 <= max_receipts <= 65_536:
            raise ValueError("secured query receipt bound MUST be between 1 and 65536")
        self._max_receipts = max_receipts
        self._verification_context = object()
        self._issued: OrderedDict[str, _IssuedReceipt] = OrderedDict()
        self._results: dict[str, SecuredObjectSetQueryResult] = {}

    @property
    def verification_context(self) -> object:
        """Return the opaque context bound into contextual ontology functions."""

        return self._verification_context

    def issue(self, result: SecuredObjectSetQueryResult) -> None:
        """Retain one content-addressed receipt produced by the secured gateway."""

        receipt = result.receipt
        key = receipt.projected_result_digest
        issued = _IssuedReceipt(
            ontology_release=receipt.ontology_release,
            purpose=receipt.purpose,
            result_digest=key,
        )
        existing = self._issued.get(key)
        if existing is not None and existing != issued:
            raise ValueError("secured query receipt digest conflicts with issued content")
        self._issued[key] = issued
        self._results[key] = SecuredObjectSetQueryResult.model_validate(
            result.model_dump(mode="json")
        )
        self._issued.move_to_end(key)
        while len(self._issued) > self._max_receipts:
            evicted, _ = self._issued.popitem(last=False)
            self._results.pop(evicted, None)

    def resolve(self, evidence_refs: tuple[str, ...]) -> SecuredObjectSetQueryResult:
        """Return one issued secured result named by a dependency evidence ref."""

        digests = tuple(
            ref.removeprefix("ontology-object-set:")
            for ref in evidence_refs
            if ref.startswith("ontology-object-set:")
        )
        if len(digests) != 1 or digests[0] not in self._results:
            raise PermissionError("function dependency does not identify one issued ObjectSet")
        return SecuredObjectSetQueryResult.model_validate(
            self._results[digests[0]].model_dump(mode="json")
        )

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
        if issued is None:
            return False
        return (
            receipt.projected_result_digest == expected_result_digest
            and receipt.ontology_release == expected_release == issued.ontology_release
            and receipt.purpose == expected_purpose == issued.purpose
            and invocation_context.purposes == (expected_purpose,)
            and invocation_context.evidence_refs == (expected_result_digest,)
        )


__all__ = ["SecuredQueryReceiptAuthority"]
