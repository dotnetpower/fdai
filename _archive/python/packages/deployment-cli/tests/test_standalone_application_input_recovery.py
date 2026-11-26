from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai_deployment_cli.standalone_application_input_recovery import (
    bind_authoritative_backend_nsg,
    successor_prerequisite_verified,
)
from fdai_deployment_cli.standalone_host_state import private_json


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def _claims(work_dir: Path) -> None:
    _write(work_dir / "application-claim.json", {"claim": "original"})
    _write(work_dir / "application-residual-claim.json", {"claim": "residual"})
    _write(work_dir / "application-residual-review.json", {"review": "residual"})


def test_authoritative_backend_nsg_rebind_is_claimed_and_receipted(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    _claims(tmp_path)
    retained = {
        "browser_gateway": {"backend_nsg_id": "", "location": "westus3"},
        "workloads": {},
    }
    current = {
        "browser_gateway": {
            "backend_nsg_id": "/subscriptions/example/networkSecurityGroups/example",
            "location": "westus3",
        },
        "workloads": {},
    }
    _write(tmp_path / "workloads.auto.tfvars.json", retained)

    assert bind_authoritative_backend_nsg(work_dir=tmp_path, retained=retained, current=current)
    assert private_json(tmp_path / "workloads.auto.tfvars.json", "values") == current
    assert successor_prerequisite_verified(tmp_path, "application")
    assert not successor_prerequisite_verified(tmp_path, "substrate")


def test_authoritative_backend_nsg_rebind_is_idempotent(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    _claims(tmp_path)
    retained = {"browser_gateway": {"backend_nsg_id": ""}}
    current = {"browser_gateway": {"backend_nsg_id": "/subscriptions/example/nsg"}}
    _write(tmp_path / "workloads.auto.tfvars.json", retained)

    assert bind_authoritative_backend_nsg(work_dir=tmp_path, retained=retained, current=current)
    assert not bind_authoritative_backend_nsg(work_dir=tmp_path, retained=current, current=current)


def test_authoritative_backend_nsg_rebind_accepts_ordinary_applied_predecessor(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    _write(tmp_path / "application-claim.json", {"claim": "original"})
    _write(tmp_path / "application-receipt.json", {"receipt": "applied"})
    retained = {"browser_gateway": {"backend_nsg_id": ""}}
    current = {"browser_gateway": {"backend_nsg_id": "/subscriptions/example/nsg"}}
    _write(tmp_path / "workloads.auto.tfvars.json", retained)

    assert bind_authoritative_backend_nsg(work_dir=tmp_path, retained=retained, current=current)
    claim = private_json(
        tmp_path / "application-input-rebind-claim.json",
        "application input rebind claim",
    )
    assert "application_receipt_digest" in claim
    assert "residual_claim_digest" not in claim


@pytest.mark.parametrize(
    "current",
    [
        {"browser_gateway": {"backend_nsg_id": ""}},
        {"browser_gateway": {"backend_nsg_id": "/subscriptions/example/nsg"}, "extra": True},
        {"browser_gateway": {"backend_nsg_id": "/subscriptions/example/nsg", "location": "x"}},
    ],
)
def test_authoritative_backend_nsg_rebind_rejects_broader_changes(
    tmp_path: Path, current: dict[str, object]
) -> None:
    tmp_path.chmod(0o700)
    _claims(tmp_path)
    retained = {"browser_gateway": {"backend_nsg_id": ""}}
    _write(tmp_path / "workloads.auto.tfvars.json", retained)

    if current == retained:
        assert not bind_authoritative_backend_nsg(
            work_dir=tmp_path, retained=retained, current=current
        )
    else:
        with pytest.raises(ValueError, match="retained workloads"):
            bind_authoritative_backend_nsg(work_dir=tmp_path, retained=retained, current=current)
