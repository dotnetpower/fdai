"""Resolve the canonical ontology release digest for the OI-16 campaign.

The lifecycle repository derives ``ObservationCheckpoint.ontology_release_digest``
from the persisted ``inventory-ontology:manifest`` projection record, and the only
writer of that record is the inventory synchronization job, which builds it from
``load_ontology_catalog(...).build_release().digest``. Any other value - a digest
of a source archive, for example - is unrelated to that identity, so binding one
would strand schema replay in a permanently unavailable state while still looking
like a well-formed release digest in the receipt.

This module therefore rebuilds the same canonical catalog release the production
job builds, over the same shipped asset root, and treats a caller-supplied digest
as an assertion to verify rather than as the authority. It also exposes a bounded
read-only lookup of the persisted projection record so a protected finalization
can refuse to bind a release identity the deployed projection contradicts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from fdai.delivery.operational_history_certification_campaign import DIGEST_PATTERN
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.runtime.inventory_ontology import INVENTORY_ONTOLOGY_MANIFEST_KEY
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_LOGGER = logging.getLogger(__name__)

RELEASE_VERIFIED = "catalog_verified"
"""The source-built catalog release resolved and no assertion contradicts it."""

RELEASE_CONFLICTED = "catalog_conflicted"
"""A caller asserted a release digest that the source-built catalog refutes."""

RELEASE_UNVERIFIED = "catalog_unavailable"
"""The canonical catalog release could not be rebuilt in this runtime."""

PROJECTION_MATCHED = "projection_matched"
PROJECTION_CONFLICTED = "projection_conflicted"
PROJECTION_UNAVAILABLE = "projection_unavailable"

_CATALOG_ERRORS = (FileNotFoundError, NotADirectoryError, OSError, KeyError, ValueError)


class ReleaseDigestUnavailableError(RuntimeError):
    """The canonical catalog release digest could not be rebuilt."""


class ProjectionStateReader(Protocol):
    """The bounded read-only ``StateStore`` surface this module depends on."""

    async def read_state(self, key: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class ReleaseResolution:
    """The release identity a campaign phase binds, plus how it was established."""

    digest: str
    """The authoritative digest to bind. Canonical whenever one could be built."""

    assertion: str
    """``catalog_verified``, ``catalog_conflicted``, or ``catalog_unavailable``."""

    canonical: str | None = None
    """The source-built catalog release digest, when it could be rebuilt."""

    supplied: str | None = None
    """The caller-asserted digest, kept only so a conflict stays explainable."""

    def __post_init__(self) -> None:
        if DIGEST_PATTERN.fullmatch(self.digest) is None:
            raise ValueError("release resolution digest MUST be a sha256 digest")

    @property
    def verified(self) -> bool:
        """Return whether the bound digest is the canonical catalog release."""

        return self.assertion == RELEASE_VERIFIED


def canonical_ontology_release_digest(*, root: Path | None = None) -> str:
    """Return the catalog release digest the inventory projection publishes.

    This mirrors the production inventory synchronization path exactly: the
    shipped asset root, the packaged schema registry, and the probes overlay.
    """

    try:
        catalog_root = (repo_asset_root() if root is None else root) / "rule-catalog"
        catalog = load_ontology_catalog(
            catalog_root,
            schema_registry=PackageResourceSchemaRegistry(),
            probes_root=catalog_root / "probes",
        )
        digest = catalog.build_release().digest
    except _CATALOG_ERRORS as exc:  # pragma: no cover - environment dependent
        raise ReleaseDigestUnavailableError(
            "canonical ontology catalog release is unavailable"
        ) from exc
    if DIGEST_PATTERN.fullmatch(digest) is None:  # pragma: no cover - defensive
        raise ReleaseDigestUnavailableError("catalog release digest is not a sha256 digest")
    return digest


def resolve_release_digest(
    supplied: str | None, *, canonical: str | None = None
) -> ReleaseResolution:
    """Bind the canonical catalog release and grade any caller assertion.

    A supplied digest never overrides the catalog. When the catalog cannot be
    rebuilt the supplied digest is bound so the phase still produces evidence,
    but the resolution stays unverified so no protected receipt can claim it.
    """

    asserted = (supplied or "").strip() or None
    if asserted is not None and DIGEST_PATTERN.fullmatch(asserted) is None:
        raise ValueError("asserted ontology release digest MUST be a sha256 digest")
    if canonical is None:
        if asserted is None:
            raise ValueError("campaign requires a resolvable ontology release digest")
        _LOGGER.error("campaign could not rebuild the canonical ontology catalog release")
        return ReleaseResolution(digest=asserted, assertion=RELEASE_UNVERIFIED, supplied=asserted)
    if asserted is not None and asserted != canonical:
        _LOGGER.error("asserted ontology release digest is refuted by the source catalog")
        return ReleaseResolution(
            digest=canonical,
            assertion=RELEASE_CONFLICTED,
            canonical=canonical,
            supplied=asserted,
        )
    return ReleaseResolution(
        digest=canonical, assertion=RELEASE_VERIFIED, canonical=canonical, supplied=asserted
    )


def resolved_release(supplied: str | None, *, root: Path | None = None) -> ReleaseResolution:
    """Rebuild the canonical catalog release and grade ``supplied`` against it."""

    try:
        canonical: str | None = canonical_ontology_release_digest(root=root)
    except ReleaseDigestUnavailableError:
        canonical = None
    return resolve_release_digest(supplied, canonical=canonical)


async def projected_release_digest(store: ProjectionStateReader) -> str | None:
    """Return the release digest the persisted projection manifest carries.

    ``None`` means the deployed database has no projection record to compare, or
    carries one without a well-formed release digest. This is a bounded
    read-only lookup through the existing state adapter; it never writes.
    """

    record = await store.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
    if record is None:
        return None
    digest = str(record.get("ontology_release_digest", ""))
    return digest if DIGEST_PATTERN.fullmatch(digest) is not None else None


def projection_state(bound: str, projected: str | None) -> str:
    """Grade the persisted projection release against the bound release."""

    if projected is None:
        return PROJECTION_UNAVAILABLE
    return PROJECTION_MATCHED if projected == bound else PROJECTION_CONFLICTED


def release_blockers(assertion: str, projection: str) -> tuple[str, ...]:
    """Return every sorted reason a release identity blocks a protected receipt.

    An unverifiable projection is not a blocker on its own: a synthetic database
    that never ran the inventory projector simply has nothing to compare, and the
    replay scenarios already report that missing projection as unavailable.
    """

    reasons: set[str] = set()
    if assertion == RELEASE_CONFLICTED:
        reasons.add("ontology_release_digest_conflicted")
    elif assertion == RELEASE_UNVERIFIED:
        reasons.add("ontology_release_digest_unverified")
    if projection == PROJECTION_CONFLICTED:
        reasons.add("ontology_release_projection_conflicted")
    return tuple(sorted(reasons))


__all__ = [
    "PROJECTION_CONFLICTED",
    "PROJECTION_MATCHED",
    "PROJECTION_UNAVAILABLE",
    "RELEASE_CONFLICTED",
    "RELEASE_UNVERIFIED",
    "RELEASE_VERIFIED",
    "ProjectionStateReader",
    "ReleaseDigestUnavailableError",
    "ReleaseResolution",
    "canonical_ontology_release_digest",
    "projected_release_digest",
    "projection_state",
    "release_blockers",
    "resolve_release_digest",
    "resolved_release",
]
