"""Capability-bounded ontology function registry."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from jsonschema import Draft202012Validator
from pydantic import Field, ValidationInfo, field_validator

from fdai.shared.contracts.models import (
    CEILING_ROLE_RANK,
    CeilingRole,
    ContractBase,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyRelease,
    OntologyReleaseRef,
    OntologyTypeRef,
)
from fdai.shared.ontology.release import build_ontology_release

from .kinetics import CriterionResult, MutationPlan, OntologyFunctionKind, OntologyFunctionType

OntologyFunction = Callable[[Mapping[str, Any]], Awaitable[object]]


class FunctionInvocationContext(ContractBase):
    caller_agent: str = Field(min_length=1, max_length=64)
    caller_role: CeilingRole = CeilingRole.READER
    purposes: tuple[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")], ...] = ()
    evidence_refs: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...] = ()

    @field_validator("purposes", "evidence_refs", mode="after")
    @classmethod
    def _deduplicate_bounded_context(
        cls,
        values: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        unique = tuple(dict.fromkeys(values))
        limit = 16 if info.field_name == "purposes" else 64
        if len(unique) > limit:
            raise ValueError(
                f"ontology function invocation {info.field_name} exceeds {limit} items"
            )
        return unique


class FunctionInvocationReceipt(ContractBase):
    request_id: str = Field(pattern=r"^logic-request:[a-f0-9]{64}$")
    invocation_id: str = Field(pattern=r"^logic-invocation:[a-f0-9]{64}$")
    function_ref: OntologyTypeRef
    caller_agent: str
    caller_role: CeilingRole
    purposes: tuple[str, ...] = ()
    input_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    output_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    seed: int | None = None
    started_at: datetime
    completed_at: datetime
    evidence_refs: tuple[str, ...] = ()


class OntologyFunctionRegistry:
    """Run local read/proposal functions under exact release and wall/output bounds.

    CPU and memory declarations remain metadata for an isolated runner. This
    in-process registry rejects network or credential access instead of claiming
    to enforce isolation that it does not provide.
    """

    def __init__(self, *, release: OntologyRelease | None = None) -> None:
        self._functions: dict[str, tuple[OntologyFunctionType, OntologyFunction]] = {}
        self._release = release

    def register(self, declaration: OntologyFunctionType, function: OntologyFunction) -> None:
        if declaration.name in self._functions:
            raise ValueError(f"duplicate ontology function {declaration.name!r}")
        if declaration.network_allowed or declaration.credentials_allowed:
            raise ValueError("network or credential ontology functions require an isolated runner")
        retained = declaration.model_copy(deep=True)
        if self._release is not None:
            active = next(
                (
                    reference
                    for reference in self._release.declarations
                    if reference.kind is OntologyDeclarationKind.FUNCTION
                    and reference.name == retained.name
                ),
                None,
            )
            registered = build_ontology_release(function_types=(retained,)).declarations[0]
            if active != registered:
                raise ValueError("ontology function declaration does not match release")
        self._functions[retained.name] = (retained, function)

    @property
    def release_ref(self) -> OntologyReleaseRef | None:
        """Return only the registry's exact immutable release identity."""

        return self._release.ref() if self._release is not None else None

    def declaration(self, name: str) -> OntologyFunctionType:
        """Return the exact declaration used for authorization and schema validation."""

        try:
            declaration, _function = self._functions[name]
        except KeyError as exc:
            raise KeyError(f"unknown ontology function {name!r}") from exc
        return declaration.model_copy(deep=True)

    async def invoke(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        context: FunctionInvocationContext | None = None,
    ) -> object:
        result, _receipt = await self._invoke(name, arguments, context=context, with_receipt=False)
        return result

    async def invoke_with_receipt(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        context: FunctionInvocationContext,
    ) -> tuple[object, FunctionInvocationReceipt]:
        if self._release is None:
            raise ValueError("ontology function receipts require an exact release")
        result, receipt = await self._invoke(name, arguments, context=context, with_receipt=True)
        if receipt is None:  # pragma: no cover - with_receipt invariant
            raise RuntimeError("ontology function receipt was not produced")
        return result, receipt

    async def _invoke(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        context: FunctionInvocationContext | None,
        with_receipt: bool,
    ) -> tuple[object, FunctionInvocationReceipt | None]:
        try:
            declaration, function = self._functions[name]
        except KeyError as exc:
            raise KeyError(f"unknown ontology function {name!r}") from exc
        invocation_context = context or FunctionInvocationContext(caller_agent="unattributed")
        _authorize(declaration, invocation_context)
        raw_arguments = dict(arguments)
        seed = None
        if declaration.execution_class is LogicExecutionClass.SEEDED_STOCHASTIC:
            seed_field = declaration.seed_field or "fdai_seed"
            if seed_field in raw_arguments:
                raise ValueError(f"ontology function seed field {seed_field!r} is runtime-owned")
            raw_digest = ontology_function_digest(raw_arguments)
            seed = int(
                hashlib.sha256(f"{declaration.artifact_digest}:{raw_digest}".encode()).hexdigest()[
                    :16
                ],
                16,
            )
            raw_arguments[seed_field] = seed
        input_errors = list(
            Draft202012Validator(declaration.input_schema).iter_errors(raw_arguments)
        )
        if input_errors:
            raise ValueError("ontology function arguments violate input_schema")
        input_digest = ontology_function_digest(raw_arguments)
        started_at = datetime.now(tz=UTC)
        try:
            async with asyncio.timeout(declaration.timeout_seconds):
                result = await function(raw_arguments)
        except TimeoutError as exc:
            raise TimeoutError("ontology function exceeded its wall timeout") from exc
        if declaration.kind is OntologyFunctionKind.VALIDATE and not isinstance(
            result, CriterionResult
        ):
            raise TypeError("validate ontology function MUST return CriterionResult")
        if declaration.kind is OntologyFunctionKind.PLAN and not isinstance(result, MutationPlan):
            raise TypeError("plan ontology function MUST return MutationPlan")
        read_only_kind = declaration.kind in {
            OntologyFunctionKind.QUERY,
            OntologyFunctionKind.DERIVE,
        }
        if read_only_kind and isinstance(result, MutationPlan):
            raise TypeError("read-only ontology function MUST NOT return MutationPlan")
        serialized = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        output_bytes = _canonical_json_bytes(serialized)
        if len(output_bytes) > declaration.max_output_bytes:
            raise ValueError("ontology function result exceeds max_output_bytes")
        output_errors = list(
            Draft202012Validator(declaration.output_schema).iter_errors(serialized)
        )
        if output_errors:
            raise TypeError("ontology function result violates output_schema")
        if not with_receipt:
            return result, None
        release = self._release
        if release is None:  # pragma: no cover - checked by public method
            raise RuntimeError("ontology release is unavailable")
        function_ref = release.type_ref(OntologyDeclarationKind.FUNCTION, declaration.name)
        output_digest = _digest_bytes(output_bytes)
        request_identity = ontology_function_digest(
            {
                "function_ref": function_ref.model_dump(mode="json"),
                "input_digest": input_digest,
                "caller_agent": invocation_context.caller_agent,
                "caller_role": invocation_context.caller_role.value,
                "purposes": list(invocation_context.purposes),
                "evidence_refs": list(invocation_context.evidence_refs),
            }
        ).removeprefix("sha256:")
        identity = ontology_function_digest(
            {
                "request_id": f"logic-request:{request_identity}",
                "output_digest": output_digest,
            }
        ).removeprefix("sha256:")
        return result, FunctionInvocationReceipt(
            request_id=f"logic-request:{request_identity}",
            invocation_id=f"logic-invocation:{identity}",
            function_ref=function_ref,
            caller_agent=invocation_context.caller_agent,
            caller_role=invocation_context.caller_role,
            purposes=invocation_context.purposes,
            input_digest=input_digest,
            output_digest=output_digest,
            seed=seed,
            started_at=started_at,
            completed_at=datetime.now(tz=UTC),
            evidence_refs=invocation_context.evidence_refs,
        )


def _authorize(declaration: OntologyFunctionType, context: FunctionInvocationContext) -> None:
    if CEILING_ROLE_RANK[context.caller_role] < CEILING_ROLE_RANK[declaration.required_role]:
        raise PermissionError("ontology function caller role is below required_role")
    if declaration.allowed_agents and context.caller_agent not in declaration.allowed_agents:
        raise PermissionError("ontology function caller agent is not allowed")
    if declaration.purpose_bindings and not set(context.purposes).intersection(
        declaration.purpose_bindings
    ):
        raise PermissionError("ontology function caller purpose is not allowed")


def ontology_function_digest(value: object) -> str:
    """Return the canonical digest used by ontology function receipts."""

    return _digest_bytes(_canonical_json_bytes(value))


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("ontology function values MUST be canonical JSON") from exc


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


__all__ = [
    "FunctionInvocationContext",
    "FunctionInvocationReceipt",
    "OntologyFunction",
    "OntologyFunctionRegistry",
]
