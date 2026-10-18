from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli.aks_service_update import service_update_review
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.standalone_service_update_finalization import (
    _finalize_service_update,
)


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def test_finalization_accepts_exact_legacy_verification_recovery(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    service = "core-control-plane"
    operation = "service-update-core-control-plane-0123456789ab"
    record = {
        "service": service,
        "image": "registry.invalid/core@sha256:" + "a" * 64,
        "source_commit": "b" * 40,
        "update_digest": "c" * 64,
    }
    context = {
        "active_service_update": {
            "operation": operation,
            "service": service,
            "update_digest": record["update_digest"],
        }
    }
    receipt = {
        "schema_version": "fdai.standalone-application-apply-receipt.v1",
        "state": "applied",
        "stage": "application",
        "service_update": service_update_review(record),
        "control_plane_readback_verified": True,
        "peer_state_unchanged_verified": True,
        "terraform_zero_change_verified": True,
        "verification_only_recovery": True,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    _write(tmp_path / "context.json", context)
    _write(tmp_path / f"{operation}-receipt.json", receipt)

    def private_json(path: Path, _label: str) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def replace_private_json(path: Path, value: dict[str, object]) -> None:
        _write(path, value)

    result = _finalize_service_update(
        SimpleNamespace(
            operation=operation,
            service=service,
            receipt_digest=receipt["receipt_digest"],
        ),
        tmp_path,
        private_json=private_json,
        replace_private_json=replace_private_json,
        service_update_record=lambda *_args, **_kwargs: record,
        service_update_review=service_update_review,
    )

    assert result["state"] == "finalized"
    assert "active_service_update" not in private_json(tmp_path / "context.json", "context")


def test_finalization_rejects_unbound_legacy_receipt(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    service = "core-control-plane"
    operation = "service-update-core-control-plane-0123456789ab"
    record = {
        "service": service,
        "image": "registry.invalid/core@sha256:" + "a" * 64,
        "source_commit": "b" * 40,
        "update_digest": "c" * 64,
    }
    context = {"active_service_update": {"operation": operation, "service": service}}
    receipt = {
        "state": "applied",
        "service_update": service_update_review(record),
        "control_plane_readback_verified": True,
        "peer_state_unchanged_verified": True,
        "terraform_zero_change_verified": True,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    _write(tmp_path / "context.json", context)
    _write(tmp_path / f"{operation}-receipt.json", receipt)

    with pytest.raises(ValueError, match="receipt is incomplete"):
        _finalize_service_update(
            SimpleNamespace(
                operation=operation,
                service=service,
                receipt_digest=receipt["receipt_digest"],
            ),
            tmp_path,
            private_json=lambda path, _label: json.loads(path.read_text(encoding="utf-8")),
            replace_private_json=lambda *_args: None,
            service_update_record=lambda *_args, **_kwargs: record,
            service_update_review=service_update_review,
        )
