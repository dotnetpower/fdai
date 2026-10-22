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
        ("application", "license-application-update"),
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


@pytest.mark.parametrize(
    ("operation", "digest"),
    [("select", "1" * 64), ("clear", "")],
)
def test_core_service_update_accepts_bound_development_authority(
    operation: str, digest: str
) -> None:
    service_update = _service_update("core-control-plane")
    service_update.update(
        development_authority_operation=operation,
        development_authority_profile_digest=digest,
    )

    assert validate_plan_review(
        _review(
            "application",
            operation="service-update-core-control-plane-0123456789ab",
            service_update=service_update,
        )
    ) == ("application", 0)


@pytest.mark.parametrize(
    ("service", "operation", "digest"),
    [
        ("operator-service", "select", "1" * 64),
        ("core-control-plane", "preserve", ""),
        ("core-control-plane", "select", ""),
        ("core-control-plane", "clear", "1" * 64),
    ],
)
def test_service_update_rejects_invalid_development_authority_binding(
    service: str, operation: str, digest: str
) -> None:
    service_update = _service_update(service)
    service_update.update(
        development_authority_operation=operation,
        development_authority_profile_digest=digest,
    )

    with pytest.raises(ValueError, match="invalid or expired"):
        validate_plan_review(
            _review(
                "application",
                operation=f"service-update-{service}-0123456789ab",
                service_update=service_update,
            )
        )


def test_service_update_rejects_partial_development_authority_binding() -> None:
    service_update = _service_update("core-control-plane")
    service_update["development_authority_operation"] = "select"

    with pytest.raises(ValueError, match="invalid or expired"):
        validate_plan_review(
            _review(
                "application",
                operation="service-update-core-control-plane-0123456789ab",
                service_update=service_update,
            )
        )


def test_review_without_operation_remains_accepted() -> None:
    assert validate_plan_review(_review("substrate")) == ("substrate", 0)
