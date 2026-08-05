"""Tests for Kubernetes diagnostic ontology function bindings."""

from __future__ import annotations

import pytest

from fdai.core.ontology_platform import FunctionInvocationContext
from fdai.delivery.kubernetes.ontology_functions import (
    build_diagnostic_function_registry,
    diagnostic_function_types,
)


def _context(*, agent: str = "Heimdall") -> FunctionInvocationContext:
    return FunctionInvocationContext(
        caller_agent=agent,
        purposes=("diagnostic-evaluation",),
        evidence_refs=("evidence:example",),
    )


def test_declares_every_reducer_as_read_only_and_credential_free() -> None:
    declarations = diagnostic_function_types()

    assert len(declarations) == 22
    assert len({item.name for item in declarations}) == len(declarations)
    assert all(item.kind.value == "derive" for item in declarations)
    assert all(item.allowed_agents == ["Heimdall"] for item in declarations)
    assert all(item.network_allowed is False for item in declarations)
    assert all(item.credentials_allowed is False for item in declarations)


async def test_invokes_dependency_reducer_with_exact_release_receipt() -> None:
    registry = build_diagnostic_function_registry()
    result, receipt = await registry.invoke_with_receipt(
        "diagnostic.kubernetes_missing_dependency_reducer",
        {"resources": [], "evidence_complete": True},
        context=_context(),
    )

    assert result == []
    assert receipt.function_ref.name == "diagnostic.kubernetes_missing_dependency_reducer"
    assert receipt.caller_agent == "Heimdall"
    assert receipt.evidence_refs == ("evidence:example",)


async def test_rejects_agent_outside_diagnostic_owner_boundary() -> None:
    registry = build_diagnostic_function_registry()

    with pytest.raises(PermissionError, match="agent is not allowed"):
        await registry.invoke_with_receipt(
            "diagnostic.kubernetes_missing_dependency_reducer",
            {"resources": [], "evidence_complete": True},
            context=_context(agent="Thor"),
        )


async def test_rejects_unbounded_or_unknown_reducer_arguments() -> None:
    registry = build_diagnostic_function_registry()

    with pytest.raises(ValueError, match="input_schema"):
        await registry.invoke_with_receipt(
            "diagnostic.kubernetes_missing_dependency_reducer",
            {"resources": [], "evidence_complete": True, "command": "kubectl delete pod"},
            context=_context(),
        )
