"""Fail-closed reconstruction of the runtime skill catalog from durable records."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Protocol

from fdai.core.skills import SkillCatalog, SkillTrustVerifier, parse_skill_markdown
from fdai.core.supply_chain.artifacts import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
)
from fdai.core.supply_chain.skill_bundle import decode_skill_bundle


class SkillTrustVerifierFactory(Protocol):
    """Create a record-bound verifier without exposing publisher keys to core."""

    def __call__(self, record: TrustedArtifactRecord, /) -> SkillTrustVerifier: ...


class TrustedSkillLoadError(ValueError):
    """A durable skill record cannot be trusted and startup must stop."""


def load_skill_catalog(
    records: Iterable[TrustedArtifactRecord],
    verifier_factory: SkillTrustVerifierFactory,
    available_tools: frozenset[str],
    known_agents: frozenset[str],
) -> SkillCatalog:
    """Rebuild a catalog in deterministic order and preserve durable enablement."""
    durable_records = tuple(records)
    non_skills = tuple(
        record.artifact_id
        for record in durable_records
        if record.kind is not TrustedArtifactKind.SKILL
    )
    if non_skills:
        raise TrustedSkillLoadError(
            f"skill restart received non-skill records: {sorted(non_skills)}"
        )
    invalid_states = tuple(
        record.artifact_id
        for record in durable_records
        if record.state is not TrustedArtifactState.DISABLED
        and record.state is not TrustedArtifactState.ENABLED
    )
    if invalid_states:
        raise TrustedSkillLoadError(
            f"skill restart records contain invalid durable states: {sorted(invalid_states)}"
        )
    artifact_ids = tuple(record.artifact_id for record in durable_records)
    if len(set(artifact_ids)) != len(artifact_ids):
        raise TrustedSkillLoadError("skill restart records contain duplicate artifact ids")

    catalog = SkillCatalog()
    for record in sorted(durable_records, key=lambda item: item.artifact_id):
        if hashlib.sha256(record.artifact).hexdigest() != record.content_sha256:
            raise TrustedSkillLoadError(
                f"trusted skill {record.artifact_id!r} content digest does not match stored bytes"
            )
        bundle = decode_skill_bundle(record.artifact)
        skill = parse_skill_markdown(bundle.raw_markdown)
        manifest = skill.manifest
        if (
            record.artifact_id != manifest.name
            or record.version != manifest.version
            or record.source != manifest.source
        ):
            raise TrustedSkillLoadError(
                f"trusted skill {record.artifact_id!r} record identity does not match its manifest"
            )
        catalog = catalog.install_bundle(
            bundle.raw_markdown,
            bundle.references,
            verifier=verifier_factory(record),
        )
        if record.state is TrustedArtifactState.ENABLED:
            catalog = catalog.enable(
                manifest.name,
                available_tools=available_tools,
                known_agents=known_agents,
            )
    return catalog


__all__ = [
    "SkillTrustVerifierFactory",
    "TrustedSkillLoadError",
    "load_skill_catalog",
]
