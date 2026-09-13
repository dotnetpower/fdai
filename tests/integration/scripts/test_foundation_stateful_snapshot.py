"""Retained Terraform state must not invalidate immutable Foundation execution sources."""

from __future__ import annotations

import hashlib
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def prepared_snapshot(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts/deployment/release"))
    monkeypatch.syspath_prepend(str(ROOT / "scripts/deployment/azure"))
    import genesis_foundation_apply as apply

    builder = runpy.run_path(str(ROOT / "scripts/deployment/release/build-deployment-bundle.py"))
    source = tmp_path / "source"
    infra = source / "infra/genesis-foundation"
    infra.mkdir(parents=True)
    (infra / "main.tf").write_text("terraform {}\n")
    (infra / ".terraform.lock.hcl").write_text("# synthetic lock\n")
    catalog = source / "rule-catalog/placeholders"
    catalog.mkdir(parents=True)
    (catalog / ".gitkeep").write_bytes(b"")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    bundle = tmp_path / "signed-bundle"
    builder["build_bundle"](
        source,
        bundle,
        source_paths=(
            "infra/genesis-foundation/main.tf",
            "infra/genesis-foundation/.terraform.lock.hcl",
            "rule-catalog/placeholders/.gitkeep",
        ),
        bundle_version="0.1.0",
        release_channel="development",
        min_cli_version="0.1.0",
        max_cli_version=None,
        private_key_pem=private.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
        source_date_epoch=1700000000,
    )
    archive = tmp_path / "bundle.tar.gz"
    builder["write_reproducible_archive"](
        bundle, archive, bundle_version="0.1.0", source_date_epoch=1700000000
    )
    key_path = tmp_path / "synthetic-public.pem"
    key_path.write_bytes(public)
    terraform = tmp_path / "terraform"
    terraform.write_bytes(b"synthetic executable, never run")
    digest = hashlib.sha256(terraform.read_bytes()).hexdigest()
    monkeypatch.setattr(
        apply,
        "verify_offline_kit",
        lambda *a, **kw: SimpleNamespace(
            manifest_digest="a" * 64,
            file_digests=(("terraform", digest),),
            terraform_binary="terraform",
        ),
    )
    monkeypatch.setattr(
        apply,
        "materialize_verified_artifacts",
        lambda *a, **kw: SimpleNamespace(
            deployment_bundle=archive,
            terraform_binary=terraform,
            provider_mirror=tmp_path / "mirror",
        ),
    )
    plan = tmp_path / "plan"
    plan.mkdir(mode=0o700)
    context = {
        "offline_manifest_digest": "a" * 64,
        "deployment_bundle_digest": hashlib.sha256(
            (bundle / "manifest.json").read_bytes()
        ).hexdigest(),
        "provider_lock_digest": hashlib.sha256(
            (infra / ".terraform.lock.hcl").read_bytes()
        ).hexdigest(),
        "terraform_digest": digest,
    }
    arguments = dict(
        plan_directory=plan,
        offline_kit=tmp_path,
        release_root=key_path,
        bundle_public_key=key_path,
        context=context,
    )
    snapshot = apply._prepare_verified_snapshot(**arguments)
    execution = snapshot.infra_root
    snapshot.cleanup()
    for name in ("terraform.tfstate", "terraform.tfstate.backup"):
        (execution / name).write_text('{"version":4,"resources":[]}\n')
        (execution / name).chmod(0o600)
    return apply, arguments, execution


def test_retained_state_resumes_without_source_replacement(prepared_snapshot):
    apply, arguments, execution = prepared_snapshot
    state = (execution / "terraform.tfstate").read_bytes()
    snapshot = apply._prepare_verified_snapshot(**arguments)
    assert snapshot.infra_root == execution
    assert (execution / "terraform.tfstate").read_bytes() == state
    assert (execution / "terraform.tfstate.backup").read_bytes() == state
    snapshot.cleanup()


@pytest.mark.parametrize(
    "change", ["source", "extra", "other-state", "state-link", "empty-state", "empty-source-link"]
)
def test_state_exception_never_relaxes_immutable_source_checks(prepared_snapshot, change):
    apply, arguments, execution = prepared_snapshot
    if change == "source":
        (execution / "main.tf").write_text("terraform {}\n# altered source\n")
    elif change == "state-link":
        (execution / "terraform.tfstate").unlink()
        (execution / "terraform.tfstate").symlink_to("terraform.tfstate.backup")
    elif change == "empty-state":
        (execution / "terraform.tfstate").write_bytes(b"")
    elif change == "empty-source-link":
        placeholder = execution.parents[1] / "rule-catalog/placeholders/.gitkeep"
        placeholder.unlink()
        placeholder.symlink_to(execution / "terraform.tfstate")
    else:
        name = "extra.tf" if change == "extra" else "terraform.tfstate.unreviewed"
        (execution / name).write_text("unexpected\n")
        (execution / name).chmod(0o600)
    with pytest.raises(ValueError):
        apply._prepare_verified_snapshot(**arguments)
    assert (execution / "terraform.tfstate.backup").exists()
