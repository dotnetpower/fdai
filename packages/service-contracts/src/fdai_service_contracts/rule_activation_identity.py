"""Dormant version 2 identities separating catalog provenance from active membership."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.executor_models import ContractBase, Digest
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef

_SEMVER_PATTERN = r"^[0-9]+[.][0-9]+[.][0-9]+$"


class RuleRevisionCatalogManifest(ContractBase):
    """Complete retained revision index used only as proposal provenance."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    revisions: Annotated[
        tuple[RuleRevisionIdentityRef, ...], Field(min_length=1, max_length=50_000)
    ]
    manifest_digest: Digest

    @model_validator(mode="after")
    def _canonical_manifest(self) -> Self:
        keys = tuple((item.rule_id, item.rule_version) for item in self.revisions)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("Rule revision catalog manifest entries MUST be unique and sorted")
        expected = rule_revision_catalog_manifest_digest(self.revisions)
        if self.manifest_digest != expected:
            raise ValueError("Rule revision catalog manifest digest mismatch")
        return self


class RuleProfileSnapshotV2(ContractBase):
    """Resolved active member snapshot; every revision change bumps profile_version."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    profile_id: Annotated[str, Field(min_length=1, max_length=128)]
    profile_version: Annotated[str, Field(pattern=_SEMVER_PATTERN)]
    members: Annotated[tuple[RuleRevisionIdentityRef, ...], Field(min_length=1, max_length=10_000)]
    snapshot_digest: Digest

    @field_validator("profile_id", "profile_version", mode="before")
    @classmethod
    def _exact_text(cls, value: object) -> object:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("Rule profile snapshot identity MUST be exact")
        return value

    @model_validator(mode="after")
    def _canonical_snapshot(self) -> Self:
        keys = tuple((item.rule_id, item.rule_version) for item in self.members)
        rule_ids = tuple(item.rule_id for item in self.members)
        if (
            keys != tuple(sorted(keys))
            or len(set(keys)) != len(keys)
            or len(set(rule_ids)) != len(rule_ids)
        ):
            raise ValueError(
                "Rule profile snapshot members MUST have unique Rule ids and be sorted"
            )
        expected = rule_profile_snapshot_digest(
            profile_id=self.profile_id,
            profile_version=self.profile_version,
            members=self.members,
        )
        if self.snapshot_digest != expected:
            raise ValueError("Rule profile snapshot digest mismatch")
        return self


class RuleActivationGenerationIdentityV2(ContractBase):
    """Authority-neutral target identity independent from the full catalog manifest."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    generation_id: Annotated[str, Field(pattern=r"^rule-activation-v2-[a-f0-9]{32}$")]
    generation_digest: Digest
    profile_snapshot_digest: Digest
    members: Annotated[tuple[RuleRevisionIdentityRef, ...], Field(min_length=1, max_length=10_000)]

    @model_validator(mode="after")
    def _canonical_generation(self) -> Self:
        keys = tuple((item.rule_id, item.rule_version) for item in self.members)
        rule_ids = tuple(item.rule_id for item in self.members)
        if (
            keys != tuple(sorted(keys))
            or len(set(keys)) != len(keys)
            or len(set(rule_ids)) != len(rule_ids)
        ):
            raise ValueError("Rule generation v2 members MUST have unique Rule ids and be sorted")
        expected = rule_activation_generation_v2_digest(
            profile_snapshot_digest=self.profile_snapshot_digest,
            members=self.members,
        )
        if self.generation_digest != expected:
            raise ValueError("Rule generation v2 digest mismatch")
        if self.generation_id != f"rule-activation-v2-{expected.removeprefix('sha256:')[:32]}":
            raise ValueError("Rule generation v2 id mismatch")
        return self


class RuleActivationIdentityContextV2(ContractBase):
    """Proposal precondition joining separate catalog and active identities."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    catalog_manifest: RuleRevisionCatalogManifest
    profile_snapshot: RuleProfileSnapshotV2
    generation: RuleActivationGenerationIdentityV2

    @model_validator(mode="after")
    def _members_exist_in_catalog(self) -> Self:
        catalog = {
            (item.rule_id, item.rule_version): item.revision_digest
            for item in self.catalog_manifest.revisions
        }
        for member in self.profile_snapshot.members:
            if catalog.get((member.rule_id, member.rule_version)) != member.revision_digest:
                raise ValueError("Rule profile member is absent from the catalog manifest")
        if (
            self.generation.profile_snapshot_digest != self.profile_snapshot.snapshot_digest
            or self.generation.members != self.profile_snapshot.members
        ):
            raise ValueError("Rule generation v2 does not match the profile snapshot")
        return self


class RuleActivationIdentityTransitionV2(ContractBase):
    """Dormant proposal precondition across separate catalog and active identities."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    source: RuleActivationIdentityContextV2
    target: RuleActivationIdentityContextV2
    transition_digest: Digest

    @model_validator(mode="after")
    def _valid_transition(self) -> Self:
        source_catalog = {
            (item.rule_id, item.rule_version): item.revision_digest
            for item in self.source.catalog_manifest.revisions
        }
        target_catalog = {
            (item.rule_id, item.rule_version): item.revision_digest
            for item in self.target.catalog_manifest.revisions
        }
        if any(target_catalog.get(key) != digest for key, digest in source_catalog.items()):
            raise ValueError("Rule identity transition MUST retain every source catalog revision")
        members_changed = (
            self.source.profile_snapshot.members != self.target.profile_snapshot.members
        )
        if (
            members_changed
            and self.source.profile_snapshot.profile_id == self.target.profile_snapshot.profile_id
            and self.source.profile_snapshot.profile_version
            == self.target.profile_snapshot.profile_version
        ):
            raise ValueError("Rule revision change MUST bump the profile version")
        if (
            members_changed
            and self.source.profile_snapshot.profile_id == self.target.profile_snapshot.profile_id
            and _semver(self.target.profile_snapshot.profile_version)
            <= _semver(self.source.profile_snapshot.profile_version)
        ):
            raise ValueError("Rule revision change MUST increase the profile version")
        profile_unchanged = (
            self.source.profile_snapshot.profile_id == self.target.profile_snapshot.profile_id
            and self.source.profile_snapshot.profile_version
            == self.target.profile_snapshot.profile_version
            and not members_changed
        )
        if profile_unchanged and (
            self.source.generation.generation_digest != self.target.generation.generation_digest
        ):
            raise ValueError("catalog-only transition MUST preserve active generation identity")
        expected = rule_activation_identity_transition_digest(
            source=self.source,
            target=self.target,
        )
        if self.transition_digest != expected:
            raise ValueError("Rule identity transition digest mismatch")
        return self


def build_rule_activation_identity_context_v2(
    *,
    catalog_revisions: tuple[RuleRevisionIdentityRef, ...],
    profile_id: str,
    profile_version: str,
    active_members: tuple[RuleRevisionIdentityRef, ...],
) -> RuleActivationIdentityContextV2:
    """Build one deterministic dormant v2 identity context."""

    catalog = RuleRevisionCatalogManifest(
        revisions=catalog_revisions,
        manifest_digest=rule_revision_catalog_manifest_digest(catalog_revisions),
    )
    profile = RuleProfileSnapshotV2(
        profile_id=profile_id,
        profile_version=profile_version,
        members=active_members,
        snapshot_digest=rule_profile_snapshot_digest(
            profile_id=profile_id,
            profile_version=profile_version,
            members=active_members,
        ),
    )
    generation_digest = rule_activation_generation_v2_digest(
        profile_snapshot_digest=profile.snapshot_digest,
        members=active_members,
    )
    generation = RuleActivationGenerationIdentityV2(
        generation_id=(f"rule-activation-v2-{generation_digest.removeprefix('sha256:')[:32]}"),
        generation_digest=generation_digest,
        profile_snapshot_digest=profile.snapshot_digest,
        members=active_members,
    )
    return RuleActivationIdentityContextV2(
        catalog_manifest=catalog,
        profile_snapshot=profile,
        generation=generation,
    )


def build_rule_activation_identity_transition_v2(
    *,
    source: RuleActivationIdentityContextV2,
    target: RuleActivationIdentityContextV2,
) -> RuleActivationIdentityTransitionV2:
    """Build and validate one dormant revision transition precondition."""

    return RuleActivationIdentityTransitionV2(
        source=source,
        target=target,
        transition_digest=rule_activation_identity_transition_digest(
            source=source,
            target=target,
        ),
    )


def rule_revision_catalog_manifest_digest(
    revisions: tuple[RuleRevisionIdentityRef, ...],
) -> str:
    return canonical_digest([revision.model_dump(mode="json") for revision in revisions])


def rule_profile_snapshot_digest(
    *,
    profile_id: str,
    profile_version: str,
    members: tuple[RuleRevisionIdentityRef, ...],
) -> str:
    return canonical_digest(
        {
            "profile_id": profile_id,
            "profile_version": profile_version,
            "members": [member.model_dump(mode="json") for member in members],
        }
    )


def rule_activation_generation_v2_digest(
    *,
    profile_snapshot_digest: str,
    members: tuple[RuleRevisionIdentityRef, ...],
) -> str:
    return canonical_digest(
        {
            "profile_snapshot_digest": profile_snapshot_digest,
            "members": [member.model_dump(mode="json") for member in members],
        }
    )


def rule_activation_identity_transition_digest(
    *,
    source: RuleActivationIdentityContextV2,
    target: RuleActivationIdentityContextV2,
) -> str:
    return canonical_digest(
        {
            "source_catalog_manifest_digest": source.catalog_manifest.manifest_digest,
            "target_catalog_manifest_digest": target.catalog_manifest.manifest_digest,
            "source_profile_snapshot_digest": source.profile_snapshot.snapshot_digest,
            "target_profile_snapshot_digest": target.profile_snapshot.snapshot_digest,
            "source_generation_digest": source.generation.generation_digest,
            "target_generation_digest": target.generation.generation_digest,
        }
    )


def _semver(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return (int(major), int(minor), int(patch))


__all__ = [
    "RuleActivationGenerationIdentityV2",
    "RuleActivationIdentityContextV2",
    "RuleActivationIdentityTransitionV2",
    "RuleProfileSnapshotV2",
    "RuleRevisionCatalogManifest",
    "build_rule_activation_identity_context_v2",
    "build_rule_activation_identity_transition_v2",
    "rule_activation_generation_v2_digest",
    "rule_activation_identity_transition_digest",
    "rule_profile_snapshot_digest",
    "rule_revision_catalog_manifest_digest",
]
