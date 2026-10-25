"""Hub ownership marker: Terraform refuses the workloads root once the Hub owns the objects."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai_deployment_cli import hub_ownership, standalone_host

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64


def aks_context(work_dir: Path) -> dict[str, object]:
    return {
        "runtime_profile": {"runtime_platform": "aks"},
        "workloads_terraform_data": str(work_dir / "workloads-terraform-data"),
        "runtime_terraform_data": str(work_dir / "runtime-terraform-data"),
    }


@pytest.fixture(autouse=True)
def isolated_terraform_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "TF_DATA_DIR", "")
    monkeypatch.delitem(os.environ, "TF_DATA_DIR")


def test_without_a_marker_terraform_keeps_the_workloads(tmp_path: Path) -> None:
    standalone_host._activate_terraform_stage("application", aks_context(tmp_path), tmp_path)

    assert (tmp_path / "workloads-terraform-data").is_dir()


def test_the_marker_refuses_every_workloads_stage_activation(tmp_path: Path) -> None:
    hub_ownership.record_hub_ownership(
        tmp_path, installation_id="installation-dev", handoff_receipt_digest=DIGEST
    )

    with pytest.raises(ValueError, match="Hub-managed"):
        standalone_host._activate_terraform_stage("application", aks_context(tmp_path), tmp_path)

    assert not (tmp_path / "workloads-terraform-data").exists()


def test_the_marker_does_not_block_the_other_stages(tmp_path: Path) -> None:
    hub_ownership.record_hub_ownership(
        tmp_path, installation_id="installation-dev", handoff_receipt_digest=DIGEST
    )

    standalone_host._activate_terraform_stage("runtime", aks_context(tmp_path), tmp_path)

    assert (tmp_path / "runtime-terraform-data").is_dir()


def test_recording_is_private_idempotent_and_never_overwrites_a_different_handoff(
    tmp_path: Path,
) -> None:
    moment = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    first = hub_ownership.record_hub_ownership(
        tmp_path,
        installation_id="installation-dev",
        handoff_receipt_digest=DIGEST,
        recorded_at=moment,
    )
    again = hub_ownership.record_hub_ownership(
        tmp_path, installation_id="installation-dev", handoff_receipt_digest=DIGEST
    )

    assert again == first
    assert (tmp_path / hub_ownership.MARKER_NAME).stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="different hub ownership marker"):
        hub_ownership.record_hub_ownership(
            tmp_path, installation_id="installation-dev", handoff_receipt_digest=OTHER
        )
    with pytest.raises(ValueError, match="different hub ownership marker"):
        hub_ownership.record_hub_ownership(
            tmp_path, installation_id="installation-other", handoff_receipt_digest=DIGEST
        )


@pytest.mark.parametrize(
    ("installation_id", "digest"),
    [
        ("", DIGEST),
        ("bad id", DIGEST),
        ("installation-dev", "sha256:xyz"),
        ("installation-dev", ""),
    ],
)
def test_marker_inputs_are_validated(tmp_path: Path, installation_id: str, digest: str) -> None:
    with pytest.raises(ValueError, match="inputs are invalid"):
        hub_ownership.record_hub_ownership(
            tmp_path, installation_id=installation_id, handoff_receipt_digest=digest
        )


def test_a_naive_timestamp_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        hub_ownership.record_hub_ownership(
            tmp_path,
            installation_id="installation-dev",
            handoff_receipt_digest=DIGEST,
            recorded_at=datetime(2026, 10, 24),
        )


@pytest.mark.parametrize(
    "damage",
    ["not json", "{}", '{"schema_version":"other"}', "[]"],
)
def test_a_damaged_marker_keeps_the_workloads_hub_managed(tmp_path: Path, damage: str) -> None:
    path = tmp_path / hub_ownership.MARKER_NAME
    path.write_text(damage, encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(ValueError, match="unreadable; workloads stay Hub-managed"):
        hub_ownership.require_terraform_owned_workloads(tmp_path)


def test_a_tampered_marker_digest_is_detected(tmp_path: Path) -> None:
    hub_ownership.record_hub_ownership(
        tmp_path, installation_id="installation-dev", handoff_receipt_digest=DIGEST
    )
    path = tmp_path / hub_ownership.MARKER_NAME
    path.write_text(path.read_text().replace("installation-dev", "installation-xxx"))
    path.chmod(0o600)

    with pytest.raises(ValueError, match="unreadable"):
        hub_ownership.require_terraform_owned_workloads(tmp_path)


def test_a_group_readable_marker_is_not_trusted_and_a_symlink_marker_refuses(
    tmp_path: Path,
) -> None:
    hub_ownership.record_hub_ownership(
        tmp_path, installation_id="installation-dev", handoff_receipt_digest=DIGEST
    )
    path = tmp_path / hub_ownership.MARKER_NAME
    path.chmod(0o644)
    with pytest.raises(ValueError):
        hub_ownership.require_terraform_owned_workloads(tmp_path)

    path.unlink()
    (tmp_path / "elsewhere").write_text("{}")
    path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        hub_ownership.require_terraform_owned_workloads(tmp_path)


def test_release_requires_a_rollback_receipt_and_restores_terraform_ownership(
    tmp_path: Path,
) -> None:
    hub_ownership.record_hub_ownership(
        tmp_path, installation_id="installation-dev", handoff_receipt_digest=DIGEST
    )

    with pytest.raises(ValueError, match="rollback receipt"):
        hub_ownership.release_hub_ownership(tmp_path, rollback_receipt_digest="")
    with pytest.raises(ValueError, match="Hub-managed"):
        hub_ownership.require_terraform_owned_workloads(tmp_path)

    hub_ownership.release_hub_ownership(tmp_path, rollback_receipt_digest=OTHER)
    hub_ownership.require_terraform_owned_workloads(tmp_path)
    hub_ownership.release_hub_ownership(tmp_path, rollback_receipt_digest=OTHER)
