"""Deterministic deployment bundle builder tests."""

from __future__ import annotations

import importlib.util
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.deployment_cli.bundle import verify_deployment_bundle

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "deployment"
    / "release"
    / "build-deployment-bundle.py"
)
_EPOCH = 1_700_000_000


@pytest.fixture(scope="module")
def builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_deployment_bundle", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _private_key() -> bytes:
    return Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _source(root: Path) -> tuple[str, ...]:
    paths = (
        "infra/main.tf",
        "policies/compute/example.rego",
        "rule-catalog/schema/example.json",
        "rule-catalog/profiles/example.yaml",
        "rule-catalog/risk-classification.yaml",
    )
    for index, relative in enumerate(paths):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"content-{index}\n", encoding="utf-8")
    return paths


def _build(builder: ModuleType, source: Path, target: Path, key: bytes) -> tuple[Path, Path]:
    bundle = target / "bundle"
    archive = target / "bundle.tar.gz"
    target.mkdir()
    builder.build_bundle(
        source,
        bundle,
        source_paths=_source(source),
        bundle_version="1.2.3",
        release_channel="stable",
        min_cli_version="1.0.0",
        max_cli_version="1.9.0",
        private_key_pem=key,
        source_date_epoch=_EPOCH,
    )
    builder.write_reproducible_archive(
        bundle,
        archive,
        bundle_version="1.2.3",
        source_date_epoch=_EPOCH,
    )
    return bundle, archive


def test_two_builds_are_byte_identical_and_verify(
    builder: ModuleType,
    tmp_path: Path,
) -> None:
    key = _private_key()
    source = tmp_path / "source"
    first_bundle, first_archive = _build(builder, source, tmp_path / "first", key)
    second_bundle, second_archive = _build(builder, source, tmp_path / "second", key)

    first_files = {
        path.relative_to(first_bundle).as_posix(): path.read_bytes()
        for path in first_bundle.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second_bundle).as_posix(): path.read_bytes()
        for path in second_bundle.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    assert first_archive.read_bytes() == second_archive.read_bytes()
    result = verify_deployment_bundle(
        first_bundle,
        public_key_pem=builder.public_key_pem(key),
        cli_version="1.3.0",
    )
    assert result.file_count == 6

    with tarfile.open(first_archive, "r:gz") as archive:
        assert all(member.uid == 0 and member.gid == 0 for member in archive.getmembers())


@pytest.mark.parametrize(
    "path",
    (
        "infra/dev.plan",
        "infra/prod.tfvars",
        "infra/terraform.tfstate",
        "outside/file.txt",
    ),
)
def test_forbidden_or_outside_source_is_rejected(
    builder: ModuleType,
    tmp_path: Path,
    path: str,
) -> None:
    source = tmp_path / "source"
    target = source / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("unsafe\n", encoding="utf-8")

    with pytest.raises(builder.BundleBuildError):
        builder.build_bundle(
            source,
            tmp_path / "bundle",
            source_paths=(path,),
            bundle_version="1.2.3",
            release_channel="stable",
            min_cli_version="1.0.0",
            max_cli_version=None,
            private_key_pem=_private_key(),
            source_date_epoch=_EPOCH,
        )
