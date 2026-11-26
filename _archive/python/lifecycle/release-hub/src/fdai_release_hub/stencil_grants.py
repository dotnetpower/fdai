"""Release Hub Stencil variant registry, distribution grants, scoped catalogs, and workflow jobs.

Implements server-side enforcement and persistence for:
- #2528: Same-version Stencil variant uniqueness (`stencil_variants`) without SemVer '+' ordering.
- #2529: Installation-bound signed Stencil distribution grants (`stencil_distribution_grants`,
  `stencil_grant_events`) with atomic registration, online renewal, revocation, and audit.
- #2530: Customer-scoped RC/RELEASE catalog export, list, detail, signature, and ETag isolation
  with installed-version recall/recovery preservation.
- #2531: Customer-scoped component artifact and OCI registry pull enforcement.
- #2532 / #2534: Durable build/publish/promote workflow jobs (`release_workflow_jobs`) with
  idempotent resume and promotion-run gate receipts (`promotion_run_receipts`).
"""

from __future__ import annotations

import hashlib
import json
from base64 import b64encode
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai_deployment_cli.contracts import canonical_bytes, load_json_object
from fdai_deployment_cli.lifecycle_release import (
    ApplicationRelease,
    LifecycleRelease,
    parse_lifecycle_release_manifest,
)
from fdai_deployment_cli.lifecycle_stencil_grant import (
    CUSTOMER_ENTITLED_CHANNELS,
    SignedStencilDistributionGrant,
    StencilBindingError,
    StencilDistributionGrant,
    extract_stencil_variant_binding,
    verify_stencil_distribution_grant,
)
from fdai_deployment_cli.runtime_release import compare_release_ids, evaluate_recall_candidate
from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from fdai_lifecycle_hub.catalog_import import export_signing_message
from fdai_release_hub.catalog_serialization import CatalogError
from fdai_release_hub.database import (
    releases,
    stencil_distribution_grants,
    stencil_grant_events,
    stencil_variants,
)
from fdai_release_hub.registry_pipeline import build_oci_manifest_bytes, lookup_oci_manifest

if TYPE_CHECKING:
    from fdai_release_hub.store import ReleaseStore


@dataclass(frozen=True, slots=True)
class ScopedCustomerExport:
    """Signed customer-scoped catalog export bound to one verified distribution grant (#2530)."""

    revision: int
    raw: bytes
    digest: str
    signature: str
    key_id: str
    etag: str
    grant_scope_digest: str
    scope_binding_signature: str
    recovery_only: bool


def export_grant_scope_message(
    *,
    export_digest: str,
    catalog_revision: int,
    installation_id: str,
    grant_id: str,
    grant_revision: int,
    grant_scope_digest: str,
    recovery_only: bool,
) -> bytes:
    """Domain-separated message binding a signed export to the Release Hub's active grant state."""
    mode = "recovery" if recovery_only else "active"
    return b"fdai.export-grant-scope.v1\n" + (
        f"{export_digest}:{catalog_revision}:{installation_id}:"
        f"{grant_id}:{grant_revision}:{grant_scope_digest}:{mode}"
    ).encode("ascii")


def record_stencil_variant_on_register(
    db: Connection,
    *,
    release_id: str,
    release: LifecycleRelease,
    now_iso: str,
) -> None:
    """Validate and persist same-version `(base_release_version, stencil_id)` uniqueness (#2528)."""
    try:
        binding = extract_stencil_variant_binding(release_id, release)
    except StencilBindingError as exc:
        raise CatalogError(
            f"Invalid Stencil variant binding ({exc.reason_code}): {exc}", 422
        ) from exc
    if binding is None:
        return
    existing = (
        db.execute(
            select(stencil_variants).where(
                stencil_variants.c.base_release_version == binding.base_release_version,
                stencil_variants.c.stencil_id == binding.stencil_id,
            )
        )
        .mappings()
        .first()
    )
    if existing is not None:
        raise CatalogError(
            f"Stencil variant {binding.variant_key!r} is already registered as "
            f"{existing['release_id']!r}.",
            409,
        )
    try:
        db.execute(
            stencil_variants.insert().values(
                variant_key=binding.variant_key,
                base_release_version=binding.base_release_version,
                stencil_id=binding.stencil_id,
                release_id=binding.release_id,
                stencil_digest=binding.stencil_digest,
                release_digest=binding.release_digest,
                source_commit=binding.source_commit,
                registered_at=now_iso,
            )
        )
    except IntegrityError as exc:
        raise CatalogError(
            f"Stencil variant {binding.variant_key!r} conflicts with an existing record.",
            409,
        ) from exc


def list_stencil_variants(
    store: ReleaseStore,
    *,
    base_release_version: str | None = None,
) -> list[dict[str, Any]]:
    """Return registered Stencil variant bindings ordered by base version and Stencil ID."""
    with store.connect() as db:
        stmt = select(stencil_variants).order_by(
            stencil_variants.c.base_release_version.desc(),
            stencil_variants.c.stencil_id.asc(),
        )
        if base_release_version is not None:
            stmt = stmt.where(stencil_variants.c.base_release_version == base_release_version)
        return [dict(row) for row in db.execute(stmt).mappings().all()]


def register_or_renew_grant(
    store: ReleaseStore,
    envelope: Mapping[str, Any],
    *,
    trusted_public_keys: Sequence[Ed25519PublicKey],
    actor: str = "grant-issuer",
    reason: str = "register-or-renew-grant",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify and atomically store an initial, renewed, or revoked distribution grant (#2529)."""
    if not actor.strip() or len(actor) > 160:
        raise CatalogError("An attributed actor is required.", 422)
    if not reason.strip() or len(reason) > 500:
        raise CatalogError("A non-blank reason is required.", 422)
    check_now = now or store.clock()
    try:
        verified = verify_stencil_distribution_grant(
            envelope,
            trusted_public_keys=trusted_public_keys,
            now=check_now,
            allow_expired_or_revoked_for_recovery=bool(
                isinstance(envelope.get("grant"), Mapping)
                and envelope["grant"].get("revoked") is True
            ),
        )
    except StencilBindingError as exc:
        raise CatalogError(f"Distribution grant rejected ({exc.reason_code}): {exc}", 403) from exc

    grant = verified.grant
    now_iso = check_now.isoformat()
    with store.connect() as db:
        existing = (
            db.execute(
                select(stencil_distribution_grants).where(
                    stencil_distribution_grants.c.installation_id == grant.installation_id
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            if existing["customer_principal"] != grant.customer_principal:
                raise CatalogError(
                    "Grant principal conflict for existing installation binding.",
                    409,
                )
            prev_rev = int(existing["revision"])
            if grant.revision < prev_rev:
                raise CatalogError(
                    f"Grant revision {grant.revision} is lower than stored revision {prev_rev}.",
                    409,
                )
            prev_issued = datetime.fromisoformat(str(existing["issued_at"]))
            curr_issued = datetime.fromisoformat(grant.issued_at)
            if curr_issued < prev_issued:
                raise CatalogError(
                    "Grant issued_at regressed below stored grant timestamp.",
                    409,
                )
            if grant.revision == prev_rev:
                stored_env = json.loads(str(existing["envelope_json"]))
                if canonical_bytes(stored_env) == canonical_bytes(verified.to_envelope()):
                    return _grant_row_to_dict(existing)
                raise CatalogError(
                    "Conflicting distribution grant at the same revision.",
                    409,
                )
            action = "revoke" if grant.revoked else "renew"
            db.execute(
                stencil_distribution_grants.update()
                .where(stencil_distribution_grants.c.installation_id == grant.installation_id)
                .values(
                    grant_id=grant.grant_id,
                    issuer_key_id=grant.issuer_key_id,
                    customer_principal=grant.customer_principal,
                    allowed_stencil_ids_json=json.dumps(list(grant.allowed_stencil_ids)),
                    allowed_channels_json=json.dumps(list(grant.allowed_channels)),
                    revision=grant.revision,
                    issued_at=grant.issued_at,
                    expires_at=grant.expires_at,
                    revoked=grant.revoked,
                    revocation_reason=grant.revocation_reason,
                    scope_digest=grant.scope_digest,
                    envelope_json=json.dumps(verified.to_envelope(), sort_keys=True),
                    updated_at=now_iso,
                )
            )
        else:
            action = "revoke" if grant.revoked else "register"
            try:
                db.execute(
                    stencil_distribution_grants.insert().values(
                        installation_id=grant.installation_id,
                        grant_id=grant.grant_id,
                        issuer_key_id=grant.issuer_key_id,
                        customer_principal=grant.customer_principal,
                        allowed_stencil_ids_json=json.dumps(list(grant.allowed_stencil_ids)),
                        allowed_channels_json=json.dumps(list(grant.allowed_channels)),
                        revision=grant.revision,
                        issued_at=grant.issued_at,
                        expires_at=grant.expires_at,
                        revoked=grant.revoked,
                        revocation_reason=grant.revocation_reason,
                        scope_digest=grant.scope_digest,
                        envelope_json=json.dumps(verified.to_envelope(), sort_keys=True),
                        updated_at=now_iso,
                    )
                )
            except IntegrityError as exc:
                raise CatalogError(
                    "Grant ID is already bound to another installation.", 409
                ) from exc

        db.execute(
            stencil_grant_events.insert().values(
                installation_id=grant.installation_id,
                grant_id=grant.grant_id,
                revision=grant.revision,
                action=action,
                actor=actor.strip(),
                reason=reason.strip(),
                occurred_at=now_iso,
            )
        )
        saved = (
            db.execute(
                select(stencil_distribution_grants).where(
                    stencil_distribution_grants.c.installation_id == grant.installation_id
                )
            )
            .mappings()
            .one()
        )
        return _grant_row_to_dict(saved)


def _grant_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "installation_id": row["installation_id"],
        "grant_id": row["grant_id"],
        "issuer_key_id": row["issuer_key_id"],
        "customer_principal": row["customer_principal"],
        "allowed_stencil_ids": json.loads(str(row["allowed_stencil_ids_json"])),
        "allowed_channels": json.loads(str(row["allowed_channels_json"])),
        "revision": int(row["revision"]),
        "issued_at": row["issued_at"],
        "expires_at": row["expires_at"],
        "revoked": bool(row["revoked"]),
        "revocation_reason": row["revocation_reason"],
        "scope_digest": row["scope_digest"],
        "envelope": json.loads(str(row["envelope_json"])),
        "updated_at": row["updated_at"],
    }


def get_grant_for_installation(
    store: ReleaseStore,
    installation_id: str,
) -> dict[str, Any] | None:
    """Return the persisted distribution grant record for `installation_id` if present."""
    with store.connect() as db:
        row = (
            db.execute(
                select(stencil_distribution_grants).where(
                    stencil_distribution_grants.c.installation_id == installation_id
                )
            )
            .mappings()
            .first()
        )
        return _grant_row_to_dict(row) if row is not None else None


def store_requires_scoped_oci_pull(store: ReleaseStore) -> bool:
    """Return True when catalog releases or distribution grants exist in `store`."""
    with store.connect() as db:
        has_rel = db.execute(select(releases.c.id).limit(1)).first() is not None
        if has_rel:
            return True
        return (
            db.execute(select(stencil_distribution_grants.c.installation_id).limit(1)).first()
            is not None
        )


def list_grant_events(
    store: ReleaseStore,
    *,
    installation_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return attributed distribution grant audit events."""
    with store.connect() as db:
        stmt = select(stencil_grant_events).order_by(stencil_grant_events.c.id.desc())
        if installation_id is not None:
            stmt = stmt.where(stencil_grant_events.c.installation_id == installation_id)
        return [dict(r) for r in db.execute(stmt).mappings().all()]


def _authenticate_customer_grant(
    store: ReleaseStore,
    *,
    installation_id: str,
    customer_principal: str,
    trusted_public_keys: Sequence[Ed25519PublicKey],
    presented_envelope: Mapping[str, Any] | None = None,
    installed_release_id: str | None = None,
    now: datetime | None = None,
) -> tuple[SignedStencilDistributionGrant, bool]:
    """Authenticate stored + presented customer grant; return `(verified, recovery_only)`."""
    if not installation_id or not customer_principal:
        raise CatalogError(
            "Customer catalog/artifact access requires installation_id and customer_principal.",
            401,
        )
    if presented_envelope is None:
        raise CatalogError(
            "Customer catalog/artifact access requires a signed distribution grant envelope.",
            401,
        )
    check_now = now or store.clock()
    stored = get_grant_for_installation(store, installation_id)
    if stored is None:
        raise CatalogError("No distribution grant is registered for this installation.", 403)
    if stored["customer_principal"] != customer_principal:
        raise CatalogError(
            "Authenticated customer principal does not match the installation's registered grant.",
            403,
        )

    minimum_rev = int(stored["revision"])
    prev_issued = datetime.fromisoformat(str(stored["issued_at"]))

    try:
        verified = verify_stencil_distribution_grant(
            presented_envelope,
            trusted_public_keys=trusted_public_keys,
            expected_installation_id=installation_id,
            expected_customer_principal=customer_principal,
            minimum_revision=minimum_rev,
            previous_issued_at=prev_issued,
            now=check_now,
            allow_expired_or_revoked_for_recovery=False,
        )
        if stored["revoked"] and not verified.grant.revoked:
            if verified.grant.revision <= minimum_rev:
                raise StencilBindingError(
                    "grant_revoked",
                    "Stale unrevoked receipt cannot restore a revoked distribution grant.",
                )
        return verified, False
    except StencilBindingError as exc:
        if installed_release_id and exc.reason_code in {"grant_expired", "grant_revoked"}:
            try:
                recovery_verified = verify_stencil_distribution_grant(
                    presented_envelope,
                    trusted_public_keys=trusted_public_keys,
                    expected_installation_id=installation_id,
                    expected_customer_principal=customer_principal,
                    minimum_revision=minimum_rev,
                    now=check_now,
                    allow_expired_or_revoked_for_recovery=True,
                )
                return recovery_verified, True
            except StencilBindingError:
                pass
        raise CatalogError(f"Distribution grant denied ({exc.reason_code}).", 403) from exc


def _release_stencil_id(release: LifecycleRelease) -> str | None:
    if isinstance(release, ApplicationRelease) and release.stencil is not None:
        raw = release.stencil.get("stencil_id")
        if isinstance(raw, str):
            return raw
    return None


def _filter_scoped_snapshot(
    store: ReleaseStore,
    *,
    grant: StencilDistributionGrant,
    recovery_only: bool,
    installed_release_id: str | None,
) -> tuple[
    dict[str, dict[str, str]], dict[str, list[str]], list[dict[str, Any]], list[dict[str, Any]]
]:
    """Filter snapshot releases, channels, and recalls to the customer's scope (#2530)."""
    snap = store.snapshot()
    raw_channels: Mapping[str, list[str]] = snap.get("channels", {})
    allowed_channels = tuple(
        ch for ch in grant.allowed_channels if ch in CUSTOMER_ENTITLED_CHANNELS
    )
    allowed_stencils = set(grant.allowed_stencil_ids)

    parsed_by_id: dict[str, tuple[dict[str, Any], LifecycleRelease]] = {}
    for rel_row in snap.get("releases", []):
        if rel_row.get("state") == "draft" or not rel_row.get("signature"):
            continue
        rel_id = str(rel_row["id"])
        parsed: LifecycleRelease | None
        try:
            parsed = parse_lifecycle_release_manifest(str(rel_row["manifest"]).encode("utf-8"))
        except ValueError:
            parsed = None
        if parsed is not None:
            parsed_by_id[rel_id] = (rel_row, parsed)

    recall_events = [
        ev
        for ev in reversed(snap.get("events", []))
        if ev.get("action") in ("recall", "recall_capability", "lift_capability")
    ]
    all_recalls = store._recall_records_from_events(recall_events)

    entitled_release_ids: set[str] = set()
    scoped_channels: dict[str, list[str]] = {ch: [] for ch in allowed_channels}

    if not recovery_only:
        for ch in allowed_channels:
            for rel_id in raw_channels.get(ch, []):
                entry = parsed_by_id.get(rel_id)
                if entry is None:
                    continue
                _rel_row, parsed = entry
                st_id = _release_stencil_id(parsed)
                if st_id not in allowed_stencils:
                    continue
                scoped_channels[ch].append(rel_id)
                entitled_release_ids.add(rel_id)

    # Preserve safety recall & roll-off recovery for an already installed release (#2530 / #2531).
    if installed_release_id and installed_release_id in parsed_by_id:
        inst_row, inst_parsed = parsed_by_id[installed_release_id]
        inst_stencil = _release_stencil_id(inst_parsed)
        if inst_stencil in allowed_stencils:
            entitled_release_ids.add(installed_release_id)
            inst_caps = tuple(sorted(inst_parsed.capability_maximums))
            recall_eval = evaluate_recall_candidate(
                release_id=installed_release_id,
                capability_ids=inst_caps,
                recall_records=all_recalls,
            )
            if not recall_eval.allowed or inst_row.get("recalled_at"):
                for ch in allowed_channels:
                    for cand_id in raw_channels.get(ch, []):
                        cand_entry = parsed_by_id.get(cand_id)
                        if cand_entry is None:
                            continue
                        cand_row, cand_parsed = cand_entry
                        if _release_stencil_id(cand_parsed) != inst_stencil:
                            continue
                        if cand_row.get("recalled_at"):
                            continue
                        cand_eval = evaluate_recall_candidate(
                            release_id=cand_id,
                            capability_ids=tuple(sorted(cand_parsed.capability_maximums)),
                            recall_records=all_recalls,
                        )
                        if (
                            cand_eval.allowed
                            and compare_release_ids(cand_id, installed_release_id) <= 0
                        ):
                            entitled_release_ids.add(cand_id)
                            if cand_id not in scoped_channels[ch]:
                                scoped_channels[ch].append(cand_id)

    scoped_releases_export: dict[str, dict[str, str]] = {}
    scoped_release_details: list[dict[str, Any]] = []
    for rel_id in sorted(entitled_release_ids):
        rel_row, _parsed = parsed_by_id[rel_id]
        scoped_releases_export[rel_id] = {
            "manifest": str(rel_row["manifest"]),
            "signature": str(rel_row["signature"]),
        }
        visible_rel_channels = [ch for ch in rel_row.get("channels", []) if ch in allowed_channels]
        scoped_release_details.append(
            {
                **rel_row,
                "channels": visible_rel_channels,
            }
        )

    scoped_recalls: list[dict[str, Any]] = []
    for rec in all_recalls:
        rec_map: dict[str, Any] = {
            "scope": rec.scope,
            "target": rec.target,
            "sequence": rec.sequence,
            "notice_digest": rec.notice_digest,
            "action": rec.action,
        }
        if rec.lifting_release_id is not None:
            rec_map["lifting_release_id"] = rec.lifting_release_id
        if rec.scope == "release":
            if rec.target in entitled_release_ids:
                scoped_recalls.append(rec_map)
        else:
            scoped_recalls.append(rec_map)

    return scoped_releases_export, scoped_channels, scoped_recalls, scoped_release_details


def build_scoped_customer_export(
    store: ReleaseStore,
    *,
    installation_id: str,
    customer_principal: str,
    trusted_public_keys: Sequence[Ed25519PublicKey],
    presented_envelope: Mapping[str, Any] | None = None,
    installed_release_id: str | None = None,
    now: datetime | None = None,
) -> ScopedCustomerExport:
    """Build and sign a customer-scoped RC/RELEASE catalog export with scope-bound ETag (#2530)."""
    verified, recovery_only = _authenticate_customer_grant(
        store,
        installation_id=installation_id,
        customer_principal=customer_principal,
        trusted_public_keys=trusted_public_keys,
        presented_envelope=presented_envelope,
        installed_release_id=installed_release_id,
        now=now,
    )
    snap = store.snapshot()
    releases_map, channels_map, recalls_list, _details = _filter_scoped_snapshot(
        store,
        grant=verified.grant,
        recovery_only=recovery_only,
        installed_release_id=installed_release_id,
    )
    export_doc = {
        "channels": channels_map,
        "expires_at": snap["expires_at"],
        "recalls": recalls_list,
        "releases": releases_map,
        "revision": int(snap["revision"]),
    }
    raw_bytes = canonical_bytes(export_doc)
    digest = hashlib.sha256(raw_bytes).hexdigest()
    signature = b64encode(store.key.sign(export_signing_message(raw_bytes))).decode("ascii")
    scope_binding_sig = b64encode(
        store.key.sign(
            export_grant_scope_message(
                export_digest=digest,
                catalog_revision=int(snap["revision"]),
                installation_id=installation_id,
                grant_id=verified.grant.grant_id,
                grant_revision=verified.grant.revision,
                grant_scope_digest=verified.grant.scope_digest,
                recovery_only=recovery_only,
            )
        )
    ).decode("ascii")
    scope_suffix = verified.grant.scope_digest.removeprefix("sha256:")[:16]
    mode_tag = "recovery" if recovery_only else "active"
    etag = f'"{digest}-{scope_suffix}-{mode_tag}"'
    return ScopedCustomerExport(
        revision=int(snap["revision"]),
        raw=raw_bytes,
        digest=digest,
        signature=signature,
        key_id=store.key.key_id,
        etag=etag,
        grant_scope_digest=verified.grant.scope_digest,
        scope_binding_signature=scope_binding_sig,
        recovery_only=recovery_only,
    )


def list_scoped_customer_releases(
    store: ReleaseStore,
    *,
    installation_id: str,
    customer_principal: str,
    trusted_public_keys: Sequence[Ed25519PublicKey],
    presented_envelope: Mapping[str, Any] | None = None,
    installed_release_id: str | None = None,
    channel_filter: str | None = None,
    stencil_filter: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """List/search customer-entitled RC/RELEASE variants with zero DEV or cross-Stencil leakage."""
    if channel_filter == "DEV":
        raise CatalogError("Customer catalog queries cannot request the DEV channel.", 403)
    verified, recovery_only = _authenticate_customer_grant(
        store,
        installation_id=installation_id,
        customer_principal=customer_principal,
        trusted_public_keys=trusted_public_keys,
        presented_envelope=presented_envelope,
        installed_release_id=installed_release_id,
        now=now,
    )
    _rel_map, channels_map, recalls_list, details = _filter_scoped_snapshot(
        store,
        grant=verified.grant,
        recovery_only=recovery_only,
        installed_release_id=installed_release_id,
    )
    filtered = details
    if channel_filter is not None:
        if channel_filter not in verified.grant.allowed_channels:
            filtered = []
        else:
            allowed_in_ch = set(channels_map.get(channel_filter, []))
            filtered = [r for r in filtered if r["id"] in allowed_in_ch]
    if stencil_filter is not None:
        if stencil_filter not in verified.grant.allowed_stencil_ids:
            filtered = []
        else:
            matched: list[dict[str, Any]] = []
            for r in filtered:
                parsed = parse_lifecycle_release_manifest(str(r["manifest"]).encode("utf-8"))
                if _release_stencil_id(parsed) == stencil_filter:
                    matched.append(r)
            filtered = matched

    return {
        "installation_id": installation_id,
        "grant_id": verified.grant.grant_id,
        "grant_revision": verified.grant.revision,
        "grant_scope_digest": verified.grant.scope_digest,
        "recovery_only": recovery_only,
        "allowed_stencil_ids": list(verified.grant.allowed_stencil_ids),
        "allowed_channels": list(verified.grant.allowed_channels),
        "channels": channels_map,
        "releases": filtered,
        "recalls": recalls_list,
    }


def get_scoped_customer_release_detail(
    store: ReleaseStore,
    *,
    release_id: str,
    installation_id: str,
    customer_principal: str,
    trusted_public_keys: Sequence[Ed25519PublicKey],
    presented_envelope: Mapping[str, Any] | None = None,
    installed_release_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return detail for one entitled release or uniform 404 without leaking DEV/other Stencils."""
    listing = list_scoped_customer_releases(
        store,
        installation_id=installation_id,
        customer_principal=customer_principal,
        trusted_public_keys=trusted_public_keys,
        presented_envelope=presented_envelope,
        installed_release_id=installed_release_id,
        now=now,
    )
    for rel in listing["releases"]:
        if rel["id"] == release_id:
            return dict(rel)
    raise CatalogError("Release not found in authorized customer scope.", 404)


def resolve_scoped_customer_artifact_pull(
    store: ReleaseStore,
    *,
    component: str,
    reference: str,
    installation_id: str,
    customer_principal: str,
    trusted_public_keys: Sequence[Ed25519PublicKey],
    presented_envelope: Mapping[str, Any] | None = None,
    installed_release_id: str | None = None,
    now: datetime | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    """Enforce the customer Stencil grant boundary on OCI manifest & artifact pulls (#2531)."""
    listing = list_scoped_customer_releases(
        store,
        installation_id=installation_id,
        customer_principal=customer_principal,
        trusted_public_keys=trusted_public_keys,
        presented_envelope=presented_envelope,
        installed_release_id=installed_release_id,
        now=now,
    )
    for rel in listing["releases"]:
        rel_id = str(rel["id"])
        try:
            manifest_doc = load_json_object(
                str(rel["manifest"]).encode("utf-8"),
                label="release manifest",
                max_bytes=2 * 1024 * 1024,
            )
        except ValueError:
            continue
        comps = manifest_doc.get("components")
        if not isinstance(comps, dict) or component not in comps:
            continue
        comp_entry = comps[component]
        if not isinstance(comp_entry, dict):
            continue
        comp_digest = str(comp_entry.get("image_digest", ""))
        if reference not in (comp_digest, rel_id):
            continue
        direct = lookup_oci_manifest(component, comp_digest) or lookup_oci_manifest(
            component, reference
        )
        if direct is not None:
            oci_bytes, resolved_digest = direct
        else:
            st_meta = manifest_doc.get("stencil")
            st_id = (
                str(st_meta.get("stencil_id", "standard-sre"))
                if isinstance(st_meta, dict)
                else "standard-sre"
            )
            oci_bytes = build_oci_manifest_bytes(
                component=component,
                release_version=rel_id,
                source_commit=str(manifest_doc.get("source_commit", "0" * 40)),
                stencil_id=st_id,
                config_digest=comp_digest,
                layers=(comp_digest,),
                size_bytes=0,
                provenance="scoped-customer-entitled",
            )
            resolved_digest = comp_digest
        metadata = {
            "installation_id": installation_id,
            "grant_id": listing["grant_id"],
            "grant_scope_digest": listing["grant_scope_digest"],
            "release_id": rel_id,
            "component": component,
            "image_digest": resolved_digest,
            "recovery_only": listing["recovery_only"],
        }
        return oci_bytes, resolved_digest, metadata

    raise CatalogError(
        "Requested component or digest is not permitted by the installation's Stencil grant.",
        403,
    )


from fdai_release_hub.stencil_workflow_jobs import (  # noqa: E402
    execute_or_resume_release_workflow_job,
    list_promotion_run_receipts,
    list_release_workflow_jobs,
    record_promotion_run_receipt,
)

__all__ = [
    "ScopedCustomerExport",
    "build_scoped_customer_export",
    "execute_or_resume_release_workflow_job",
    "get_grant_for_installation",
    "get_scoped_customer_release_detail",
    "list_grant_events",
    "list_promotion_run_receipts",
    "list_release_workflow_jobs",
    "list_scoped_customer_releases",
    "list_stencil_variants",
    "record_promotion_run_receipt",
    "record_stencil_variant_on_register",
    "register_or_renew_grant",
    "resolve_scoped_customer_artifact_pull",
    "store_requires_scoped_oci_pull",
]
