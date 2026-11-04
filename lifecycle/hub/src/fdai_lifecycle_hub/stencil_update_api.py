"""Durable Lifecycle Hub persistence and API routes for Stencil reconciliation (#2533/#2535)."""

from __future__ import annotations

import json
import os
from base64 import b64decode
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from functools import partial
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.lifecycle_promotion import BoundaryRegistryMirror
from fdai_deployment_cli.lifecycle_stencil_grant import (
    StencilBindingError,
    verify_stencil_distribution_grant,
)
from sqlalchemy import Column, MetaData, String, Table, Text, select
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_lifecycle_hub.domain import Clock
from fdai_lifecycle_hub.stencil_update_flow import (
    StencilInstallationState,
    StencilUpdateReconciliationResult,
    build_customer_stencil_readiness_view,
    reconcile_stencil_update,
)
from fdai_lifecycle_hub.store import HubStore

stencil_hub_metadata = MetaData()

stencil_installation_states = Table(
    "stencil_installation_states",
    stencil_hub_metadata,
    Column("installation_id", String(128), primary_key=True),
    Column("customer_principal", String(160), nullable=False),
    Column("state_json", Text, nullable=False),
    Column("readiness_view_json", Text, nullable=False),
    Column("updated_at", String(40), nullable=False),
)


def ensure_stencil_hub_tables(store: HubStore) -> None:
    """Ensure the `stencil_installation_states` table exists on `store.engine`."""
    stencil_hub_metadata.create_all(store.engine)


def save_stencil_installation_state(
    store: HubStore,
    state: StencilInstallationState,
    *,
    readiness_view: dict[str, Any] | None = None,
    updated_at: str,
    preserve_server_pins: bool = False,
) -> dict[str, Any]:
    """Persist `StencilInstallationState` and its readiness projection transactionally."""
    ensure_stencil_hub_tables(store)
    with store.engine.begin() as db:
        existing = (
            db.execute(
                select(stencil_installation_states).where(
                    stencil_installation_states.c.installation_id == state.installation_id
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            if existing["customer_principal"] != state.customer_principal:
                raise PermissionError(
                    "customer_principal is immutable once bound to an installation_id."
                )
            if preserve_server_pins:
                stored_raw = json.loads(str(existing["state_json"]))
                state = replace(
                    state,
                    pinned_grant_id=str(stored_raw.get("pinned_grant_id") or ""),
                    pinned_grant_revision=int(stored_raw.get("pinned_grant_revision") or 0),
                    pinned_grant_scope_digest=str(
                        stored_raw.get("pinned_grant_scope_digest") or ""
                    ),
                )
        view = readiness_view or build_customer_stencil_readiness_view(
            state,
            classification="up-to-date",
            executable_readiness=state.agent_active and state.inputs_staged,
            proposed_release_id=None,
            proposed_stencil_id=None,
            changed_features={
                "added_panels": [],
                "removed_panels": [],
                "added_workloads": [],
                "removed_workloads": [],
                "added_loops": [],
                "removed_loops": [],
            },
            blocker_code=None,
            blocker_detail=None,
            decision_owner="none-automatic",
        )
        state_dict = asdict(state)
        state_dict["runtime_bundle_workloads"] = list(state.runtime_bundle_workloads)
        state_dict["runtime_bundle_component_images"] = dict(state.runtime_bundle_component_images)
        if existing is not None:
            db.execute(
                stencil_installation_states.update()
                .where(stencil_installation_states.c.installation_id == state.installation_id)
                .values(
                    customer_principal=state.customer_principal,
                    state_json=json.dumps(state_dict, sort_keys=True),
                    readiness_view_json=json.dumps(view, sort_keys=True),
                    updated_at=updated_at,
                )
            )
        else:
            db.execute(
                stencil_installation_states.insert().values(
                    installation_id=state.installation_id,
                    customer_principal=state.customer_principal,
                    state_json=json.dumps(state_dict, sort_keys=True),
                    readiness_view_json=json.dumps(view, sort_keys=True),
                    updated_at=updated_at,
                )
            )
    return {"state": state_dict, "readiness_view": view, "updated_at": updated_at}


def load_stencil_installation_state(
    store: HubStore,
    installation_id: str,
) -> tuple[StencilInstallationState, dict[str, Any]] | None:
    """Load persisted `(StencilInstallationState, readiness_view)` for `installation_id`."""
    ensure_stencil_hub_tables(store)
    with store.engine.begin() as db:
        row = (
            db.execute(
                select(stencil_installation_states).where(
                    stencil_installation_states.c.installation_id == installation_id
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        raw = json.loads(str(row["state_json"]))
        raw["runtime_bundle_workloads"] = tuple(raw.get("runtime_bundle_workloads") or ())
        raw["runtime_bundle_component_images"] = dict(
            raw.get("runtime_bundle_component_images") or {}
        )
        state = StencilInstallationState(**raw)
        view = json.loads(str(row["readiness_view_json"]))
        return state, view


def run_persisted_stencil_reconciliation(
    store: HubStore,
    installation_id: str,
    *,
    scoped_export_raw: bytes,
    export_signature: str,
    export_scope_signature: str,
    export_public_key: Ed25519PublicKey,
    grant_envelope: dict[str, Any],
    grant_issuer_public_keys: tuple[Ed25519PublicKey, ...],
    clock: Clock,
) -> StencilUpdateReconciliationResult:
    """Load persisted installation state, run `reconcile_stencil_update`, and persist result."""
    loaded = load_stencil_installation_state(store, installation_id)
    if loaded is None:
        raise LookupError(f"Stencil installation state not found for {installation_id!r}.")
    current_state, _old_view = loaded
    now = clock()
    result = reconcile_stencil_update(
        current_state,
        scoped_export_raw=scoped_export_raw,
        export_signature=export_signature,
        export_public_key=export_public_key,
        grant_envelope=grant_envelope,
        grant_issuer_public_keys=grant_issuer_public_keys,
        mirror=BoundaryRegistryMirror(),
        expected_grant_scope_digest=None,
        export_scope_signature=export_scope_signature,
        now=now,
    )
    save_stencil_installation_state(
        store,
        result.updated_state,
        readiness_view=dict(result.readiness_view),
        updated_at=now.isoformat(),
    )
    return result


def _parse_ed25519_pub(raw_hex_or_b64: str) -> Ed25519PublicKey:
    cleaned = raw_hex_or_b64.strip()
    if len(cleaned) == 64:
        return Ed25519PublicKey.from_public_bytes(bytes.fromhex(cleaned))
    if cleaned.startswith("-----BEGIN"):
        loaded = serialization.load_pem_public_key(cleaned.encode("utf-8"))
        if not isinstance(loaded, Ed25519PublicKey):
            raise TypeError("Expected Ed25519PublicKey PEM.")
        return loaded
    return Ed25519PublicKey.from_public_bytes(b64decode(cleaned, validate=True))


def load_env_stencil_trust_keys(
    environ: Mapping[str, str] | None = None,
) -> tuple[Ed25519PublicKey | None, tuple[Ed25519PublicKey, ...]]:
    """Load server-configured Stencil export and grant-issuer public keys from environment."""
    env = environ if environ is not None else os.environ
    raw_export = env.get("FDAI_STENCIL_EXPORT_PUBLIC_KEY", "").strip()
    export_pub = _parse_ed25519_pub(raw_export) if raw_export else None
    raw_issuers = env.get("FDAI_STENCIL_GRANT_ISSUER_PUBLIC_KEYS", "").strip()
    issuer_pubs = tuple(
        _parse_ed25519_pub(token)
        for token in (raw_issuers.split(",") if raw_issuers else [])
        if token.strip()
    )
    return export_pub, issuer_pubs


def stencil_update_routes(
    store: HubStore,
    clock: Clock,
    *,
    operator_resolver: Callable[[Request], str | None] | None = None,
    export_public_key: Ed25519PublicKey | None = None,
    grant_issuer_public_keys: tuple[Ed25519PublicKey, ...] = (),
) -> list[Route]:
    """Build Starlette routes for Lifecycle Hub Stencil state, reconciliation, and readiness."""
    env_export_pub, env_grant_pubs = load_env_stencil_trust_keys()
    eff_export_pub = export_public_key or env_export_pub
    eff_grant_pubs = grant_issuer_public_keys or env_grant_pubs

    def _require_principal(request: Request, expected_principal: str) -> Response | None:
        active = operator_resolver(request) if operator_resolver is not None else None
        if not active or active == "local-operator":
            return JSONResponse(
                {"error": "Authenticated Entra or remote session is required."},
                status_code=401,
            )
        accepted = {active, f"entra:{active}"}
        hdr = (request.headers.get("x-fdai-customer-principal") or "").strip()
        if hdr and hdr not in accepted:
            return JSONResponse(
                {"error": "Authenticated session principal does not match header."},
                status_code=403,
            )
        if expected_principal not in accepted:
            return JSONResponse(
                {"error": "Authenticated principal does not match customer_principal."},
                status_code=403,
            )
        return None

    async def put_stencil_state(request: Request) -> Response:
        installation_id = request.path_params["installation_id"]
        existing_loaded = await run_in_threadpool(
            load_stencil_installation_state, store, installation_id
        )
        if existing_loaded is not None:
            if denied := _require_principal(request, existing_loaded[0].customer_principal):
                return denied
        body = await request.body()
        try:
            doc = load_json_object(body, label="stencil state", max_bytes=65536, strict=True)
            if any(
                k in doc
                for k in (
                    "pinned_grant_id",
                    "pinned_grant_revision",
                    "pinned_grant_scope_digest",
                )
            ):
                return JSONResponse(
                    {
                        "error": (
                            "Server-pinned grant fields are derived from verified grants and "
                            "cannot be set by the caller."
                        )
                    },
                    status_code=422,
                )
            raw_grant_env = doc.pop("grant_envelope", None)
            doc["installation_id"] = installation_id
            doc["runtime_bundle_workloads"] = tuple(doc.get("runtime_bundle_workloads") or ())
            doc["runtime_bundle_component_images"] = dict(
                doc.get("runtime_bundle_component_images") or {}
            )
            state = StencilInstallationState(**doc)
        except Exception as exc:
            return JSONResponse({"error": f"Invalid Stencil state: {exc}"}, status_code=422)
        if existing_loaded is not None:
            if state.customer_principal != existing_loaded[0].customer_principal:
                return JSONResponse(
                    {"error": "customer_principal cannot be changed for an existing installation."},
                    status_code=403,
                )
        else:
            if denied := _require_principal(request, state.customer_principal):
                return denied
            if not eff_grant_pubs:
                return JSONResponse(
                    {"error": "Stencil grant issuer trust keys are not configured."},
                    status_code=503,
                )
            if not isinstance(raw_grant_env, dict):
                return JSONResponse(
                    {
                        "error": (
                            "Initial Stencil state provisioning requires a signed grant_envelope."
                        )
                    },
                    status_code=403,
                )
            try:
                verified_init = verify_stencil_distribution_grant(
                    raw_grant_env,
                    trusted_public_keys=eff_grant_pubs,
                    expected_installation_id=installation_id,
                    expected_customer_principal=state.customer_principal,
                    now=clock(),
                )
            except StencilBindingError as exc:
                return JSONResponse(
                    {"error": f"Initial grant verification failed ({exc.reason_code}): {exc}"},
                    status_code=403,
                )
            state = replace(
                state,
                pinned_grant_id=verified_init.grant.grant_id,
                pinned_grant_revision=verified_init.grant.revision,
                pinned_grant_scope_digest=verified_init.grant.scope_digest,
            )
        saved = await run_in_threadpool(
            partial(
                save_stencil_installation_state,
                store,
                state,
                updated_at=clock().isoformat(),
                preserve_server_pins=(existing_loaded is not None),
            )
        )
        return JSONResponse(saved)

    async def get_stencil_readiness(request: Request) -> Response:
        installation_id = request.path_params["installation_id"]
        loaded = await run_in_threadpool(load_stencil_installation_state, store, installation_id)
        if loaded is None:
            return JSONResponse({"error": "Stencil installation state not found."}, status_code=404)
        state, view = loaded
        if denied := _require_principal(request, state.customer_principal):
            return denied
        return JSONResponse({"installation_id": installation_id, "readiness_view": view})

    async def post_stencil_reconcile(request: Request) -> Response:
        if eff_export_pub is None or not eff_grant_pubs:
            return JSONResponse(
                {
                    "error": (
                        "Lifecycle Hub Stencil reconciliation requires server-configured "
                        "export_public_key and grant_issuer_public_keys."
                    )
                },
                status_code=503,
            )
        installation_id = request.path_params["installation_id"]
        loaded = await run_in_threadpool(load_stencil_installation_state, store, installation_id)
        if loaded is None:
            return JSONResponse({"error": "Stencil installation state not found."}, status_code=404)
        state, _view = loaded
        if denied := _require_principal(request, state.customer_principal):
            return denied
        body = await request.body()
        try:
            doc = load_json_object(
                body, label="stencil reconcile", max_bytes=2 * 1024 * 1024, strict=True
            )
            if any(
                k in doc
                for k in (
                    "export_public_key",
                    "grant_issuer_public_keys",
                    "expected_grant_scope_digest",
                )
            ):
                return JSONResponse(
                    {
                        "error": (
                            "Trust roots and expected scope digests are server-owned and cannot "
                            "be supplied by the caller."
                        )
                    },
                    status_code=422,
                )
            raw_export = str(doc["scoped_export_raw"]).encode("utf-8")
            export_sig = str(doc["export_signature"])
            export_scope_sig = str(doc["export_scope_signature"])
            raw_grant_env = doc["grant_envelope"]
            if not isinstance(raw_grant_env, dict):
                raise TypeError("grant_envelope must be a JSON object.")
            grant_env = dict(raw_grant_env)
        except Exception as exc:
            return JSONResponse({"error": f"Invalid reconcile request: {exc}"}, status_code=422)

        result = await run_in_threadpool(
            partial(
                run_persisted_stencil_reconciliation,
                store,
                installation_id,
                scoped_export_raw=raw_export,
                export_signature=export_sig,
                export_scope_signature=export_scope_sig,
                export_public_key=eff_export_pub,
                grant_envelope=grant_env,
                grant_issuer_public_keys=eff_grant_pubs,
                clock=clock,
            )
        )
        return JSONResponse(
            {
                "installation_id": result.installation_id,
                "classification": result.classification,
                "executable_readiness": result.executable_readiness,
                "plan_issued": result.plan_issued,
                "plan_type": result.plan_type,
                "plan_digest": result.plan_digest,
                "applied_in_window": result.applied_in_window,
                "current_release_id": result.current_release_id,
                "current_stencil_id": result.current_stencil_id,
                "proposed_release_id": result.proposed_release_id,
                "proposed_stencil_id": result.proposed_stencil_id,
                "blocker_code": result.blocker_code,
                "inter_party_handoff_count": result.inter_party_handoff_count,
                "additional_customer_apply_clicks": result.additional_customer_apply_clicks,
                "outside_window_mutations": result.outside_window_mutations,
                "readiness_view": dict(result.readiness_view),
            }
        )

    return [
        Route(
            "/v1/installations/{installation_id}/stencil-state",
            put_stencil_state,
            methods=["PUT"],
        ),
        Route(
            "/v1/installations/{installation_id}/stencil-readiness",
            get_stencil_readiness,
            methods=["GET"],
        ),
        Route(
            "/v1/installations/{installation_id}/stencil-reconcile",
            post_stencil_reconcile,
            methods=["POST"],
        ),
    ]
