"""Assignment intent to stewardship v2 rendering tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.core.human_assignment import (
    AssignmentIntent,
    AssignmentOwnershipError,
    DutyBinding,
    ProviderSubject,
    render_assignment_ownership_yaml,
)
from fdai.core.rbac.roles import Role
from fdai.core.stewardship import Duty, load_stewardship_from_mapping, load_stewardship_from_yaml
from fdai.core.stewardship.names import AGENT_NAMES

_CONFIG = Path(__file__).resolve().parents[3] / "config" / "agent-stewardship.yaml"


def _intent(*, all_agents: bool = True, scope_ref: str = "scope:platform") -> AssignmentIntent:
    names = tuple(name for name in AGENT_NAMES if name != "Loki") if all_agents else ("Thor",)
    return AssignmentIntent(
        idempotency_key="assignment-ownership-1",
        subject=ProviderSubject(
            provider="entra",
            subject_id="00000000-0000-0000-0000-000000009999",
        ),
        requested_role=Role.READER,
        duty_bindings=tuple(
            DutyBinding(agent_name=name, duty=Duty.BACKUP, scope_ref=scope_ref) for name in names
        ),
        goal_refs=(),
        requester_ref="owner-1",
        justification="Assign complete backup coverage for platform ownership.",
    )


def test_complete_assignment_renders_valid_v2_candidate() -> None:
    base = load_stewardship_from_yaml(_CONFIG, environ={})
    raw = yaml.safe_load(render_assignment_ownership_yaml(base, _intent()))

    candidate = load_stewardship_from_mapping(raw, environ={})

    assert candidate.version == 2
    assert candidate.agent("Thor").backup[0].id.endswith("9999")


def test_partial_assignment_does_not_invent_other_backups() -> None:
    base = load_stewardship_from_yaml(_CONFIG, environ={})

    with pytest.raises(AssignmentOwnershipError, match="complete stewardship v2 coverage"):
        render_assignment_ownership_yaml(base, _intent(all_agents=False))


def test_non_platform_scope_is_rejected() -> None:
    base = load_stewardship_from_yaml(_CONFIG, environ={})

    with pytest.raises(AssignmentOwnershipError, match="supports only scope:platform"):
        render_assignment_ownership_yaml(base, _intent(scope_ref="scope:team-a"))
