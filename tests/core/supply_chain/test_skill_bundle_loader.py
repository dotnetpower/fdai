"""Fail-closed durable governed skill bundle restart tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from fdai.core.skills import (
    RuntimeSkill,
    RuntimeSkillBundle,
    SkillCatalog,
    encode_skill_bundle_manifest,
    skill_body_digest,
)
from fdai.core.supply_chain import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
    TrustedSkillBundleLoadError,
    load_skill_bundle_catalog,
)

_NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)


class _SkillVerifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


class _BundleVerifier:
    def __init__(self, *, trusted: bool = True) -> None:
        self.trusted = trusted

    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        return self.trusted and bundle.raw_manifest == raw_manifest


class _Factory:
    def __init__(self, *, trusted: bool = True) -> None:
        self.trusted = trusted
        self.seen: list[str] = []

    def __call__(self, record: TrustedArtifactRecord, /) -> _BundleVerifier:
        self.seen.append(record.artifact_id)
        return _BundleVerifier(trusted=self.trusted and record.signature == b"b" * 64)


def _skills(*, version: str = "1.0.0") -> SkillCatalog:
    body = "Complete inventory procedure."
    raw = f"""---
name: inventory-evidence
version: {version}
description: Inventory evidence.
source: publisher.example
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
---
{body}
""".encode()
    return (
        SkillCatalog()
        .install(raw, verifier=_SkillVerifier())
        .enable(
            "inventory-evidence",
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    )


def _record(
    *,
    name: str = "inventory-pack",
    state: TrustedArtifactState = TrustedArtifactState.ENABLED,
) -> TrustedArtifactRecord:
    raw = encode_skill_bundle_manifest(
        {
            "name": name,
            "version": "1.0.0",
            "description": "Reviewed inventory procedure.",
            "source": "publisher.example",
            "members": [{"name": "inventory-evidence", "version": "==1.0.0"}],
            "allowed_agents": ["Bragi"],
            "required_tools": ["query_inventory"],
            "instruction": None,
        }
    )
    return TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL_BUNDLE,
        artifact_id=name,
        version="1.0.0",
        source="publisher.example",
        content_sha256=hashlib.sha256(raw).hexdigest(),
        artifact=raw,
        signature=b"b" * 64,
        state=state,
        revision=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_restart_restores_enabled_bundle_and_deterministic_order() -> None:
    alpha = _record(name="alpha-pack", state=TrustedArtifactState.DISABLED)
    zeta = _record(name="zeta-pack")
    factory = _Factory()

    catalog = load_skill_bundle_catalog(
        [zeta, alpha],
        factory,
        skills=_skills(),
        skill_verifier=_SkillVerifier(),
        available_tools=frozenset({"query_inventory"}),
        known_agents=frozenset({"Bragi"}),
    )

    assert factory.seen == ["alpha-pack", "zeta-pack"]
    assert [bundle.manifest.name for bundle in catalog.list()] == ["alpha-pack", "zeta-pack"]
    assert catalog.get("alpha-pack").enabled is False
    assert catalog.get("zeta-pack").enabled is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("content_sha256", "0" * 64, "digest"),
        ("artifact_id", "other-pack", "identity"),
        ("version", "2.0.0", "identity"),
        ("source", "other.publisher", "identity"),
    ],
)
def test_restart_rejects_record_digest_or_identity_mismatch(
    field: str,
    value: str,
    message: str,
) -> None:
    record = _record()
    if field == "content_sha256":
        changed = replace(record, content_sha256=value)
    elif field == "artifact_id":
        changed = replace(record, artifact_id=value)
    elif field == "version":
        changed = replace(record, version=value)
    else:
        changed = replace(record, source=value)
    with pytest.raises(TrustedSkillBundleLoadError, match=message):
        load_skill_bundle_catalog(
            [changed],
            _Factory(),
            skills=_skills(),
            skill_verifier=_SkillVerifier(),
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )


def test_restart_rejects_wrong_kind_duplicate_untrusted_and_updated_member() -> None:
    record = _record()
    with pytest.raises(TrustedSkillBundleLoadError, match="non-bundle"):
        load_skill_bundle_catalog(
            [replace(record, kind=TrustedArtifactKind.SKILL)],
            _Factory(),
            skills=_skills(),
            skill_verifier=_SkillVerifier(),
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    with pytest.raises(TrustedSkillBundleLoadError, match="duplicate"):
        load_skill_bundle_catalog(
            [record, record],
            _Factory(),
            skills=_skills(),
            skill_verifier=_SkillVerifier(),
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    with pytest.raises(ValueError, match="trust"):
        load_skill_bundle_catalog(
            [record],
            _Factory(trusted=False),
            skills=_skills(),
            skill_verifier=_SkillVerifier(),
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    with pytest.raises(ValueError, match="version"):
        load_skill_bundle_catalog(
            [record],
            _Factory(),
            skills=_skills(version="1.1.0"),
            skill_verifier=_SkillVerifier(),
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
