"""Tests for interrupted deploy-identity state reconciliation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.deployment.azure import reconcile_deploy_identity_state as reconcile

_PRINCIPAL = "00000000-0000-0000-0000-000000000001"
_SCOPE = (
    "/subscriptions/00000000-0000-0000-0000-000000000002/"
    "resourceGroups/example/providers/Microsoft.Storage/storageAccounts/example"
)
_ASSIGNMENT_ID = (
    f"{_SCOPE}/providers/Microsoft.Authorization/roleAssignments/"
    "00000000-0000-0000-0000-000000000003"
)
_BINDING = reconcile.RoleBinding(
    "azurerm_role_assignment.example",
    'try(azurerm_storage_account.example.id, "")',
    "Storage Blob Data Owner",
    "azurerm_storage_account.example",
)


def _completed(arguments: tuple[str, ...], stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(arguments, 0, stdout=stdout, stderr="")


def test_scope_accepts_terraform_warnings_before_the_exact_result() -> None:
    output = "\n".join(
        (
            "Warning: Deprecated attribute",
            "This warning can span multiple lines.",
            json.dumps(_SCOPE),
        )
    )

    assert reconcile._scope(output) == _SCOPE


@pytest.mark.parametrize("output", ["", f"{json.dumps(_SCOPE)}\ntrailing noise", "123"])
def test_scope_rejects_empty_non_string_or_trailing_output(output: str) -> None:
    with pytest.raises(ValueError, match="scope output"):
        reconcile._scope(output)


def test_reconcile_imports_one_exact_existing_assignment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, ...]] = []

    def command(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == tmp_path
        calls.append(arguments)
        if arguments == ("terraform", "state", "list"):
            return _completed(arguments, "")
        if arguments == ("terraform", "console"):
            assert input_text == f"{_BINDING.scope_expression}\n"
            return _completed(arguments, json.dumps(_SCOPE))
        if arguments[:4] == ("az", "role", "assignment", "list"):
            payload = [
                {
                    "id": _ASSIGNMENT_ID,
                    "principalId": _PRINCIPAL,
                    "roleDefinitionName": _BINDING.role_name,
                    "scope": _SCOPE,
                }
            ]
            return _completed(arguments, json.dumps(payload))
        return _completed(arguments, "")

    monkeypatch.setattr(reconcile, "_command", command)

    adopted = reconcile.reconcile(
        tmp_path,
        principal_id=_PRINCIPAL,
        bindings=(_BINDING,),
    )

    assert adopted == (_BINDING.address,)
    assert calls[-1] == (
        "terraform",
        "import",
        "-input=false",
        _BINDING.address,
        _ASSIGNMENT_ID,
    )


def test_reconcile_rejects_duplicate_assignments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def command(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, input_text
        if arguments == ("terraform", "state", "list"):
            return _completed(
                arguments,
                "module.other.azurerm_role_assignment.existing\n",
            )
        if arguments[:4] == ("terraform", "state", "show", "-no-color"):
            return _completed(arguments, f'id = "{_ASSIGNMENT_ID.upper()}"\n')
        if arguments == ("terraform", "console"):
            return _completed(arguments, json.dumps(_SCOPE))
        payload = [
            {
                "id": _ASSIGNMENT_ID,
                "principalId": _PRINCIPAL,
                "roleDefinitionName": _BINDING.role_name,
                "scope": _SCOPE,
            },
            {
                "id": _ASSIGNMENT_ID.replace("0003", "0004"),
                "principalId": _PRINCIPAL,
                "roleDefinitionName": _BINDING.role_name,
                "scope": _SCOPE,
            },
        ]
        return _completed(arguments, json.dumps(payload))

    monkeypatch.setattr(reconcile, "_command", command)

    with pytest.raises(ValueError, match="exactly one assignment"):
        reconcile.reconcile(
            tmp_path,
            principal_id=_PRINCIPAL,
            bindings=(_BINDING,),
        )


def test_reconcile_rejects_an_assignment_tracked_at_another_address(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def command(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, input_text
        if arguments == ("terraform", "state", "list"):
            return _completed(
                arguments,
                "module.other.azurerm_role_assignment.existing\n",
            )
        if arguments[:4] == ("terraform", "state", "show", "-no-color"):
            return _completed(arguments, f'id = "{_ASSIGNMENT_ID.upper()}"\n')
        if arguments == ("terraform", "console"):
            return _completed(arguments, json.dumps(_SCOPE))
        if arguments[:4] == ("az", "role", "assignment", "list"):
            payload = [
                {
                    "id": _ASSIGNMENT_ID,
                    "principalId": _PRINCIPAL,
                    "roleDefinitionName": _BINDING.role_name,
                    "scope": _SCOPE,
                }
            ]
            return _completed(arguments, json.dumps(payload))
        return _completed(arguments, "")

    monkeypatch.setattr(reconcile, "_command", command)

    with pytest.raises(ValueError, match="already tracked at another address"):
        reconcile.reconcile(
            tmp_path,
            principal_id=_PRINCIPAL,
            bindings=(_BINDING,),
        )


def test_reconcile_rejects_unavailable_scope_for_a_surviving_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def command(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, input_text
        if arguments == ("terraform", "state", "list"):
            return _completed(arguments, f"{_BINDING.owner_state_address}\n")
        return _completed(arguments, '""\n')

    monkeypatch.setattr(reconcile, "_command", command)

    with pytest.raises(ValueError, match="owner remains in state"):
        reconcile.reconcile(
            tmp_path,
            principal_id=_PRINCIPAL,
            bindings=(_BINDING,),
        )
