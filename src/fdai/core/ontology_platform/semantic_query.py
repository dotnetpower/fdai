"""Verified semantic-plan execution for bounded read-only ontology queries."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from fdai.shared.contracts.models import ContractBase, OntologyDeclarationKind, OntologyRelease
from fdai.shared.ontology.release import build_ontology_release

from .functions import (
    FunctionInvocationContext,
    FunctionInvocationReceipt,
    OntologyFunctionRegistry,
    ontology_function_digest,
)
from .models import ObjectSetMaterialization, ObjectSetTruncationReason
from .query_profiles import QueryProfile
from .semantic_plans import SemanticOperationClass, VerifiedSemanticPlan

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"


class SemanticQueryReceipt(ContractBase):
    """Canonical query-plan and function-invocation lineage with no authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    function_invocation: FunctionInvocationReceipt
    truncated: bool | None = None
    truncation_reason: ObjectSetTruncationReason | None = None
    execution_authority: Literal[False] = False
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _receipt_is_canonical(self) -> SemanticQueryReceipt:
        if self.truncated is None and self.truncation_reason is not None:
            raise ValueError("non-ObjectSet query receipt MUST NOT carry truncation_reason")
        if self.truncated is False and self.truncation_reason is not None:
            raise ValueError("complete ObjectSet query receipt MUST NOT carry truncation_reason")
        if self.truncated is True and self.truncation_reason is None:
            raise ValueError("truncated ObjectSet query receipt requires truncation_reason")
        if self.receipt_digest != _receipt_digest(
            plan_digest=self.plan_digest,
            function_invocation=self.function_invocation,
            truncated=self.truncated,
            truncation_reason=self.truncation_reason,
        ):
            raise ValueError("semantic query receipt digest does not match its content")
        return self


class SemanticQueryService:
    """Reverify a query plan and invoke the existing exact-release function registry."""

    def __init__(
        self,
        *,
        release: OntologyRelease,
        registry: OntologyFunctionRegistry,
    ) -> None:
        self._release = release
        self._registry = registry

    async def execute(
        self,
        *,
        profile: QueryProfile,
        plan: VerifiedSemanticPlan,
        context: FunctionInvocationContext,
    ) -> tuple[object, SemanticQueryReceipt]:
        """Execute one exact QUERY plan without creating execution authority."""

        if plan.operation_class is not SemanticOperationClass.QUERY:
            raise ValueError("semantic query service requires a QUERY plan")
        if plan.ontology_release_digest != self._release.digest:
            raise ValueError("semantic query plan targets a stale ontology release")
        active_declaration = next(
            (
                declaration
                for declaration in self._release.declarations
                if declaration.kind is OntologyDeclarationKind.FUNCTION
                and declaration.name == profile.function_ref.name
            ),
            None,
        )
        if active_declaration is None:
            raise ValueError("query profile targets a stale ontology function")
        active_ref = self._release.type_ref(
            OntologyDeclarationKind.FUNCTION, active_declaration.name
        )
        if profile.function_ref != active_ref:
            raise ValueError("query profile targets a stale ontology function")
        profile_declaration = build_ontology_release(
            function_types=(profile.function_type,)
        ).declarations[0]
        if profile_declaration.declaration_digest != active_declaration.declaration_digest:
            raise ValueError("query profile selects a stale ontology function declaration")
        if self._registry.declaration(profile.function_type.name) != profile.function_type:
            raise ValueError("ontology function registry declaration does not match query profile")
        if plan.target_ref != active_ref:
            raise ValueError("semantic query plan targets a stale ontology function")
        if profile.purpose not in context.purposes:
            raise PermissionError("semantic query purpose does not match query profile")
        arguments = {"object_set": profile.object_set_template.model_dump(mode="json")}
        if plan.arguments != arguments:
            raise ValueError("semantic query plan arguments do not match query profile")

        result, invocation = await self._registry.invoke_with_receipt(
            profile.function_type.name,
            arguments,
            context=context,
        )
        truncated: bool | None = None
        truncation_reason: ObjectSetTruncationReason | None = None
        if isinstance(result, ObjectSetMaterialization):
            truncated = result.truncated
            truncation_reason = result.truncation_reason
        receipt_digest = _receipt_digest(
            plan_digest=plan.plan_digest,
            function_invocation=invocation,
            truncated=truncated,
            truncation_reason=truncation_reason,
        )
        return result, SemanticQueryReceipt(
            plan_digest=plan.plan_digest,
            function_invocation=invocation,
            truncated=truncated,
            truncation_reason=truncation_reason,
            receipt_digest=receipt_digest,
        )


def _receipt_digest(
    *,
    plan_digest: str,
    function_invocation: FunctionInvocationReceipt,
    truncated: bool | None,
    truncation_reason: ObjectSetTruncationReason | None,
) -> str:
    return ontology_function_digest(
        {
            "plan_digest": plan_digest,
            "function_invocation": function_invocation.model_dump(mode="json"),
            "truncated": truncated,
            "truncation_reason": (
                truncation_reason.value if truncation_reason is not None else None
            ),
            "execution_authority": False,
        }
    )


__all__ = ["SemanticQueryReceipt", "SemanticQueryService"]
