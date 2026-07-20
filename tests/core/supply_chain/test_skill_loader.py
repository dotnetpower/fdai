"""Fail-closed durable skill catalog restart tests."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

import pytest
import yaml

from fdai.core.skills import RuntimeSkill, SkillCatalogError, skill_body_digest
from fdai.core.supply_chain import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
    TrustedSkillLoadError,
    encode_skill_bundle,
    load_skill_catalog,
)

_NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)


class _Verifier:
    def __init__(self, trusted: bool) -> None:
        self._trusted = trusted

    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        del skill, raw_markdown
        return self._trusted


class _Factory:
    def __init__(self, *, trusted: bool = True) -> None:
        self._trusted = trusted
        self.seen: list[str] = []

    def __call__(self, record: TrustedArtifactRecord, /) -> _Verifier:
        self.seen.append(record.artifact_id)
        return _Verifier(self._trusted and record.signature == b"s" * 64)


def _skill(
    *,
    name: str = "example.skill",
    source: str = "publisher.example",
    required_tools: tuple[str, ...] = (),
    allowed_agents: tuple[str, ...] = (),
    references: tuple[tuple[str, bytes], ...] = (),
) -> bytes:
    body = f"Use {name} deterministically."
    manifest: dict[str, object] = {
        "name": name,
        "version": "1.0.0",
        "description": "Example",
        "source": source,
        "body_sha256": skill_body_digest(body),
        "required_tools": list(required_tools),
        "allowed_agents": list(allowed_agents),
    }
    if references:
        manifest["references"] = [
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "media_type": "text/plain",
            }
            for path, content in references
        ]
    return f"---\n{yaml.safe_dump(manifest, sort_keys=False)}---\n{body}\n".encode()


def _record(
    raw: bytes,
    *,
    references: Mapping[str, bytes] | None = None,
    state: TrustedArtifactState = TrustedArtifactState.DISABLED,
) -> TrustedArtifactRecord:
    reference_map = references or {}
    artifact = encode_skill_bundle(raw, reference_map) if reference_map else raw
    return TrustedArtifactRecord(
        kind=TrustedArtifactKind.SKILL,
        artifact_id="example.skill",
        version="1.0.0",
        source="publisher.example",
        content_sha256=hashlib.sha256(artifact).hexdigest(),
        artifact=artifact,
        signature=b"s" * 64,
        state=state,
        revision=1,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_legacy_single_file_reload_preserves_disabled_state() -> None:
    catalog = load_skill_catalog(
        [_record(_skill())],
        _Factory(),
        frozenset(),
        frozenset(),
    )

    skill = catalog.get("example.skill")
    assert skill.raw_markdown == _skill()
    assert skill.enabled is False


def test_reference_bundle_reload_restores_content_and_enabled_state() -> None:
    reference = ("references/guide.txt", b"bounded guide")
    raw = _skill(references=(reference,))
    record = _record(
        raw,
        references={reference[0]: reference[1]},
        state=TrustedArtifactState.ENABLED,
    )

    catalog = load_skill_catalog([record], _Factory(), frozenset(), frozenset())

    skill = catalog.get("example.skill")
    assert skill.enabled is True
    assert skill.references[0].manifest.path == reference[0]
    assert skill.references[0].content == reference[1]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content_sha256", "0" * 64),
        ("artifact_id", "other.skill"),
        ("version", "2.0.0"),
        ("source", "other.publisher"),
    ],
)
def test_content_hash_and_record_identity_mismatch_fail_closed(
    field: str,
    value: object,
) -> None:
    record = replace(_record(_skill()), **{field: value})

    with pytest.raises(TrustedSkillLoadError, match="digest|identity"):
        load_skill_catalog([record], _Factory(), frozenset(), frozenset())


def test_signature_or_publisher_trust_failure_stops_restart() -> None:
    with pytest.raises(SkillCatalogError, match="trust"):
        load_skill_catalog([_record(_skill())], _Factory(trusted=False), frozenset(), frozenset())


@pytest.mark.parametrize(
    ("required_tools", "allowed_agents", "message"),
    [
        (("inventory.read",), (), "unavailable tools"),
        ((), ("Bragi",), "unknown agents"),
    ],
)
def test_enabled_skill_missing_tool_or_agent_fails_closed(
    required_tools: tuple[str, ...],
    allowed_agents: tuple[str, ...],
    message: str,
) -> None:
    record = _record(
        _skill(required_tools=required_tools, allowed_agents=allowed_agents),
        state=TrustedArtifactState.ENABLED,
    )

    with pytest.raises(SkillCatalogError, match=message):
        load_skill_catalog([record], _Factory(), frozenset(), frozenset())


def test_duplicate_and_non_skill_records_fail_before_verifier_creation() -> None:
    record = _record(_skill())
    factory = _Factory()

    with pytest.raises(TrustedSkillLoadError, match="duplicate"):
        load_skill_catalog([record, record], factory, frozenset(), frozenset())
    with pytest.raises(TrustedSkillLoadError, match="non-skill"):
        load_skill_catalog(
            [replace(record, kind=TrustedArtifactKind.EXTENSION)],
            factory,
            frozenset(),
            frozenset(),
        )
    assert factory.seen == []


def test_invalid_runtime_state_fails_closed() -> None:
    record = replace(_record(_skill()), state="enabled")

    with pytest.raises(TrustedSkillLoadError, match="invalid durable states"):
        load_skill_catalog([record], _Factory(), frozenset(), frozenset())


def test_records_install_in_deterministic_artifact_id_order() -> None:
    first = _record(_skill(name="alpha.skill"))
    first = replace(first, artifact_id="alpha.skill")
    second = _record(_skill(name="zeta.skill"))
    second = replace(second, artifact_id="zeta.skill")
    factory = _Factory()

    catalog = load_skill_catalog([second, first], factory, frozenset(), frozenset())

    assert factory.seen == ["alpha.skill", "zeta.skill"]
    assert tuple(skill.manifest.name for skill in catalog.list()) == ("alpha.skill", "zeta.skill")
