"""Execution authorization is bound only through validated composition."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from fdai.composition import Container, bind_execution_authorization
from fdai.core.execution_authorization import HierarchicalAuthorizationScopeResolver
from fdai.shared.providers.execution_authorization import (
    EffectiveAuthorizationProbe,
    ExecutionAccessGrantPlanner,
    ExecutionAccessGrantSink,
    ExecutionAuthorizationContextProvider,
    ExecutionIdentityResolver,
    ProviderPermissionMapper,
)


def _write_requirement(root: Path) -> None:
    root.mkdir()
    (root / "object.write.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "kind": "authorization-requirement",
                "id": "object.write.target",
                "version": "1.0.0",
                "capability_id": "object.write",
                "action_type_ids": ["object.update"],
                "resource_types": ["object-storage"],
                "scope_expressions": ["target"],
                "execution_profile": "change-executor",
                "provenance": {
                    "created_at": "2026-07-31T00:00:00Z",
                    "created_by": "example-team",
                },
            }
        ),
        encoding="utf-8",
    )


def _write_assignment(root: Path) -> None:
    root.mkdir()
    (root / "object.write.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "kind": "authorization-assignment",
                "id": "authz.object-write",
                "version": "1.0.0",
                "capabilities": ["object.write"],
                "execution_profiles": ["change-executor"],
                "scope": {"include": ["scope://example/account"]},
                "posture": "request_jit",
                "constraints": {
                    "allowed_grant_modes": ["action_bound"],
                    "max_scope": "resource",
                    "max_duration_seconds": 900,
                    "quorum": 2,
                    "approver_roles": ["owner"],
                },
                "enforcement": "enforce",
                "provenance": {
                    "created_at": "2026-07-31T00:00:00Z",
                    "created_by": "example-team",
                },
            }
        ),
        encoding="utf-8",
    )


def _bind(
    container: Container,
    *,
    requirements_root: Path,
    assignments_root: Path,
    grant_planner: ExecutionAccessGrantPlanner | None = None,
    grant_sink: ExecutionAccessGrantSink | None = None,
) -> Container:
    provider = cast(Any, object())
    return bind_execution_authorization(
        container,
        requirements_root=requirements_root,
        assignments_root=assignments_root,
        known_action_type_ids=frozenset({"object.update"}),
        known_resource_types=frozenset({"object-storage"}),
        known_capability_ids=frozenset({"object.write"}),
        known_execution_profiles=frozenset({"change-executor"}),
        context_provider=cast(ExecutionAuthorizationContextProvider, provider),
        scope_resolver=HierarchicalAuthorizationScopeResolver(),
        identity_resolver=cast(ExecutionIdentityResolver, provider),
        permission_mapper=cast(ProviderPermissionMapper, provider),
        effective_probe=cast(EffectiveAuthorizationProbe, provider),
        grant_planner=grant_planner,
        grant_sink=grant_sink,
    )


def test_valid_catalogs_bind_required_evaluator(
    container: Container,
    tmp_path: Path,
) -> None:
    requirements_root = tmp_path / "requirements"
    assignments_root = tmp_path / "assignments"
    _write_requirement(requirements_root)
    _write_assignment(assignments_root)

    bound = _bind(
        container,
        requirements_root=requirements_root,
        assignments_root=assignments_root,
    )

    assert container.execution_authorization_evaluator is None
    assert bound.execution_authorization_required
    assert bound.execution_authorization_evaluator is not None


def test_empty_requirement_catalog_fails_fast(
    container: Container,
    tmp_path: Path,
) -> None:
    requirements_root = tmp_path / "requirements"
    assignments_root = tmp_path / "assignments"
    requirements_root.mkdir()
    assignments_root.mkdir()

    with pytest.raises(ValueError, match="at least one requirement"):
        _bind(
            container,
            requirements_root=requirements_root,
            assignments_root=assignments_root,
        )


def test_grant_planner_and_sink_must_be_bound_together(
    container: Container,
    tmp_path: Path,
) -> None:
    provider = cast(ExecutionAccessGrantPlanner, object())
    with pytest.raises(ValueError, match="MUST be bound together"):
        _bind(
            container,
            requirements_root=tmp_path / "requirements",
            assignments_root=tmp_path / "assignments",
            grant_planner=provider,
        )
