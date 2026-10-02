"""Role assignments to identities created in the same apply declare their principal type.

Without ``principal_type`` Azure looks the principal up in Entra ID, and a managed identity
created moments earlier in the same apply may not have replicated yet, which fails a fresh
installation at random with ``PrincipalNotFound``. With ``principal_type = "ServicePrincipal"``
the assignment is accepted during replication.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_INFRA = Path(__file__).resolve().parents[3] / "infra"
_ASSIGNMENT = re.compile(r'resource "azurerm_role_assignment" "([a-z0-9_]+)" \{(.*?)\n\}', re.S)
_PRINCIPAL = re.compile(r"\n\s*principal_id\s*=\s*(.*?)(?=\n\s*[a-z_]+\s*=|\Z)", re.S)
_TYPE = re.compile(r'\n\s*principal_type\s*=\s*"([A-Za-z]+)"')
# Identities whose creation shares the apply with the assignment.
_SAME_APPLY = re.compile(
    r"module\.[a-z0-9_]*identity[a-z0-9_]*(\[[^\]]*\])?\.principal_id"
    r"|azurerm_user_assigned_identity\.[a-z0-9_]+(\[[^\]]*\])?\.principal_id"
    r"|kubelet_identity\[0\]\.object_id"
)
# Module inputs that every caller fills from a managed identity created in the same apply.
_MANAGED_IDENTITY_INPUTS = re.compile(r"^var\.(executor_principal_id|runtime_principal_id)$")


def _assignments() -> list[tuple[str, str, str, str | None]]:
    found = []
    for path in sorted(_INFRA.rglob("*.tf")):
        if ".terraform" in path.parts:
            continue
        for match in _ASSIGNMENT.finditer(path.read_text(encoding="utf-8")):
            body = match.group(2)
            principal = _PRINCIPAL.search(body)
            declared = _TYPE.search(body)
            found.append(
                (
                    f"{path.relative_to(_INFRA)}:{match.group(1)}",
                    " ".join(principal.group(1).split()) if principal else "",
                    body,
                    declared.group(1) if declared else None,
                )
            )
    return found


_ALL = _assignments()


def test_the_scan_sees_the_infrastructure_role_assignments() -> None:
    assert len(_ALL) >= 100
    assert any(name.startswith("main.tf:") for name, *_ in _ALL)


@pytest.mark.parametrize(
    ("name", "principal", "declared"),
    [
        (name, principal, declared)
        for name, principal, _body, declared in _ALL
        if _SAME_APPLY.search(principal) or _MANAGED_IDENTITY_INPUTS.fullmatch(principal)
    ],
    ids=lambda value: value if isinstance(value, str) and ":" in value else "",
)
def test_same_apply_identities_declare_service_principal(
    name: str, principal: str, declared: str | None
) -> None:
    assert declared == "ServicePrincipal", (
        f'{name} assigns a role to {principal} without principal_type = "ServicePrincipal"'
    )


def test_no_assignment_declares_an_unknown_principal_type() -> None:
    declared = {value for *_rest, value in _ALL if value is not None}
    assert declared <= {"ServicePrincipal", "User", "Group"}
