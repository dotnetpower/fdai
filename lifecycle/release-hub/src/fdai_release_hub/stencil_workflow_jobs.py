"""Durable Release Hub workflow jobs, promotion receipts, and Stencil API routes (#2532/#2534)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from sqlalchemy import select
from sqlalchemy.engine import Connection
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_release_hub.catalog_serialization import CatalogError
from fdai_release_hub.database import (
    catalog_metadata,
    promotion_run_receipts,
    release_workflow_jobs,
)
from fdai_release_hub.registry_pipeline import OCI_IMAGE_MANIFEST_MEDIA_TYPE
from fdai_release_hub.stencil_grants import (
    build_scoped_customer_export,
    get_grant_for_installation,
    get_scoped_customer_release_detail,
    list_grant_events,
    list_scoped_customer_releases,
    list_stencil_variants,
    register_or_renew_grant,
    resolve_scoped_customer_artifact_pull,
)
from fdai_release_hub.stencil_product_decisions import (
    F01_TO_F15_FEATURE_MAPPING,
    REVIEWED_STENCIL_DRAFTS,
    STENCIL_PRODUCT_DECISION_REGISTER,
)
from fdai_release_hub.stencils import evaluate_stencil_footprint

if TYPE_CHECKING:
    from fdai_release_hub.store import ReleaseStore


def execute_or_resume_release_workflow_job(
    store: ReleaseStore,
    *,
    job_id: str,
    idempotency_key: str,
    release_id: str,
    stencil_id: str,
    source_commit: str,
    manifest: Mapping[str, Any] | str,
    label: str = "",
    reason: str = "Automated Stencil vendor publication workflow",
    actor: str = "vendor-operator",
) -> dict[str, Any]:
    """Execute or safely resume a durable build -> validate -> sign -> DEV job (#2532/#2534)."""
    raw_manifest = (
        manifest if isinstance(manifest, str) else canonical_bytes(dict(manifest)).decode("utf-8")
    )
    input_digest = "sha256:" + canonical_digest(
        {
            "release_id": release_id,
            "stencil_id": stencil_id,
            "source_commit": source_commit,
            "manifest": raw_manifest,
        }
    )
    now_iso = store.clock().isoformat()
    recovering = False

    with store.connect() as db:
        if store.engine.dialect.name == "sqlite":
            db.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            db.execute(select(catalog_metadata).with_for_update()).all()
        existing = (
            db.execute(
                select(release_workflow_jobs).where(
                    release_workflow_jobs.c.idempotency_key == idempotency_key
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            if existing["input_digest"] != input_digest:
                raise CatalogError(
                    "Idempotency key conflicts with different workflow job inputs.",
                    409,
                )
            if existing["status"] == "completed":
                saved_result = json.loads(str(existing["result_json"]))
                return {
                    "job_id": existing["job_id"],
                    "idempotency_key": existing["idempotency_key"],
                    "release_id": existing["release_id"],
                    "stencil_id": existing["stencil_id"],
                    "source_commit": existing["source_commit"],
                    "stage": existing["stage"],
                    "status": "resumed",
                    "resumed_from_durable_state": True,
                    "input_digest": existing["input_digest"],
                    "manifest_digest": existing["manifest_digest"],
                    "actor": existing["actor"],
                    "result": saved_result,
                    "created_at": existing["created_at"],
                    "updated_at": existing["updated_at"],
                }
            recovering = True
            job_id = str(existing["job_id"])
            created_iso = str(existing["created_at"])
        else:
            created_iso = now_iso
            db.execute(
                release_workflow_jobs.insert().values(
                    job_id=job_id,
                    idempotency_key=idempotency_key,
                    release_id=release_id,
                    stencil_id=stencil_id,
                    source_commit=source_commit,
                    stage="reserved",
                    status="running",
                    input_digest=input_digest,
                    manifest_digest=(
                        "sha256:" + hashlib.sha256(raw_manifest.encode("utf-8")).hexdigest()
                    ),
                    actor=actor,
                    error_code=None,
                    result_json="{}",
                    created_at=created_iso,
                    updated_at=now_iso,
                )
            )

    from fdai_release_hub.store import Change

    snap = store.snapshot()
    existing_rel = next((r for r in snap["releases"] if r["id"] == release_id), None)
    if existing_rel is None:
        snap = store.change(
            "register",
            release_id,
            Change(
                revision=int(snap["revision"]),
                confirmation=release_id,
                reason=reason,
                label=label or f"{release_id} ({stencil_id})",
                manifest=raw_manifest,
            ),
            actor=actor,
        )
        existing_rel = next(r for r in snap["releases"] if r["id"] == release_id)
    elif existing_rel["manifest"] != raw_manifest:
        raise CatalogError(
            "Release ID already exists with different manifest bytes.",
            409,
        )

    if not existing_rel.get("signature"):
        snap = store.change(
            "publish",
            release_id,
            Change(
                revision=int(snap["revision"]),
                confirmation=release_id,
                reason=reason,
            ),
            actor=actor,
        )
        existing_rel = next(r for r in snap["releases"] if r["id"] == release_id)

    manifest_digest = f"sha256:{existing_rel['digest']}"
    result_summary = {
        "catalog_revision": snap["revision"],
        "release_id": release_id,
        "stencil_id": stencil_id,
        "state": existing_rel["state"],
        "channels": existing_rel["channels"],
        "signature": existing_rel["signature"],
        "signed_payload_sha256": existing_rel["signed_payload_sha256"],
    }

    with store.connect() as db:
        db.execute(
            release_workflow_jobs.update()
            .where(release_workflow_jobs.c.idempotency_key == idempotency_key)
            .values(
                stage="publish_dev",
                status="completed",
                manifest_digest=manifest_digest,
                error_code=None,
                result_json=json.dumps(result_summary, sort_keys=True),
                updated_at=now_iso,
            )
        )
    return {
        "job_id": job_id,
        "idempotency_key": idempotency_key,
        "release_id": release_id,
        "stencil_id": stencil_id,
        "source_commit": source_commit,
        "stage": "publish_dev",
        "status": "resumed" if recovering else "completed",
        "resumed_from_durable_state": recovering,
        "input_digest": input_digest,
        "manifest_digest": manifest_digest,
        "actor": actor,
        "result": result_summary,
        "created_at": created_iso,
        "updated_at": now_iso,
    }


def list_release_workflow_jobs(
    store: ReleaseStore,
    *,
    release_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return durable vendor workflow jobs ordered newest-first."""
    with store.connect() as db:
        stmt = select(release_workflow_jobs).order_by(release_workflow_jobs.c.created_at.desc())
        if release_id is not None:
            stmt = stmt.where(release_workflow_jobs.c.release_id == release_id)
        rows = db.execute(stmt).mappings().all()
        return [
            {
                "job_id": r["job_id"],
                "idempotency_key": r["idempotency_key"],
                "release_id": r["release_id"],
                "stencil_id": r["stencil_id"],
                "source_commit": r["source_commit"],
                "stage": r["stage"],
                "status": r["status"],
                "input_digest": r["input_digest"],
                "manifest_digest": r["manifest_digest"],
                "actor": r["actor"],
                "error_code": r["error_code"],
                "result": json.loads(str(r["result_json"])),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]


def record_promotion_run_receipt(
    db: Connection,
    *,
    release_id: str,
    source_channel: str,
    target_channel: str,
    allowed: bool,
    reason_code: str,
    manifest_digest: str,
    component_digests: Mapping[str, str],
    actor: str,
    occurred_at: str,
) -> dict[str, Any]:
    """Persist an attributable promotion gate evaluation receipt (#2532/#2534)."""
    receipt_id = (
        "promo-rcpt-"
        + hashlib.sha256(
            f"{release_id}:{source_channel}:{target_channel}:{reason_code}:{occurred_at}".encode()
        ).hexdigest()[:16]
    )
    db.execute(
        promotion_run_receipts.insert().values(
            receipt_id=receipt_id,
            release_id=release_id,
            source_channel=source_channel,
            target_channel=target_channel,
            allowed=allowed,
            reason_code=reason_code,
            manifest_digest=manifest_digest,
            component_digests_json=json.dumps(dict(sorted(component_digests.items()))),
            actor=actor,
            occurred_at=occurred_at,
        )
    )
    return {
        "receipt_id": receipt_id,
        "release_id": release_id,
        "source_channel": source_channel,
        "target_channel": target_channel,
        "allowed": allowed,
        "reason_code": reason_code,
        "manifest_digest": manifest_digest,
        "component_digests": dict(sorted(component_digests.items())),
        "actor": actor,
        "occurred_at": occurred_at,
    }


def list_promotion_run_receipts(
    store: ReleaseStore,
    *,
    release_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return persisted promotion gate evaluation receipts."""
    with store.connect() as db:
        stmt = select(promotion_run_receipts).order_by(promotion_run_receipts.c.occurred_at.desc())
        if release_id is not None:
            stmt = stmt.where(promotion_run_receipts.c.release_id == release_id)
        rows = db.execute(stmt).mappings().all()
        return [
            {
                "receipt_id": r["receipt_id"],
                "release_id": r["release_id"],
                "source_channel": r["source_channel"],
                "target_channel": r["target_channel"],
                "allowed": bool(r["allowed"]),
                "reason_code": r["reason_code"],
                "manifest_digest": r["manifest_digest"],
                "component_digests": json.loads(str(r["component_digests_json"])),
                "actor": r["actor"],
                "occurred_at": r["occurred_at"],
            }
            for r in rows
        ]


def build_stencil_routes(
    store: ReleaseStore,
    *,
    grant_issuer_public_keys: Sequence[Ed25519PublicKey],
    resolve_actor: Callable[[Request], str],
) -> list[Route]:
    """Build Starlette routes for Stencil decisions, variants, grants, scoped catalog, and jobs."""

    def _customer_credentials(
        request: Request,
    ) -> tuple[str, str, Mapping[str, Any] | None, str | None]:
        if not grant_issuer_public_keys:
            raise CatalogError(
                "Stencil distribution grant trust keys are not configured on this Release Hub.",
                503,
            )
        inst_id = (request.headers.get("x-fdai-installation-id") or "").strip()
        header_principal = (request.headers.get("x-fdai-customer-principal") or "").strip()
        if (
            "customer_principal" in request.query_params
            or "installation_id" in request.query_params
        ):
            raise CatalogError(
                "Customer identity and installation bindings cannot be in query parameters.",
                400,
            )
        server_actor = resolve_actor(request)
        if not server_actor or server_actor == "local-operator":
            raise CatalogError(
                "Customer catalog/artifact access requires an authenticated Entra/remote session.",
                401,
            )
        if header_principal and header_principal != server_actor:
            raise CatalogError(
                "Authenticated session principal does not match X-FDAI-Customer-Principal.",
                403,
            )
        installed_rel = request.headers.get("x-fdai-installed-release-id") or None
        raw_grant_hdr = request.headers.get("x-fdai-distribution-grant")
        if not raw_grant_hdr:
            raise CatalogError(
                "Customer catalog and artifact access requires a signed X-FDAI-Distribution-Grant.",
                401,
            )
        try:
            presented = load_json_object(
                raw_grant_hdr.encode("utf-8"),
                label="grant header",
                max_bytes=32768,
                strict=True,
            )
        except ValueError as exc:
            raise CatalogError("Malformed X-FDAI-Distribution-Grant header.", 400) from exc
        return inst_id, server_actor, presented, installed_rel

    async def stencil_decisions(request: Request) -> Response:
        return JSONResponse(
            {
                "product_decision_register": list(STENCIL_PRODUCT_DECISION_REGISTER),
                "reviewed_drafts": {
                    key: {
                        "stencil": draft.model_dump(mode="json"),
                        "footprint": evaluate_stencil_footprint(draft),
                    }
                    for key, draft in REVIEWED_STENCIL_DRAFTS.items()
                },
                "feature_mappings": {
                    fid: rec.to_dict() for fid, rec in F01_TO_F15_FEATURE_MAPPING.items()
                },
            }
        )

    async def stencil_variants_route(request: Request) -> Response:
        base_ver = request.query_params.get("base_release_version")
        items = await run_in_threadpool(
            partial(list_stencil_variants, store, base_release_version=base_ver)
        )
        return JSONResponse({"variants": items})

    async def grant_post(request: Request) -> Response:
        body = await request.body()
        try:
            doc = load_json_object(body, label="grant registration", max_bytes=65536, strict=True)
        except ValueError:
            return JSONResponse({"error": "Invalid JSON body."}, status_code=422)
        envelope = doc.get("envelope") if isinstance(doc.get("envelope"), Mapping) else doc
        reason = str(doc.get("reason", "register-or-renew-grant"))
        actor = resolve_actor(request)
        try:
            saved = await run_in_threadpool(
                partial(
                    register_or_renew_grant,
                    store,
                    envelope,  # type: ignore[arg-type]
                    trusted_public_keys=grant_issuer_public_keys,
                    actor=actor,
                    reason=reason,
                )
            )
            return JSONResponse(saved)
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)

    async def grant_get(request: Request) -> Response:
        installation_id = request.path_params["installation_id"]
        record = await run_in_threadpool(get_grant_for_installation, store, installation_id)
        if record is None:
            return JSONResponse({"error": "Grant not found."}, status_code=404)
        events = await run_in_threadpool(
            partial(list_grant_events, store, installation_id=installation_id)
        )
        return JSONResponse({"grant": record, "events": events})

    async def customer_export(request: Request) -> Response:
        try:
            inst_id, principal, presented, installed_rel = _customer_credentials(request)
            scoped = await run_in_threadpool(
                partial(
                    build_scoped_customer_export,
                    store,
                    installation_id=inst_id,
                    customer_principal=principal,
                    trusted_public_keys=grant_issuer_public_keys,
                    presented_envelope=presented,
                    installed_release_id=installed_rel,
                )
            )
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)
        offered = {
            token.strip().removeprefix("W/")
            for token in request.headers.get("if-none-match", "").split(",")
        }
        if scoped.etag in offered:
            return Response(
                status_code=304,
                headers={
                    "ETag": scoped.etag,
                    "X-FDAI-Grant-Scope-Digest": scoped.grant_scope_digest,
                },
            )
        return Response(
            scoped.raw,
            media_type="application/json",
            headers={
                "ETag": scoped.etag,
                "X-FDAI-Export-Signature": scoped.signature,
                "X-FDAI-Export-Key-Id": scoped.key_id,
                "X-FDAI-Grant-Scope-Digest": scoped.grant_scope_digest,
                "X-FDAI-Grant-Scope-Signature": scoped.scope_binding_signature,
                "X-FDAI-Recovery-Only": "true" if scoped.recovery_only else "false",
            },
        )

    async def customer_releases(request: Request) -> Response:
        try:
            inst_id, principal, presented, installed_rel = _customer_credentials(request)
            channel_filter = request.query_params.get("channel")
            stencil_filter = request.query_params.get("stencil_id")
            listing = await run_in_threadpool(
                partial(
                    list_scoped_customer_releases,
                    store,
                    installation_id=inst_id,
                    customer_principal=principal,
                    trusted_public_keys=grant_issuer_public_keys,
                    presented_envelope=presented,
                    installed_release_id=installed_rel,
                    channel_filter=channel_filter,
                    stencil_filter=stencil_filter,
                )
            )
            return JSONResponse(listing)
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)

    async def customer_release_detail(request: Request) -> Response:
        try:
            inst_id, principal, presented, installed_rel = _customer_credentials(request)
            detail = await run_in_threadpool(
                partial(
                    get_scoped_customer_release_detail,
                    store,
                    release_id=request.path_params["release_id"],
                    installation_id=inst_id,
                    customer_principal=principal,
                    trusted_public_keys=grant_issuer_public_keys,
                    presented_envelope=presented,
                    installed_release_id=installed_rel,
                )
            )
            return JSONResponse(detail)
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)

    async def customer_artifact_pull(request: Request) -> Response:
        try:
            inst_id, principal, presented, installed_rel = _customer_credentials(request)
            oci_bytes, resolved_digest, meta = await run_in_threadpool(
                partial(
                    resolve_scoped_customer_artifact_pull,
                    store,
                    component=request.path_params["component"],
                    reference=request.path_params["release_id"],
                    installation_id=inst_id,
                    customer_principal=principal,
                    trusted_public_keys=grant_issuer_public_keys,
                    presented_envelope=presented,
                    installed_release_id=installed_rel,
                )
            )
            return Response(
                content=oci_bytes,
                media_type=OCI_IMAGE_MANIFEST_MEDIA_TYPE,
                headers={
                    "Docker-Distribution-Api-Version": "registry/2.0",
                    "Docker-Content-Digest": resolved_digest,
                    "X-FDAI-Grant-Scope-Digest": str(meta["grant_scope_digest"]),
                },
            )
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)

    async def workflow_jobs_route(request: Request) -> Response:
        rel_id = request.path_params.get("release_id")
        if request.method == "GET":
            jobs = await run_in_threadpool(
                partial(list_release_workflow_jobs, store, release_id=rel_id)
            )
            return JSONResponse({"jobs": jobs})
        body = await request.body()
        try:
            doc = load_json_object(
                body, label="workflow job", max_bytes=2 * 1024 * 1024, strict=True
            )
        except ValueError:
            return JSONResponse({"error": "Invalid workflow job JSON."}, status_code=422)
        raw_manifest_input = doc["manifest"]
        if not isinstance(raw_manifest_input, (Mapping, str)):
            return JSONResponse(
                {"error": "manifest must be a JSON object or string."}, status_code=422
            )
        try:
            res = await run_in_threadpool(
                partial(
                    execute_or_resume_release_workflow_job,
                    store,
                    job_id=str(doc.get("job_id", f"job-{rel_id}")),
                    idempotency_key=str(doc["idempotency_key"]),
                    release_id=str(rel_id or doc["release_id"]),
                    stencil_id=str(doc.get("stencil_id", "standard-sre")),
                    source_commit=str(doc.get("source_commit", "0" * 40)),
                    manifest=raw_manifest_input,
                    label=str(doc.get("label", "")),
                    reason=str(doc.get("reason", "Automated Stencil vendor publication workflow")),
                    actor=resolve_actor(request),
                )
            )
            return JSONResponse(res)
        except (KeyError, TypeError) as exc:
            return JSONResponse(
                {"error": f"Missing required workflow job field: {exc}"}, status_code=422
            )
        except CatalogError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)

    async def promotion_receipts_route(request: Request) -> Response:
        rel_id = request.path_params.get("release_id")
        items = await run_in_threadpool(
            partial(list_promotion_run_receipts, store, release_id=rel_id)
        )
        return JSONResponse({"receipts": items})

    return [
        Route("/v1/stencils/decisions", stencil_decisions, methods=["GET"]),
        Route("/v1/stencil-variants", stencil_variants_route, methods=["GET"]),
        Route("/v1/stencil-grants", grant_post, methods=["POST"]),
        Route("/v1/stencil-grants/{installation_id}", grant_get, methods=["GET"]),
        Route("/v1/customer/catalog/export", customer_export, methods=["GET", "HEAD"]),
        Route("/v1/customer/catalog/releases", customer_releases, methods=["GET"]),
        Route(
            "/v1/customer/catalog/releases/{release_id}", customer_release_detail, methods=["GET"]
        ),
        Route(
            "/v1/customer/artifacts/{release_id}/components/{component}",
            customer_artifact_pull,
            methods=["GET", "HEAD"],
        ),
        Route(
            "/v1/releases/{release_id}/workflow-jobs", workflow_jobs_route, methods=["GET", "POST"]
        ),
        Route(
            "/v1/releases/{release_id}/promotion-receipts",
            promotion_receipts_route,
            methods=["GET"],
        ),
    ]
