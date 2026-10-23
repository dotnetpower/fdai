"""Trusted-host orchestration over existing transactional Hub boundaries."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_release import (
    ApplicationRelease,
    parse_lifecycle_release_manifest,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine

from fdai_lifecycle_hub.domain import Issued, PlanOutcome, Unchanged
from fdai_lifecycle_hub.remote_catalog import PinApproval, RemoteCatalog
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore
from fdai_release_hub.store import Change, ReleaseStore


class ReleasePublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.release-publication-request.v1"]
    request_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    release_id: str
    manifest: str = Field(max_length=1024 * 1024)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    channels: tuple[str, ...] = ("DEV",)
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str

    @model_validator(mode="after")
    def validate_request(self) -> ReleasePublicationRequest:
        release = parse_lifecycle_release_manifest(self.manifest.encode())
        if (
            not isinstance(release, ApplicationRelease)
            or release.release_version != self.release_id
            or release.digest != self.manifest_digest
            or not self.channels
            or len(set(self.channels)) != len(self.channels)
            or self.confirmation != f"publish {self.release_id} to {','.join(self.channels)}"
        ):
            raise ValueError("Release publication request identity is invalid.")
        return self


class CatalogImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.catalog-import-request.v1"]
    request_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    revision: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str

    @model_validator(mode="after")
    def validate_request(self) -> CatalogImportRequest:
        if self.confirmation != f"approve {self.revision} {self.sha256}":
            raise ValueError("Catalog import confirmation differs.")
        return self


class RecomputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["fdai.lifecycle-recompute-request.v1"]
    request_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    installation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    catalog_revision: int = Field(ge=1)
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def publish_release(
    engine: Engine,
    key: HubSigningKey,
    request: ReleasePublicationRequest,
    *,
    actor: str,
    now: datetime,
) -> dict[str, Any]:
    """Converge one immutable Release through register, publish, and channel membership."""

    store = ReleaseStore(engine, key, clock=lambda: now, initialize=False)
    snapshot = store.snapshot()
    mutated = False
    existing = next(
        (item for item in snapshot["releases"] if item["id"] == request.release_id),
        None,
    )
    if existing is None:
        snapshot = store.change(
            "register",
            request.release_id,
            Change(
                revision=snapshot["revision"],
                confirmation=request.release_id,
                reason=request.reason,
                manifest=request.manifest,
            ),
            actor=actor,
        )
        mutated = True
        existing = next(item for item in snapshot["releases"] if item["id"] == request.release_id)
    if (
        existing["manifest"] != request.manifest
        or existing["digest"] != request.manifest_digest
        or existing["state"] == "recalled"
    ):
        raise ValueError("Existing Release differs from the publication request.")
    if existing["state"] == "draft":
        snapshot = store.change(
            "publish",
            request.release_id,
            Change(
                revision=snapshot["revision"],
                confirmation=request.release_id,
                reason=request.reason,
            ),
            actor=actor,
        )
        mutated = True
    for channel in request.channels:
        existing = next(item for item in snapshot["releases"] if item["id"] == request.release_id)
        if channel in existing["channels"]:
            continue
        snapshot = store.change(
            "contribute",
            request.release_id,
            Change(
                revision=snapshot["revision"],
                confirmation=request.release_id,
                reason=request.reason,
                channel=channel,
                channel_confirmation=channel if channel.startswith("custom-") else None,
            ),
            actor=actor,
        )
        mutated = True
    raw, digest = store.export_snapshot(snapshot)
    return {
        "schema_version": "fdai.release-publication-receipt.v1",
        "request_id": request.request_id,
        "release_id": request.release_id,
        "manifest_digest": request.manifest_digest,
        "catalog_revision": snapshot["revision"],
        "catalog_sha256": digest,
        "catalog_bytes": len(raw),
        "channels": list(request.channels),
        "effect_verified": True,
        "mutation_performed": mutated,
    }


def approve_and_import_catalog(
    catalog: RemoteCatalog,
    request: CatalogImportRequest,
    *,
    actor: str,
    now: datetime,
) -> dict[str, Any]:
    """Converge one exact independently approved catalog pin without renewing it."""

    status = catalog.status()
    mutated = not (
        status["imported"]
        and status["minimum_revision"] == request.revision
        and status["accepted_sha256"] == request.sha256
    )
    if mutated:
        catalog.approve(
            PinApproval(
                revision=request.revision,
                sha256=request.sha256,
                confirmation=request.confirmation,
                reason=request.reason,
            ),
            actor=actor,
            now=now,
        )
        status = catalog.import_once(actor=actor, now=now)
    if (
        not status["imported"]
        or status["minimum_revision"] != request.revision
        or status["accepted_sha256"] != request.sha256
    ):
        raise ValueError("Catalog import readback differs from the approved pin.")
    return {
        "schema_version": "fdai.catalog-import-receipt.v1",
        "request_id": request.request_id,
        "catalog_revision": request.revision,
        "catalog_sha256": request.sha256,
        "effect_verified": True,
        "mutation_performed": mutated,
    }


def recompute_installation(
    store: HubStore,
    catalog: RemoteCatalog,
    key: HubSigningKey,
    request: RecomputeRequest,
    *,
    now: datetime,
) -> tuple[PlanOutcome, dict[str, Any]]:
    """Compute one Plan only against the exact accepted catalog named by the request."""

    status = catalog.status()
    if (
        not status["imported"]
        or status["minimum_revision"] != request.catalog_revision
        or status["accepted_sha256"] != request.catalog_sha256
    ):
        raise ValueError("Lifecycle recompute catalog binding differs.")
    outcome = catalog.recompute(store, request.installation_id, key, now=now)
    plan = outcome.plan if isinstance(outcome, (Issued, Unchanged)) else None
    payload = canonical_bytes(
        {
            "request_id": request.request_id,
            "installation_id": request.installation_id,
            "catalog_revision": request.catalog_revision,
            "catalog_sha256": request.catalog_sha256,
            "outcome": outcome.kind,
            "plan_id": plan.plan_id if plan is not None else None,
        }
    )
    receipt = {
        "schema_version": "fdai.lifecycle-recompute-receipt.v1",
        "request_id": request.request_id,
        "installation_id": request.installation_id,
        "catalog_revision": request.catalog_revision,
        "catalog_sha256": request.catalog_sha256,
        "outcome": outcome.kind,
        "plan_id": plan.plan_id if plan is not None else None,
        "receipt_digest": hashlib.sha256(payload).hexdigest(),
        "mutation_performed": isinstance(outcome, Issued),
    }
    return outcome, receipt


__all__ = [
    "CatalogImportRequest",
    "RecomputeRequest",
    "ReleasePublicationRequest",
    "approve_and_import_catalog",
    "publish_release",
    "recompute_installation",
]
