"""Invoke diagnostic reducers through the exact ontology function release."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fdai.core.ontology_platform import FunctionInvocationContext, OntologyFunctionRegistry
from fdai.delivery.kubernetes.ontology_functions import build_diagnostic_function_registry
from fdai.shared.providers.ontology_instance import canonical_json_mapping


@dataclass(frozen=True, slots=True)
class DiagnosticFunctionExecution:
    """Validated reducer output and its immutable invocation receipt."""

    findings: tuple[Mapping[str, Any], ...]
    receipt: Mapping[str, Any]
    function_name: str
    arguments: Mapping[str, Any]

    @property
    def input_binding(self) -> Mapping[str, Any]:
        return {"function_name": self.function_name, "arguments": self.arguments}


@dataclass(frozen=True, slots=True)
class DiagnosticFunctionExecutor:
    """Execute read-only diagnostic functions as Heimdall under one exact release."""

    registry: OntologyFunctionRegistry = field(default_factory=build_diagnostic_function_registry)

    async def derive(
        self,
        mechanism_id: str,
        arguments: Mapping[str, Any],
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> DiagnosticFunctionExecution:
        function_name = f"diagnostic.{mechanism_id}"
        normalized_arguments, _ = canonical_json_mapping(
            arguments,
            path=f"{function_name}.arguments",
        )
        result, receipt = await self.registry.invoke_with_receipt(
            function_name,
            normalized_arguments,
            context=FunctionInvocationContext(
                caller_agent="Heimdall",
                purposes=("diagnostic-evaluation",),
                evidence_refs=evidence_refs,
            ),
        )
        if not isinstance(result, list) or any(not isinstance(item, Mapping) for item in result):
            raise TypeError("diagnostic ontology function MUST return finding mappings")
        return DiagnosticFunctionExecution(
            findings=tuple(result),
            receipt=receipt.model_dump(mode="json"),
            function_name=function_name,
            arguments=normalized_arguments,
        )


__all__ = ["DiagnosticFunctionExecution", "DiagnosticFunctionExecutor"]
