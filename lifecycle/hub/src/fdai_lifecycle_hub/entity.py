"""Entities: ownership evidence, settings revisions, and the managed rule."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from fdai_deployment_cli.contracts import canonical_digest

_PREFIXED_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


class OwnershipGap(StrEnum):
    """Why ownership evidence doesn't prove that FDAI owns an Entity."""

    TAG_ONLY = "ownership_tag_only"
    UNPROVEN = "ownership_unproven"


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnershipEvidence:
    """Digests of what proves FDAI ownership, as the installation reports them.

    A signed Foundation creation receipt together with a Terraform state identity proves
    ownership. The `fdai:managed=true` tag is only a discovery hint, because anyone with tag
    rights can set it.
    """

    foundation_receipt_digest: str | None = None
    terraform_state_digest: str | None = None
    managed_tag: bool = False

    def __post_init__(self) -> None:
        digests = (self.foundation_receipt_digest, self.terraform_state_digest)
        if not (self.managed_tag or any(digests)):
            raise ValueError("ownership evidence is empty")
        if any(d is not None and not _PREFIXED_SHA256.fullmatch(d) for d in digests):
            raise ValueError("an ownership digest must be sha256: followed by 64 hex characters")

    @property
    def gap(self) -> OwnershipGap | None:
        if self.foundation_receipt_digest and self.terraform_state_digest:
            return None
        if self.foundation_receipt_digest or self.terraform_state_digest:
            return OwnershipGap.UNPROVEN
        return OwnershipGap.TAG_ONLY


@dataclass(frozen=True, slots=True, kw_only=True)
class EntitySettings:
    """One revision of an Entity's override blocks, addressed by the digest of its content."""

    overrides: tuple[Mapping[str, object], ...]

    @property
    def digest(self) -> str:
        return canonical_digest({"overrides": self.overrides})


@dataclass(frozen=True, slots=True, kw_only=True)
class Entity:
    """One deployable unit of an installation.

    As in Apollo, an Entity with settings is managed and one without is unmanaged. Only managed
    entities receive Plans, and only an Entity with proven ownership can have settings.
    """

    entity_id: str
    kind: str
    ownership: OwnershipEvidence | None = None
    # Override blocks hold dicts, so an Entity hashes by identity and ownership only.
    settings: EntitySettings | None = field(default=None, hash=False)

    def __post_init__(self) -> None:
        if self.settings is not None and self.ownership_gap is not None:
            raise ValueError(f"entity {self.entity_id!r} has settings without proven ownership")

    @property
    def ownership_gap(self) -> OwnershipGap | None:
        return OwnershipGap.UNPROVEN if self.ownership is None else self.ownership.gap

    @property
    def managed(self) -> bool:
        return self.settings is not None
