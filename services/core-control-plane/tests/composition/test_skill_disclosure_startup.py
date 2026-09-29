"""Production composition tests for trusted skill disclosure startup."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.composition.wire_skill_disclosure import publish_trusted_skill_disclosure_snapshots
from fdai.core.skills import (
    RuntimeSkill,
    RuntimeSkillBundle,
    RuntimeSkillDisclosure,
    SkillBundleCatalog,
    SkillCatalog,
    encode_skill_bundle_manifest,
    skill_body_digest,
)
from fdai.core.supply_chain import (
    TrustedArtifactConflictError,
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
    TrustedSkillBundleLoadError,
)

_NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)


class _SkillVerifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return skill.raw_markdown == raw_markdown


class _BundleVerifier:
    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        return bundle.raw_manifest == raw_manifest


class _SkillVerifierFactory:
    def __call__(self, record: TrustedArtifactRecord, /) -> _SkillVerifier:
        if record.signature != b"s" * 64:
            raise ValueError("skill signature is not trusted")
        return _SkillVerifier()


class _BundleVerifierFactory:
    def __call__(self, record: TrustedArtifactRecord, /) -> _BundleVerifier:
        if record.signature != b"b" * 64:
            raise ValueError("bundle signature is not trusted")
        return _BundleVerifier()


class _Store:
    def __init__(self, *records: TrustedArtifactRecord) -> None:
        self._records = records
        self.requests: list[TrustedArtifactKind] = []

    async def put(
        self,
        record: TrustedArtifactRecord,
        *,
        expected_revision: int,
    ) -> TrustedArtifactRecord:
        del record, expected_revision
        raise TrustedArtifactConflictError("test store is read-only")

    async def get(
        self,
        kind: TrustedArtifactKind,
        artifact_id: str,
    ) -> TrustedArtifactRecord | None:
        for record in self._records:
            if record.kind is kind and record.artifact_id == artifact_id:
                return record
        return None

    async def list(self, kind: TrustedArtifactKind) -> tuple[TrustedArtifactRecord, ...]:
        self.requests.append(kind)
        return tuple(record for record in self._records if record.kind is kind)


def _skill_markdown() -> bytes:
    body = "Collect inventory evidence."
    return f"""---
name: inventory-evidence
version: 1.0.0
description: Inventory evidence.
source: publisher.example
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
---
{body}
""".encode()


def _skill_record() -> TrustedArtifactRecord:
    raw = _skill_markdown()
    return TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL,
        artifact_id="inventory-evidence",
        version="1.0.0",
        source="publisher.example",
        content_sha256=hashlib.sha256(raw).hexdigest(),
        artifact=raw,
        signature=b"s" * 64,
        state=TrustedArtifactState.ENABLED,
        revision=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _bundle_record() -> TrustedArtifactRecord:
    raw = encode_skill_bundle_manifest(
        {
            "name": "incident-evidence-pack",
            "version": "1.0.0",
            "description": "Reviewed incident evidence procedure.",
            "source": "publisher.example",
            "members": [{"name": "inventory-evidence", "version": "==1.0.0"}],
            "allowed_agents": ["Bragi"],
            "required_tools": ["query_inventory"],
            "instruction": "Use the member exactly once.",
        }
    )
    return TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL_BUNDLE,
        artifact_id="incident-evidence-pack",
        version="1.0.0",
        source="publisher.example",
        content_sha256=hashlib.sha256(raw).hexdigest(),
        artifact=raw,
        signature=b"b" * 64,
        state=TrustedArtifactState.ENABLED,
        revision=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _disclosure() -> RuntimeSkillDisclosure:
    return RuntimeSkillDisclosure(
        catalog=SkillCatalog(),
        verifier=_SkillVerifier(),
        agent="Bragi",
        available_tools=frozenset({"query_inventory"}),
        bundle_catalog=SkillBundleCatalog(),
        bundle_verifier=_BundleVerifier(),
        known_agents=frozenset({"Bragi"}),
    )


async def test_startup_reconstructs_skills_before_bundles_and_publishes_before_ready() -> None:
    store = _Store(_bundle_record(), _skill_record())
    disclosure = _disclosure()

    readiness = await publish_trusted_skill_disclosure_snapshots(
        disclosure,
        store=store,
        skill_verifier_factory=_SkillVerifierFactory(),
        bundle_verifier_factory=_BundleVerifierFactory(),
        skill_verifier=_SkillVerifier(),
        bundle_verifier=_BundleVerifier(),
        available_tools=frozenset({"query_inventory"}),
        known_agents=frozenset({"Bragi"}),
    )

    assert store.requests == [TrustedArtifactKind.SKILL, TrustedArtifactKind.SKILL_BUNDLE]
    assert readiness.ready is True
    assert readiness.enabled_skill_count == 1
    assert readiness.enabled_bundle_count == 1
    inspection = disclosure.inspect()
    assert inspection["eligible_count"] == 1
    assert inspection["eligible_bundle_count"] == 1
    assert disclosure.load_bundle("incident-evidence-pack")["name"] == "incident-evidence-pack"


async def test_tampered_bundle_record_fails_closed_before_snapshot_publication() -> None:
    tampered = replace(_bundle_record(), content_sha256="0" * 64)
    disclosure = _disclosure()

    with pytest.raises(TrustedSkillBundleLoadError, match="digest"):
        await publish_trusted_skill_disclosure_snapshots(
            disclosure,
            store=_Store(_skill_record(), tampered),
            skill_verifier_factory=_SkillVerifierFactory(),
            bundle_verifier_factory=_BundleVerifierFactory(),
            skill_verifier=_SkillVerifier(),
            bundle_verifier=_BundleVerifier(),
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )

    inspection = disclosure.inspect()
    assert inspection["installed_count"] == 0
    assert inspection["installed_bundle_count"] == 0
