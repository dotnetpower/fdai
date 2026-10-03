from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fdai_deployment_cli import standalone_aks_inventory
from fdai_deployment_cli.aks_job_execution import AksOneShotJob
from fdai_deployment_cli.contracts import canonical_digest

_REVISION = "a" * 40
_TARGET = "b" * 64
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
_IMAGE = "example.azurecr.io/fdai@sha256:" + "c" * 64


def _context(infra: Path) -> dict[str, object]:
    return {
        "infra": str(infra),
        "source_commit": _REVISION,
        "target_binding": _TARGET,
        "subscription_id": _SUBSCRIPTION,
        "client_id": "00000000-0000-0000-0000-000000000001",
        "inventory_progress_container_url": (
            "https://storage.blob.core.windows.net/provisioning-events"
        ),
        "image_refs": {"core-control-plane": _IMAGE},
        "initial_inventory_binding": standalone_aks_inventory.initial_inventory_binding(
            _SUBSCRIPTION
        ),
    }


def _closure(
    *,
    run_id: str,
    attempt_id: str,
    scope_digest: str,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "generation_digest": "sha256:" + "d" * 64,
        "scope_digest": scope_digest,
        "subscription_root": True,
        "resource_type_filter": False,
        "final_fence": True,
        "provider_coverage_complete": True,
        "truncated": False,
        "active_generation_matches": True,
        "overlay_open": False,
        "child_sources_complete": True,
        "fresh_generation": True,
        "observer_distinct": True,
        "resource_count": 7,
        "link_count": 5,
        "unmapped_object_count": 2,
        "coverage_gap_count": 1,
        "observed_at": (observed_at or datetime.now(tz=UTC)).isoformat(),
        "execution_authority": False,
    }
    value["receipt_digest"] = standalone_aks_inventory._closure_receipt_digest(value)
    return value


def test_initial_inventory_overrides_mutable_template_and_retains_closure_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    infra = bundle / "infra"
    infra.mkdir(parents=True)
    context = _context(infra)
    execution_calls: list[dict[str, object]] = []
    closure_environment: dict[str, str] = {}

    def execute(*_args: object, **kwargs: object) -> AksOneShotJob:
        execution_calls.append(kwargs)
        return AksOneShotJob(
            name="fdai-inventory-0123456789abcdef",
            execution_digest="e" * 64,
            manifest={},
        )

    def capture_env(_command: tuple[str, ...], **kwargs: object) -> str:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        closure_environment.update(environment)
        receipt = _closure(
            run_id=environment["FDAI_INVENTORY_PROGRESS_RUN_ID"],
            attempt_id=environment["FDAI_INVENTORY_PROGRESS_ATTEMPT_ID"],
            scope_digest=environment["FDAI_INVENTORY_EXPECTED_SCOPE_DIGEST"],
        )
        return json.dumps(receipt)

    monkeypatch.setattr(standalone_aks_inventory, "execute_aks_cronjob_once", execute)
    monkeypatch.setattr(standalone_aks_inventory, "_terraform_output", lambda *_: "unused")
    monkeypatch.setattr(standalone_aks_inventory, "vault_name", lambda *_: "vault")
    monkeypatch.setattr(standalone_aks_inventory, "_capture", lambda *_args, **_kwargs: "dsn")
    monkeypatch.setattr(standalone_aks_inventory, "_capture_env", capture_env)

    receipt_path = tmp_path / "inventory-receipt.json"
    result = standalone_aks_inventory.run_initial_aks_inventory(
        context,
        tmp_path,
        receipt_path=receipt_path,
    )

    request = execution_calls[0]
    overrides = request["environment"]
    assert isinstance(overrides, dict)
    assert overrides["FDAI_INVENTORY_SCOPES"] == _SUBSCRIPTION
    assert overrides["FDAI_INVENTORY_SOURCES"] == "arg,arm"
    assert overrides["FDAI_INVENTORY_RESOURCE_TYPES"] == ""
    # The in-cluster Job cannot reach the operations-private progress container.
    assert "FDAI_INVENTORY_PROGRESS_CONTAINER_URL" not in overrides
    assert closure_environment["FDAI_INVENTORY_PROGRESS_CONTAINER_URL"].startswith("https://")
    assert closure_environment["FDAI_INVENTORY_SCOPES"] == _SUBSCRIPTION
    assert closure_environment["FDAI_INVENTORY_SOURCES"] == "arg,arm"
    assert closure_environment["FDAI_INVENTORY_RESOURCE_TYPES"] == ""
    assert result["scope_digest"] == context["initial_inventory_binding"]["scope_digest"]  # type: ignore[index]
    assert result["fresh_generation"] is True
    assert result["freshness_observed_at"]
    assert result["resource_count"] == 7
    assert result["link_count"] == 5
    assert result["unmapped_object_count"] == 2
    assert result["coverage_gap_count"] == 1
    assert result["closure_receipt_verified"] is True
    standalone_aks_inventory.require_initial_inventory_receipt(result, runtime_platform="aks")


@pytest.mark.parametrize("tamper", ["scope", "stale", "digest"])
def test_closure_rejects_unbound_or_stale_evidence(tamper: str) -> None:
    binding = standalone_aks_inventory.initial_inventory_binding(_SUBSCRIPTION)
    observed_after = datetime.now(tz=UTC)
    value = _closure(
        run_id=f"genesis.{_REVISION}",
        attempt_id="attempt.example",
        scope_digest=str(binding["scope_digest"]),
        observed_at=(
            observed_after - timedelta(minutes=5) if tamper == "stale" else observed_after
        ),
    )
    if tamper == "scope":
        value["scope_digest"] = "sha256:" + "f" * 64
        value["receipt_digest"] = standalone_aks_inventory._closure_receipt_digest(
            {key: item for key, item in value.items() if key != "receipt_digest"}
        )
    elif tamper == "digest":
        value["receipt_digest"] = "sha256:" + "0" * 64

    with pytest.raises(ValueError, match="closure receipt is incomplete"):
        standalone_aks_inventory._verified_closure(
            json.dumps(value),
            expected_attempt_id="attempt.example",
            expected_run_id=f"genesis.{_REVISION}",
            expected_scope_digest=str(binding["scope_digest"]),
            observed_after=observed_after,
        )


def test_initial_inventory_receipt_digest_is_not_trusted_after_tamper() -> None:
    value: dict[str, object] = {
        "schema_version": "fdai.standalone-aks-initial-inventory-receipt.v1",
        "state": "inventory-verified",
        "active_generation_readback_verified": True,
        "complete_generation_readback_verified": True,
        "progress_persisted": True,
        "fresh_generation": True,
        "closure_receipt_verified": True,
        "sources": ["arg", "arm"],
        "scope_digest": "sha256:" + "a" * 64,
        "closure_receipt_digest": "sha256:" + "b" * 64,
        "inventory_binding_digest": "c" * 64,
        "freshness_observed_at": datetime.now(tz=UTC).isoformat(),
        "resource_count": 1,
        "link_count": 1,
        "unmapped_object_count": 0,
        "coverage_gap_count": 0,
    }
    value["receipt_digest"] = canonical_digest(value)
    value["resource_count"] = 2

    with pytest.raises(ValueError, match="inventory is incomplete"):
        standalone_aks_inventory.require_initial_inventory_receipt(
            value,
            runtime_platform="aks",
        )
