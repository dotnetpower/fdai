"""Trust lifecycle plus durable disabled-first installation tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from fdai.core.capability_catalog import (
    CapabilityBundle,
    CapabilityReferences,
    ExtensionManager,
    ExtensionManifest,
    ExtensionPackage,
)
from fdai.core.skills import (
    SkillBundleCatalog,
    SkillCatalog,
    encode_skill_bundle_manifest,
    skill_body_digest,
)
from fdai.core.supply_chain import (
    TrustedArtifactConflictError,
    TrustedArtifactInstaller,
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
    decode_skill_bundle,
)

_NOW = datetime(2026, 7, 17, 13, 0, tzinfo=UTC)


class _Store:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.records: list[TrustedArtifactRecord] = []

    async def put(
        self,
        record: TrustedArtifactRecord,
        *,
        expected_revision: int,
    ) -> TrustedArtifactRecord:
        assert expected_revision == 0
        if self.fail:
            raise TrustedArtifactConflictError("conflict")
        self.records.append(record)
        return record

    async def get(self, kind, artifact_id):  # type: ignore[no-untyped-def]
        del kind, artifact_id
        return None

    async def list(self, kind):  # type: ignore[no-untyped-def]
        del kind
        return tuple(self.records)


class _Allow:
    def verify(self, _value, _raw):  # type: ignore[no-untyped-def]
        return True


def _skill(*, reference: tuple[str, bytes] | None = None) -> bytes:
    body = "Use deterministic tools only."
    reference_yaml = ""
    if reference is not None:
        path, content = reference
        reference_yaml = (
            "references:\n"
            f"- path: {path}\n"
            f"  sha256: {hashlib.sha256(content).hexdigest()}\n"
            f"  size_bytes: {len(content)}\n"
            "  media_type: text/plain\n"
        )
    return (
        "---\n"
        "name: example.skill\n"
        "version: 1.0.0\n"
        "description: Example\n"
        "source: publisher.example\n"
        f"body_sha256: {skill_body_digest(body)}\n"
        "required_tools: []\n"
        "allowed_agents: []\n"
        f"{reference_yaml}"
        "---\n"
        f"{body}\n"
    ).encode()


async def test_skill_install_persists_raw_disabled_artifact() -> None:
    store = _Store()
    installer = TrustedArtifactInstaller(store=store)
    raw = _skill()

    catalog = await installer.install_skill(
        SkillCatalog(),
        raw,
        signature=b"s" * 64,
        verifier=_Allow(),
        now=_NOW,
    )

    assert catalog.get("example.skill").enabled is False
    assert store.records[0].kind is TrustedArtifactKind.SKILL
    assert store.records[0].state is TrustedArtifactState.DISABLED
    assert store.records[0].artifact == raw
    assert store.records[0].content_sha256 == hashlib.sha256(raw).hexdigest()


async def test_skill_bundle_install_persists_canonical_reference_artifact() -> None:
    store = _Store()
    installer = TrustedArtifactInstaller(store=store)
    reference = ("references/guide.txt", b"bounded guide")
    raw = _skill(reference=reference)

    catalog = await installer.install_skill(
        SkillCatalog(),
        raw,
        references={reference[0]: reference[1]},
        signature=b"s" * 64,
        verifier=_Allow(),
        now=_NOW,
    )

    persisted = store.records[0]
    decoded = decode_skill_bundle(persisted.artifact)
    assert catalog.get("example.skill").references[0].content == reference[1]
    assert decoded.raw_markdown == raw
    assert dict(decoded.references) == {reference[0]: reference[1]}
    assert persisted.content_sha256 == hashlib.sha256(persisted.artifact).hexdigest()


async def test_governed_bundle_install_persists_raw_disabled_artifact() -> None:
    store = _Store()
    installer = TrustedArtifactInstaller(store=store)
    raw = _governed_bundle()

    catalog = await installer.install_skill_bundle(
        SkillBundleCatalog(),
        raw,
        signature=b"b" * 64,
        verifier=_Allow(),
        now=_NOW,
    )

    assert catalog.get("example.pack").enabled is False
    assert store.records[0].kind is TrustedArtifactKind.SKILL_BUNDLE
    assert store.records[0].state is TrustedArtifactState.DISABLED
    assert store.records[0].artifact == raw
    assert store.records[0].content_sha256 == hashlib.sha256(raw).hexdigest()


async def test_governed_bundle_persistence_failure_does_not_return_candidate() -> None:
    installer = TrustedArtifactInstaller(store=_Store(fail=True))

    with pytest.raises(TrustedArtifactConflictError):
        await installer.install_skill_bundle(
            SkillBundleCatalog(),
            _governed_bundle(),
            signature=b"b" * 64,
            verifier=_Allow(),
            now=_NOW,
        )


def _governed_bundle() -> bytes:
    return encode_skill_bundle_manifest(
        {
            "name": "example.pack",
            "version": "1.0.0",
            "description": "Reviewed example procedures.",
            "source": "publisher.example",
            "members": [{"name": "example.skill", "version": "==1.0.0"}],
            "allowed_agents": ["Bragi"],
            "required_tools": [],
            "instruction": None,
        }
    )


async def test_extension_persistence_failure_does_not_return_candidate() -> None:
    store = _Store(fail=True)
    installer = TrustedArtifactInstaller(store=store)
    archive = b"archive"
    package = ExtensionPackage(
        manifest=ExtensionManifest(
            extension_id="example.extension",
            version="1.0.0",
            source="publisher.example",
            archive_sha256=hashlib.sha256(archive).hexdigest(),
            min_host_version="1.0.0",
        ),
        bundle=CapabilityBundle(capabilities=(), bindings=()),
    )
    manager = ExtensionManager(
        host_version="1.0.0",
        references=CapabilityReferences(),
    )

    with pytest.raises(TrustedArtifactConflictError):
        await installer.install_extension(
            manager,
            package,
            archive=archive,
            signature=b"s" * 64,
            verifier=_Allow(),
            now=_NOW,
        )

    assert manager.list() == ()
