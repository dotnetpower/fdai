"""Render approved platform assignment intent as a validated stewardship v2 candidate."""

from __future__ import annotations

from typing import Any

import yaml

from fdai.core.human_assignment.model import AssignmentIntent
from fdai.core.stewardship import StewardKind, StewardshipMap, load_stewardship_from_mapping

_PLATFORM_SCOPE = "scope:platform"


class AssignmentOwnershipError(ValueError):
    """Raised when an assignment cannot safely produce a complete ownership map."""


def render_assignment_ownership_yaml(base: StewardshipMap, intent: AssignmentIntent) -> str:
    """Return a resolver-valid v2 ownership candidate for one approved intent."""

    unsupported = sorted(
        {
            binding.scope_ref
            for binding in intent.duty_bindings
            if binding.scope_ref != _PLATFORM_SCOPE
        }
    )
    if unsupported:
        raise AssignmentOwnershipError(
            "stewardship ownership supports only scope:platform; unsupported scopes: "
            + ", ".join(unsupported)
        )

    raw = _base_mapping(base)
    agents = raw["stewardship"]["agents"]
    for binding in intent.duty_bindings:
        agent = agents[binding.agent_name]
        stewards = agent["stewards"]
        stewards[:] = [
            item
            for item in stewards
            if not (
                item["kind"] == StewardKind.USER.value
                and item["id"].casefold() == intent.subject.subject_id.casefold()
            )
        ]
        stewards.append(
            {
                "kind": StewardKind.USER.value,
                "id": intent.subject.subject_id,
                "responsibility": "accountable",
                "duty": binding.duty.value,
            }
        )

    try:
        load_stewardship_from_mapping(raw, environ={})
    except ValueError as exc:
        raise AssignmentOwnershipError(
            "assignment does not produce complete stewardship v2 coverage"
        ) from exc
    return yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)


def _base_mapping(base: StewardshipMap) -> dict[str, Any]:
    agents: dict[str, Any] = {}
    for name, agent in base.agents.items():
        entry: dict[str, Any] = {
            "stewards": [
                {
                    "kind": subject.kind.value,
                    "id": subject.id,
                    "responsibility": subject.responsibility.value,
                    **({"duty": subject.duty.value} if subject.duty is not None else {}),
                }
                for subject in agent.stewards
            ]
        }
        if agent.accept_autonomous_reason is not None:
            entry["accept_autonomous"] = {"reason": agent.accept_autonomous_reason}
        agents[name] = entry
    return {
        "stewardship": {
            "version": 2,
            "maintainers": [{"oid": item.oid} for item in base.maintainers],
            "channels": dict(base.channels),
            "escalation": {"hop_timeout_seconds": base.hop_timeout_seconds},
            "thresholds": {"over_assigned_max": base.over_assigned_max},
            "agents": agents,
        }
    }


__all__ = ["AssignmentOwnershipError", "render_assignment_ownership_yaml"]
