"""Strict catalog loading for execution-authorization assignments."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from fdai.rule_catalog.schema.execution_authorization import (
    AuthorizationAssignmentLoadError,
    AuthorizationEnforcement,
    AuthorizationPosture,
    AuthorizationScopeLevel,
    GrantMode,
    load_authorization_assignment_catalog,
    load_authorization_assignment_from_mapping,
)
from fdai.rule_catalog.schema.scope import ResourceContext


def _assignment() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "kind": "authorization-assignment",
        "id": "authz.object-write.prod",
        "version": "1.0.0",
        "capabilities": ["object.write"],
        "execution_profiles": ["change-executor"],
        "scope": {
            "include": ["scope://example/account/prod"],
            "selector": {"resource_types": ["object-storage"]},
        },
        "posture": "request_jit",
        "constraints": {
            "allowed_grant_modes": ["action_bound", "time_bound"],
            "max_scope": "resource",
            "max_duration_seconds": 1800,
            "quorum": 2,
            "approver_roles": ["owner"],
            "required_evidence": ["effective_access"],
            "require_effective_probe": True,
            "exemptible": False,
        },
        "enforcement": "enforce",
        "provenance": {
            "created_at": "2026-07-31T00:00:00Z",
            "created_by": "example-team",
        },
    }


def test_loads_scoped_authorization_assignment() -> None:
    assignment = load_authorization_assignment_from_mapping(_assignment())
    assert assignment.posture is AuthorizationPosture.REQUEST_JIT
    assert assignment.enforcement is AuthorizationEnforcement.ENFORCE
    assert assignment.constraints.allowed_grant_modes == frozenset(
        {GrantMode.ACTION_BOUND, GrantMode.TIME_BOUND}
    )
    assert assignment.constraints.max_scope is AuthorizationScopeLevel.RESOURCE
    assert assignment.constraints.quorum == 2
    assert assignment.provenance is not None
    assert assignment.applies_to(
        capability_id="object.write",
        execution_profile="change-executor",
        resource=ResourceContext(
            organization="example",
            account="account",
            resource_group="prod",
            resource_id="store-1",
            resource_type="object-storage",
        ),
    )


def test_assignment_defaults_to_shadow_enforcement() -> None:
    raw = _assignment()
    del raw["enforcement"]
    assignment = load_authorization_assignment_from_mapping(raw)
    assert assignment.enforcement is AuthorizationEnforcement.DO_NOT_ENFORCE


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("kind",), "assignment"),
        (("posture",), "allow"),
        (("constraints", "max_duration_seconds"), 0),
        (("constraints", "allowed_grant_modes"), []),
        (("scope", "include"), ["not-a-scope"]),
    ),
)
def test_invalid_assignment_is_rejected(path: tuple[str, ...], value: object) -> None:
    raw = deepcopy(_assignment())
    target: dict[str, Any] = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(AuthorizationAssignmentLoadError):
        load_authorization_assignment_from_mapping(raw)


def test_unknown_field_is_rejected() -> None:
    raw = _assignment()
    raw["customer_override"] = True
    with pytest.raises(AuthorizationAssignmentLoadError):
        load_authorization_assignment_from_mapping(raw)


def test_provenance_is_required() -> None:
    raw = _assignment()
    del raw["provenance"]
    with pytest.raises(AuthorizationAssignmentLoadError):
        load_authorization_assignment_from_mapping(raw)


def test_directory_loader_rejects_duplicates_and_unknown_references(
    tmp_path: Any,
) -> None:
    import yaml

    first = _assignment()
    second = deepcopy(first)
    second["capabilities"] = ["unknown.capability"]
    (tmp_path / "first.yaml").write_text(yaml.safe_dump(first), encoding="utf-8")
    (tmp_path / "second.yaml").write_text(yaml.safe_dump(second), encoding="utf-8")
    with pytest.raises(AuthorizationAssignmentLoadError) as caught:
        load_authorization_assignment_catalog(
            tmp_path,
            known_capability_ids=frozenset({"object.write"}),
            known_execution_profiles=frozenset({"change-executor"}),
        )
    messages = " ".join(item.message for item in caught.value.issues)
    assert "duplicate" in messages or "unknown capability" in messages


def test_directory_loader_accepts_known_references(tmp_path: Any) -> None:
    import yaml

    (tmp_path / "assignment.yaml").write_text(
        yaml.safe_dump(_assignment()),
        encoding="utf-8",
    )
    loaded = load_authorization_assignment_catalog(
        tmp_path,
        known_capability_ids=frozenset({"object.write"}),
        known_execution_profiles=frozenset({"change-executor"}),
    )
    assert [item.assignment_id for item in loaded] == ["authz.object-write.prod"]
