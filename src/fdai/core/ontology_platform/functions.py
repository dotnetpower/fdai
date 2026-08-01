"""Capability-bounded ontology function registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .kinetics import CriterionResult, MutationPlan, OntologyFunctionKind, OntologyFunctionType

OntologyFunction = Callable[[Mapping[str, Any]], Awaitable[object]]


class OntologyFunctionRegistry:
    def __init__(self) -> None:
        self._functions: dict[str, tuple[OntologyFunctionType, OntologyFunction]] = {}

    def register(self, declaration: OntologyFunctionType, function: OntologyFunction) -> None:
        if declaration.name in self._functions:
            raise ValueError(f"duplicate ontology function {declaration.name!r}")
        self._functions[declaration.name] = (declaration, function)

    async def invoke(self, name: str, arguments: Mapping[str, Any]) -> object:
        try:
            declaration, function = self._functions[name]
        except KeyError as exc:
            raise KeyError(f"unknown ontology function {name!r}") from exc
        result = await function(dict(arguments))
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
        return result


__all__ = ["OntologyFunction", "OntologyFunctionRegistry"]
