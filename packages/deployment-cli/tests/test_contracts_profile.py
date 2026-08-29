from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from fdai_deployment_cli.contracts import (
    ApprovalClass,
    ManifestEntry,
    ProvisionProfile,
    SubscriptionProvisioningManifest,
    canonical_digest,
)
from fdai_deployment_cli.profile import _publish_profile, load_profile, write_profile


def _profile() -> ProvisionProfile:
    return ProvisionProfile(
        environment="dev",
        region="koreacentral",
        target_binding="a" * 64,
        connectivity="online",
        host="managed-vm",
        transport="github-actions",
        access_method="github_actions",
        shadow_only=True,
        approval_quorum=1,
        monthly_cost_ceiling=500,
    )


def _entry(entry_id: str, prerequisites: tuple[str, ...] = ()) -> ManifestEntry:
    return ManifestEntry(
        entry_id=entry_id,
        owner="deployment",
        desired_state="ready",
        prerequisites=prerequisites,
        approval_class=ApprovalClass.STANDARD,
        idempotency_key=f"run.{entry_id}",
        timeout_seconds=300,
        no_progress_seconds=60,
        rollback_ref="rollback.restore",
        observer="observer.independent",
    )


def test_profile_round_trip_is_private_and_stable(tmp_path: Path) -> None:
    path = tmp_path / "private" / "profile.json"
    write_profile(path, _profile())

    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_profile(path) == _profile()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert canonical_digest(payload) == canonical_digest(_profile().to_mapping())


def test_profile_refuses_overwrite_and_symlink(tmp_path: Path) -> None:
    path = tmp_path / "private" / "profile.json"
    write_profile(path, _profile())
    with pytest.raises(FileExistsError):
        write_profile(path, _profile())

    target = tmp_path / "target"
    target.write_text("unchanged", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.parent.chmod(0o700)
    linked.symlink_to(target)
    with pytest.raises(PermissionError):
        write_profile(linked, _profile(), force=True)
    assert target.read_text(encoding="utf-8") == "unchanged"


def test_profile_reader_never_follows_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    linked = tmp_path / "profile.json"
    linked.symlink_to(target)

    with pytest.raises(OSError):
        load_profile(linked)


def test_profile_reader_rejects_fifo_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fifo = tmp_path / "profile.json"
    os.mkfifo(fifo, mode=0o600)
    real_open = os.open

    def open_nonblocking(path: os.PathLike[str], flags: int) -> int:
        assert flags & os.O_NONBLOCK
        return real_open(path, flags)

    monkeypatch.setattr(os, "open", open_nonblocking)
    with pytest.raises(PermissionError, match="regular file"):
        load_profile(fifo)


def test_profile_publish_never_replaces_concurrent_destination(tmp_path: Path) -> None:
    temporary = tmp_path / "temporary"
    destination = tmp_path / "profile.json"
    temporary.write_text("new", encoding="utf-8")
    destination.write_text("concurrent", encoding="utf-8")

    with pytest.raises(FileExistsError):
        _publish_profile(temporary, destination, force=False)
    assert destination.read_text(encoding="utf-8") == "concurrent"
    assert temporary.read_text(encoding="utf-8") == "new"


def test_profile_rejects_non_shadow_and_transport_mismatch() -> None:
    values = _profile().to_mapping()
    values["shadow_only"] = False
    with pytest.raises(ValueError, match="shadow-only"):
        ProvisionProfile.from_mapping(values)

    values = _profile().to_mapping()
    values["access_method"] = "internal_ssh"
    with pytest.raises(ValueError, match="requires github_actions"):
        ProvisionProfile.from_mapping(values)


def test_manifest_rejects_unknown_dependency_and_cycle() -> None:
    with pytest.raises(ValueError, match="unknown prerequisites"):
        SubscriptionProvisioningManifest(
            source_commit="a" * 40,
            profile_digest="b" * 64,
            entries=(_entry("application", ("foundation",)),),
        )
    with pytest.raises(ValueError, match="cycle"):
        SubscriptionProvisioningManifest(
            source_commit="a" * 40,
            profile_digest="b" * 64,
            entries=(
                _entry("foundation", ("application",)),
                _entry("application", ("foundation",)),
            ),
        )


def test_manifest_digest_is_order_stable_for_serialization() -> None:
    manifest = SubscriptionProvisioningManifest(
        source_commit="a" * 40,
        profile_digest="b" * 64,
        entries=(_entry("foundation"), _entry("application", ("foundation",))),
    )
    assert manifest.digest == canonical_digest(manifest.to_mapping())
