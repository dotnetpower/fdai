"""Validate the managed-host plan review before rendering or naming an approval file."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest

_FIELDS = frozenset(
    {
        "schema_version",
        "stage",
        "plan_digest",
        "review_digest",
        "target_binding",
        "source_commit",
        "summary",
        "expires_at",
        "mutation_performed",
        "subscription_ready",
    }
)
_ACTIONS = frozenset({"create", "update", "delete", "replace", "read", "no-op"})
_ERROR = "standalone plan review is invalid or expired; request a current exact plan"


def validate_plan_review(review: dict[str, Any]) -> tuple[str, int]:
    """Return a safe stage and destructive count without granting execution authority."""

    stage = review.get("stage")
    summary = review.get("summary")
    if (
        set(review) != _FIELDS
        or review.get("schema_version") != "fdai.standalone-application-plan.v1"
        or not isinstance(stage, str)
        or stage not in {"substrate", "application"}
        or review.get("mutation_performed") is not False
        or review.get("subscription_ready") is not False
        or not isinstance(summary, dict)
        or not set(summary).issubset({"action_counts", "resource_type_counts", "resource_changes"})
    ):
        raise ValueError(_ERROR)
    for key, length in (
        ("plan_digest", 64),
        ("review_digest", 64),
        ("target_binding", 64),
        ("source_commit", 40),
    ):
        value = review.get(key)
        if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
            raise ValueError(_ERROR)
    counts = summary.get("action_counts")
    if (
        not isinstance(counts, dict)
        or not counts
        or not set(counts).issubset(_ACTIONS)
        or any(type(count) is not int or not 0 <= count <= 5000 for count in counts.values())
    ):
        raise ValueError(_ERROR)
    types = summary.get("resource_type_counts", {})
    if (
        not isinstance(types, dict)
        or len(types) > 5000
        or any(
            not isinstance(name, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", name) is None
            or type(count) is not int
            or not 0 <= count <= 5000
            for name, count in types.items()
        )
    ):
        raise ValueError(_ERROR)
    changes = summary.get("resource_changes", [])
    if not isinstance(changes, list) or len(changes) > 5000:
        raise ValueError(_ERROR)
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"address", "actions"}:
            raise ValueError(_ERROR)
        address, actions = change["address"], change["actions"]
        if (
            not isinstance(address, str)
            or not 0 < len(address) <= 512
            or not address.isascii()
            or not address.isprintable()
            or not isinstance(actions, list)
            or not actions
            or any(not isinstance(action, str) or action not in _ACTIONS for action in actions)
        ):
            raise ValueError(_ERROR)
    expiry = review.get("expires_at")
    if not isinstance(expiry, str):
        raise ValueError(_ERROR)
    try:
        expires = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(_ERROR) from exc
    if expires.tzinfo is None or expires <= datetime.now(UTC):
        raise ValueError(_ERROR)
    document = {key: value for key, value in review.items() if key != "review_digest"}
    if review["review_digest"] != canonical_digest(document):
        raise ValueError(_ERROR)
    return stage, int(counts.get("delete", 0)) + int(counts.get("replace", 0))
