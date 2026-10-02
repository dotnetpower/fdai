"""The controller validator accepts exactly the plan reviews the managed host produces."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_review import validate_plan_review


def _review(stage: str, **extra: Any) -> dict[str, Any]:
    review: dict[str, Any] = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": stage,
        "plan_digest": "a" * 64,
        "target_binding": "b" * 64,
        "source_commit": "c" * 40,
        "runtime_profile_digest": "d" * 64,
        "runtime_platform": "aks",
        "summary": {"action_counts": {"update": 1, "no-op": 23}},
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "mutation_performed": False,
        "subscription_ready": False,
        **extra,
    }
    review["review_digest"] = canonical_digest(review)
    return review


def _service_update(service: str = "operator-service") -> dict[str, str]:
    return {
        "service": service,
        "image": f"registry.example.invalid/fdai/{service}@sha256:{'e' * 64}",
        "source_commit": "c" * 40,
        "update_digest": "f" * 64,
    }


@pytest.mark.parametrize(
    ("stage", "operation"),
    [
        ("access", "access"),
        ("substrate", "substrate"),
        ("runtime", "runtime"),
        ("runtime", "runtime-cluster"),
        ("database", "database"),
        ("application", "application"),
    ],
)
def test_host_operation_matching_the_stage_is_accepted(stage: str, operation: str) -> None:
    assert validate_plan_review(_review(stage, operation=operation)) == (stage, 0)


@pytest.mark.parametrize(
    ("stage", "operation"),
    [
        ("access", "substrate"),
        ("substrate", "runtime-cluster"),
        ("application", "runtime"),
        ("runtime", "runtime-residual"),
        ("runtime", 7),
        ("database", None),
    ],
)
def test_host_operation_for_another_stage_is_rejected(stage: str, operation: object) -> None:
    with pytest.raises(ValueError, match="invalid or expired"):
        validate_plan_review(_review(stage, operation=operation))


def test_service_update_operation_is_bound_to_its_service() -> None:
    operation = "service-update-operator-service-0123456789ab"

    assert validate_plan_review(
        _review("application", operation=operation, service_update=_service_update())
    ) == ("application", 0)
    for wrong in ("application", "service-update-core-control-plane-0123456789ab"):
        with pytest.raises(ValueError, match="invalid or expired"):
            validate_plan_review(
                _review("application", operation=wrong, service_update=_service_update())
            )


def test_review_without_operation_remains_accepted() -> None:
    assert validate_plan_review(_review("substrate")) == ("substrate", 0)
