from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli.contracts import (
    ProvisionProfile,
    canonical_bytes,
    canonical_digest,
    load_json_object,
)
from fdai_deployment_cli.foundation_adoption import (
    stage_recovered_foundation,
)
from fdai_deployment_cli.foundation_adoption_evidence import (
    validate_foundation_adoption_receipt,
)
from fdai_deployment_cli.foundation_adoption_host import (
    load_foundation_host_adoption,
)
from fdai_deployment_cli.profile import write_profile
from fdai_deployment_cli.target import compute_target_binding

SOURCE = "a" * 40
APPLICATION_SOURCE = "b" * 40
TENANT = "00000000-0000-0000-0000-000000000001"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000002"
TARGET = compute_target_binding(tenant_id=TENANT, subscription_id=SUBSCRIPTION)
REGION = "westus2"


def _write(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    path.chmod(0o600)


def _receipt(value: dict[str, object], field: str = "receipt_digest") -> bytes:
    value[field] = canonical_digest(value)
    return canonical_bytes(value)


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    foundation = tmp_path / "foundation"
    recovery = tmp_path / "recovery"
    foundation.mkdir(mode=0o700)
    recovery.mkdir(mode=0o700)
    write_profile(
        foundation / "profile.json",
        ProvisionProfile(
            environment="dev",
            region=REGION,
            target_binding=TARGET,
            connectivity="online",
            host="managed-vm",
            transport="manual",
            access_method="bastion",
            shadow_only=True,
            approval_quorum=1,
            monthly_cost_ceiling=2000,
        ),
    )
    _write(foundation / "runner_ed25519", b"private-key")
    handoff = {
        "source_commit": SOURCE,
        "run_digest": "c" * 64,
        "tenant_id": TENANT,
        "subscription_id": SUBSCRIPTION,
        "region": REGION,
        "runner": {"execution_transport": "manual"},
        "access": {"method": "bastion"},
    }
    _write(recovery / "recovery-private-handoff.json", canonical_bytes(handoff))
    recovery_receipt = {
        "schema_version": "fdai.foundation-recovery-receipt.v1",
        "state": "verified",
        "source_commit": SOURCE,
        "handoff_digest": canonical_digest(handoff),
        "control_plane_readback_verified": True,
        "runner_attested": False,
        "remote_backend_authority_verified": False,
        "zero_change_verified": True,
    }
    recovery_raw = _receipt(recovery_receipt)
    _write(recovery / "recovery-apply-receipt.json", recovery_raw)
    known_hosts = b"host-key"
    _write(recovery / "runner-known-hosts", known_hosts)
    enrollment = {
        "schema_version": "fdai.genesis-runner-enrollment-receipt.v1",
        "state": "attested",
        "source_commit": SOURCE,
        "target_binding": TARGET,
        "foundation_receipt_digest": recovery_receipt["receipt_digest"],
        "host_key_digest": hashlib.sha256(known_hosts).hexdigest(),
        "effect_verified": True,
        "identity_attested": True,
        "manual_host_readback_verified": True,
        "services_attested": True,
    }
    enrollment_raw = _receipt(enrollment)
    _write(recovery / "runner-enrollment-receipt.json", enrollment_raw)
    authority = {
        "schema_version": "fdai.genesis-foundation-state-authority.v1",
        "state": "verified",
        "source_commit": SOURCE,
        "target_binding": TARGET,
        "state_digest": "d" * 64,
        "managed_resource_count": 35,
        "remote_backend_authority_verified": True,
        "zero_change_verified": True,
        "local_state_deletion_authorized": True,
    }
    authority_raw = _receipt(authority, "authority_digest")
    _write(recovery / "foundation-state-authority.json", authority_raw)
    state_receipt = {
        "schema_version": "fdai.genesis-foundation-state-handoff-receipt.v1",
        "state": "verified",
        "source_commit": SOURCE,
        "target_binding": TARGET,
        "foundation_receipt_digest": recovery_receipt["receipt_digest"],
        "enrollment_receipt_digest": enrollment["receipt_digest"],
        "authority_digest": authority["authority_digest"],
        "state_digest": authority["state_digest"],
        "managed_resource_count": 35,
        "effect_verified": True,
        "runner_attested": True,
        "remote_backend_authority_verified": True,
        "zero_change_verified": True,
        "local_state_deletion_authorized": True,
        "local_state_deleted": True,
        "remote_transient_deleted": True,
    }
    _write(
        recovery / "foundation-state-handoff-receipt.json",
        _receipt(state_receipt),
    )
    return foundation, recovery


def _stage(tmp_path: Path):
    foundation, recovery = _inputs(tmp_path)
    return stage_recovered_foundation(
        foundation_directory=foundation,
        recovery_directory=recovery,
        destination=tmp_path / "destination",
        application_source_commit=APPLICATION_SOURCE,
        kit_manifest_digest="e" * 64,
        runtime_release_digest="f" * 64,
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        region=REGION,
        monthly_cost_ceiling=2000,
    )


def test_recovered_foundation_adoption_stages_no_effect_context(tmp_path: Path) -> None:
    adoption = _stage(tmp_path)

    assert adoption.receipt["state"] == "adopted"
    assert adoption.receipt["foundation_source_commit"] == SOURCE
    assert adoption.receipt["application_source_commit"] == APPLICATION_SOURCE
    assert adoption.receipt["managed_resource_count"] == 35
    assert adoption.receipt["no_effect_adoption"] is True
    assert adoption.receipt["mutation_performed"] is False
    assert adoption.prepared.source_commit == APPLICATION_SOURCE
    assert adoption.prepared.run_binding == adoption.receipt["adopted_run_binding"]
    assert adoption.status["foundation_report"] == {
        "foundation_plan": {"plan_ref": "foundation-adoption"},
        "state_handoff": {"receipt_digest": adoption.receipt["foundation_state_receipt_digest"]},
    }
    assert (tmp_path / "destination/foundation-adoption/foundation-private-handoff.json").is_file()
    assert (tmp_path / "destination/foundation-adoption/runner-known-hosts").is_file()


def test_recovered_foundation_adoption_selects_current_kit_source(tmp_path: Path) -> None:
    adoption = _stage(tmp_path)
    handoff = load_json_object(
        (tmp_path / "destination/foundation-adoption/foundation-private-handoff.json").read_bytes(),
        label="Foundation handoff",
    )
    selected = load_foundation_host_adoption(
        tmp_path / "destination/foundation-adoption-receipt.json",
        handoff=handoff,
        target_binding=TARGET,
    )
    kit = SimpleNamespace(
        source_commit=APPLICATION_SOURCE,
        verification=SimpleNamespace(manifest_digest="e" * 64),
        runtime=SimpleNamespace(digest="f" * 64),
    )

    selected.require_kit(kit)
    selected.require_context(
        {
            "source_commit": APPLICATION_SOURCE,
            "foundation_adoption_digest": adoption.receipt["receipt_digest"],
            "kit_manifest_digest": "e" * 64,
            "runtime_release_digest": "f" * 64,
        }
    )

    assert selected.source_commit == APPLICATION_SOURCE
    assert selected.digest == adoption.receipt["receipt_digest"]


def test_recovered_foundation_adoption_is_idempotent(tmp_path: Path) -> None:
    first = _stage(tmp_path)
    foundation = tmp_path / "foundation"
    recovery = tmp_path / "recovery"

    second = stage_recovered_foundation(
        foundation_directory=foundation,
        recovery_directory=recovery,
        destination=tmp_path / "destination",
        application_source_commit=APPLICATION_SOURCE,
        kit_manifest_digest="e" * 64,
        runtime_release_digest="f" * 64,
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        region=REGION,
        monthly_cost_ceiling=2000,
    )

    assert second.receipt == first.receipt


def test_recovered_foundation_adoption_rejects_target_change(tmp_path: Path) -> None:
    foundation, recovery = _inputs(tmp_path)

    with pytest.raises(ValueError, match="profile differs"):
        stage_recovered_foundation(
            foundation_directory=foundation,
            recovery_directory=recovery,
            destination=tmp_path / "destination",
            application_source_commit=APPLICATION_SOURCE,
            kit_manifest_digest="e" * 64,
            runtime_release_digest="f" * 64,
            tenant_id=TENANT,
            subscription_id="00000000-0000-0000-0000-000000000003",
            region=REGION,
            monthly_cost_ceiling=2000,
        )


def test_recovered_foundation_adoption_rejects_nested_destination(tmp_path: Path) -> None:
    foundation, recovery = _inputs(tmp_path)

    with pytest.raises(ValueError, match="destination must be separate"):
        stage_recovered_foundation(
            foundation_directory=foundation,
            recovery_directory=recovery,
            destination=foundation / "application",
            application_source_commit=APPLICATION_SOURCE,
            kit_manifest_digest="e" * 64,
            runtime_release_digest="f" * 64,
            tenant_id=TENANT,
            subscription_id=SUBSCRIPTION,
            region=REGION,
            monthly_cost_ceiling=2000,
        )


def test_recovered_foundation_adoption_rejects_incomplete_state(tmp_path: Path) -> None:
    foundation, recovery = _inputs(tmp_path)
    path = recovery / "foundation-state-handoff-receipt.json"
    value = load_json_object(path.read_bytes(), label="state receipt")
    value.pop("receipt_digest")
    value["local_state_deleted"] = False
    _write(path, _receipt(value))

    with pytest.raises(ValueError, match="evidence is incomplete"):
        stage_recovered_foundation(
            foundation_directory=foundation,
            recovery_directory=recovery,
            destination=tmp_path / "destination",
            application_source_commit=APPLICATION_SOURCE,
            kit_manifest_digest="e" * 64,
            runtime_release_digest="f" * 64,
            tenant_id=TENANT,
            subscription_id=SUBSCRIPTION,
            region=REGION,
            monthly_cost_ceiling=2000,
        )


def test_recovered_foundation_adoption_rejects_receipt_tampering(tmp_path: Path) -> None:
    foundation, recovery = _inputs(tmp_path)
    path = recovery / "runner-enrollment-receipt.json"
    path.write_bytes(path.read_bytes().replace(b'"attested"', b'"tampered"'))

    with pytest.raises(ValueError, match="digest differs"):
        stage_recovered_foundation(
            foundation_directory=foundation,
            recovery_directory=recovery,
            destination=tmp_path / "destination",
            application_source_commit=APPLICATION_SOURCE,
            kit_manifest_digest="e" * 64,
            runtime_release_digest="f" * 64,
            tenant_id=TENANT,
            subscription_id=SUBSCRIPTION,
            region=REGION,
            monthly_cost_ceiling=2000,
        )


def test_foundation_adoption_receipt_rejects_another_kit(tmp_path: Path) -> None:
    adoption = _stage(tmp_path)
    handoff = load_json_object(
        (tmp_path / "recovery/recovery-private-handoff.json").read_bytes(),
        label="Foundation handoff",
    )
    changed = dict(adoption.receipt)
    changed.pop("receipt_digest")
    changed["kit_manifest_digest"] = "0" * 64
    changed["receipt_digest"] = canonical_digest(changed)

    with pytest.raises(ValueError, match="exact context"):
        validate_foundation_adoption_receipt(
            changed,
            handoff=handoff,
            target_binding=TARGET,
            application_source_commit=APPLICATION_SOURCE,
            kit_manifest_digest="e" * 64,
            runtime_release_digest="f" * 64,
        )


def _swap_recovery_receipt(recovery: Path, **fields: object) -> None:
    """Rewrite the terminal Foundation receipt and re-bind the dependent chain.

    Changing the receipt changes its digest, so enrollment and state handoff must be
    re-pointed at it. Otherwise the chain check fires first and the test would never
    reach the terminal-pair decision it is about.
    """

    def _load(name: str) -> dict[str, object]:
        return load_json_object(
            (recovery / name).read_bytes(), label="retained Foundation evidence"
        )

    record = _load("recovery-apply-receipt.json")
    record.pop("receipt_digest", None)
    record.update(fields)
    raw = _receipt(record)
    _write(recovery / "recovery-apply-receipt.json", raw)
    digest = load_json_object(raw, label="terminal Foundation receipt")["receipt_digest"]

    enrollment = _load("runner-enrollment-receipt.json")
    enrollment.pop("receipt_digest", None)
    enrollment["foundation_receipt_digest"] = digest
    enrollment_raw = _receipt(enrollment)
    _write(recovery / "runner-enrollment-receipt.json", enrollment_raw)
    enrollment_digest = load_json_object(enrollment_raw, label="enrollment receipt")[
        "receipt_digest"
    ]

    state = _load("foundation-state-handoff-receipt.json")
    state.pop("receipt_digest", None)
    state["foundation_receipt_digest"] = digest
    state["enrollment_receipt_digest"] = enrollment_digest
    _write(recovery / "foundation-state-handoff-receipt.json", _receipt(state))


def test_an_ordinary_apply_receipt_is_accepted_for_adoption(tmp_path: Path) -> None:
    """A Foundation that completed normally must continue without a recovery detour."""

    foundation, recovery = _inputs(tmp_path)
    _swap_recovery_receipt(
        recovery,
        schema_version="fdai.genesis-foundation-apply-receipt.v1",
        state="applied",
    )

    adoption = stage_recovered_foundation(
        foundation_directory=foundation,
        recovery_directory=recovery,
        destination=tmp_path / "destination",
        application_source_commit=APPLICATION_SOURCE,
        kit_manifest_digest="e" * 64,
        runtime_release_digest="f" * 64,
        tenant_id=TENANT,
        subscription_id=SUBSCRIPTION,
        region=REGION,
        monthly_cost_ceiling=2000,
    )

    assert adoption.receipt["state"] == "adopted"
    assert adoption.receipt["no_effect_adoption"] is True


@pytest.mark.parametrize(
    ("schema_version", "state"),
    [
        ("fdai.genesis-foundation-apply-receipt.v1", "applying"),
        ("fdai.foundation-recovery-receipt.v1", "applied"),
        ("fdai.genesis-foundation-state-handoff-receipt.v1", "verified"),
        ("fdai.unknown-receipt.v1", "verified"),
    ],
)
def test_a_non_terminal_or_mismatched_receipt_is_refused(
    tmp_path: Path, schema_version: str, state: str
) -> None:
    """Only the two exact terminal pairs adopt; a crossed pair must not."""

    foundation, recovery = _inputs(tmp_path)
    _swap_recovery_receipt(recovery, schema_version=schema_version, state=state)

    with pytest.raises(ValueError, match="not terminal"):
        stage_recovered_foundation(
            foundation_directory=foundation,
            recovery_directory=recovery,
            destination=tmp_path / "destination",
            application_source_commit=APPLICATION_SOURCE,
            kit_manifest_digest="e" * 64,
            runtime_release_digest="f" * 64,
            tenant_id=TENANT,
            subscription_id=SUBSCRIPTION,
            region=REGION,
            monthly_cost_ceiling=2000,
        )
