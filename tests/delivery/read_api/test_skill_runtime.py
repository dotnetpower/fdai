"""Production runtime skill startup composition tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fdai.core.skills import (
    encode_skill_bundle_manifest,
    parse_skill_bundle_manifest,
    parse_skill_markdown,
    skill_body_digest,
)
from fdai.core.supply_chain import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
)
from fdai.delivery.read_api.production.skills import (
    TRUSTED_SKILL_PUBLISHERS_PATH_ENV,
    build_production_skill_runtime,
)
from fdai.delivery.trust import skill_bundle_signature_payload, skill_signature_payload

_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


class _Store:
    def __init__(self, records: tuple[TrustedArtifactRecord, ...]) -> None:
        self._records = records

    async def list(self, kind: TrustedArtifactKind) -> tuple[TrustedArtifactRecord, ...]:
        return tuple(record for record in self._records if record.kind is kind)

    async def get(
        self,
        kind: TrustedArtifactKind,
        artifact_id: str,
    ) -> TrustedArtifactRecord | None:
        del kind, artifact_id
        return None

    async def put(
        self,
        record: TrustedArtifactRecord,
        *,
        expected_revision: int,
    ) -> TrustedArtifactRecord:
        del record, expected_revision
        raise AssertionError("startup skill wiring MUST NOT write trusted artifacts")


def _signed_records() -> tuple[TrustedArtifactRecord, TrustedArtifactRecord, bytes]:
    body = "Complete inventory procedure."
    raw = f"""---
name: inventory-evidence
version: 1.0.0
description: Collect inventory evidence.
source: publisher.example
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
---
{body}
""".encode()
    skill = parse_skill_markdown(raw)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    skill_record = TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL,
        artifact_id=skill.manifest.name,
        version=skill.manifest.version,
        source=skill.manifest.source,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        artifact=raw,
        signature=private.sign(skill_signature_payload(skill, raw)),
        state=TrustedArtifactState.ENABLED,
        revision=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    raw_bundle = encode_skill_bundle_manifest(
        {
            "name": "inventory-pack",
            "version": "1.0.0",
            "description": "Reviewed inventory procedure.",
            "source": "publisher.example",
            "members": [{"name": "inventory-evidence", "version": "==1.0.0"}],
            "allowed_agents": ["Bragi"],
            "required_tools": ["query_inventory"],
            "instruction": "Use complete inventory evidence.",
        }
    )
    bundle = parse_skill_bundle_manifest(raw_bundle)
    bundle_record = TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL_BUNDLE,
        artifact_id=bundle.manifest.name,
        version=bundle.manifest.version,
        source=bundle.manifest.source,
        content_sha256=hashlib.sha256(raw_bundle).hexdigest(),
        artifact=raw_bundle,
        signature=private.sign(skill_bundle_signature_payload(bundle)),
        state=TrustedArtifactState.ENABLED,
        revision=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return skill_record, bundle_record, public


async def test_startup_loads_signed_skill_and_bundle_into_shared_disclosure(
    tmp_path: Path,
) -> None:
    record, bundle_record, public = _signed_records()
    publishers = tmp_path / "skill-publishers.json"
    publishers.write_text(
        json.dumps({record.source: public.decode("utf-8")}),
        encoding="utf-8",
    )
    runtime = build_production_skill_runtime(
        env={TRUSTED_SKILL_PUBLISHERS_PATH_ENV: str(publishers)},
        dsn="postgresql://example",
        statement_timeout_ms=1,
        connect_timeout_s=1,
        store=_Store((record, bundle_record)),
    )

    await runtime.startup()
    inspection = await runtime.panel.render(params={})
    loaded = runtime.disclosure.load("inventory-evidence")
    loaded_bundle = runtime.disclosure.load_bundle("inventory-pack")

    assert inspection["installed_count"] == 1
    assert inspection["eligible_count"] == 1
    assert inspection["installed_bundle_count"] == 1
    assert inspection["eligible_bundle_count"] == 1
    assert loaded["body"] == "Complete inventory procedure.\n"
    assert loaded_bundle["members"][0]["body"] == "Complete inventory procedure.\n"
    assert runtime.disclosure.inspect()["diagnostics"][-1]["status"] == "selected"


async def test_startup_fails_closed_when_durable_skill_has_no_trusted_key() -> None:
    record, bundle_record, _public = _signed_records()
    runtime = build_production_skill_runtime(
        env={},
        dsn="postgresql://example",
        statement_timeout_ms=1,
        connect_timeout_s=1,
        store=_Store((record, bundle_record)),
    )

    with pytest.raises(ValueError, match="trust"):
        await runtime.startup()
    assert runtime.disclosure.inspect()["installed_count"] == 0
