from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from fdai_deployment_cli.contracts import canonical_bytes

from fdai_lifecycle_hub import cli, domain
from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.catalog_import import load_pinned_export
from fdai_lifecycle_hub.domain import Installation, Issued
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import HubSigningKey, generate_development_key, load_signing_key
from fdai_lifecycle_hub.store import HubStore
from fdai_release_hub.store import Change, ReleaseStore


def test_vendor_publication_to_lifecycle_plan_and_recall(
    tmp_path: Path,
    catalog: ReleaseCatalog,
    installation: Installation,
    key: HubSigningKey,
    now: datetime,
) -> None:
    vendor = ReleaseStore(tmp_path / "vendor.db", key, clock=lambda: now)
    for release_id in ("1.5.0", "1.6.0"):
        for action in ("register", "publish"):
            vendor.change(
                action,
                release_id,
                Change(
                    revision=vendor.snapshot()["revision"],
                    confirmation=release_id,
                    reason="Local integration review",
                    manifest=canonical_bytes(catalog.releases[release_id].to_mapping()).decode()
                    if action == "register"
                    else None,
                ),
            )
    target = replace(installation, settings=replace(installation.settings, channel="DEV"))

    def compute():
        raw, digest = vendor.export()
        admitted = load_pinned_export(
            raw, expected_sha256=digest, public_key=key.public_key, now=now
        )
        return plan_next(target, now, catalog=admitted, key=key)

    first = compute()
    assert isinstance(first, Issued)
    assert first.plan.target_release_id == "1.6.0"
    vendor.change(
        "recall",
        "1.6.0",
        Change(
            revision=4,
            confirmation="1.6.0",
            reason="Withdraw failed candidate",
        ),
    )
    second = compute()
    assert isinstance(second, Issued)
    assert second.plan.target_release_id == "1.5.0"
    assert "release_recalled" in {b.reason_code for b in second.checks[0].blocks}


def test_recompute_pinned_cli_issues_from_verified_vendor_export(
    tmp_path: Path,
    catalog: ReleaseCatalog,
    installation: Installation,
    store: HubStore,
    enroll: Callable[[HubStore, Installation], None],
    now: datetime,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = replace(installation, settings=replace(installation.settings, channel="DEV"))
    enroll(store, target)
    key_path = tmp_path / "signing.pem"
    public_path = generate_development_key(key_path)
    vendor = ReleaseStore(
        tmp_path / "vendor.db", load_signing_key(key_path, epoch=1), clock=lambda: now
    )
    for revision, action in enumerate(("register", "publish")):
        vendor.change(
            action,
            "1.6.0",
            Change(
                revision=revision,
                confirmation="1.6.0",
                reason="CLI integration review",
                manifest=canonical_bytes(catalog.releases["1.6.0"].to_mapping()).decode()
                if action == "register"
                else None,
            ),
        )
    raw, digest = vendor.export()
    export = tmp_path / "catalog.json"
    export.write_bytes(raw)
    monkeypatch.setattr(cli, "_store", lambda: store)
    monkeypatch.setattr(domain, "utc_now", lambda: now)
    assert (
        cli.main(
            [
                "recompute-pinned",
                target.installation_id,
                "--export",
                str(export),
                "--sha256",
                digest,
                "--release-public-key",
                str(public_path),
                "--minimum-revision",
                "0",
                "--key",
                str(key_path),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert (output["outcome"], output["target"]) == ("issued", "1.6.0")
