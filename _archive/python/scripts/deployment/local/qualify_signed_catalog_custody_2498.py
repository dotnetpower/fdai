#!/usr/bin/env python3
"""Qualify production custody and operational paths for signed catalog roles (#2498).

Exercises and verifies all 4 exit criteria of Issue #2498 (and the corresponding items in
`docs/roadmap-implementation/deployment/lifecycle-releases-and-channels.md`) across SQLite and
isolated loopback PostgreSQL (`port 5433`):
1. Criterion 1: Threshold 2-of-3 independently held offline root ceremony (`root_ceremony.py`) and
   managed non-exportable online role key custody (`ManagedOnlineRoleKey`,
   `ManagedKeyCustodyReceipt`) replacing the single development key.
2. Criterion 2: Audited `bind-catalog` and `rebind-catalog` operations moving a deployed Hub from
   legacy single-key trust to pinned TUF root without a one-off Job override or a hand-deleted
   trust row, preserving the revision floor and approval history.
3. Criterion 3: Full refusal matrix (`review_required`, `unsigned`, `wrong_key`,
   `expired_timestamp` restricting to `recall-rolloff` and demoting operator overrides via AKS
   workload `CatalogFreshnessMonitor`) and one threshold root rotation (`v1 -> v2`) on a Release
   Hub and Lifecycle Hub pair with independent readback.
4. Criterion 4: Genuine Agent and operator enrollment submission on the Release Hub and Lifecycle
   Hub pair, including zone-redundant Agent state volume verification and owner-only key +
   declaration delivery to the Agent.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _rel_src in (
    "packages/service-contracts/src",
    "packages/deployment-cli/src",
    "lifecycle/agent/src",
    "lifecycle/hub/src",
    "lifecycle/release-hub/src",
    "lifecycle/manager/src",
    "services/core-control-plane/src",
):
    _abs_src = str(_REPO_ROOT / _rel_src)
    if _abs_src not in sys.path:
        sys.path.insert(0, _abs_src)

import psycopg  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from fdai.delivery.catalog_freshness import (  # noqa: E402
    CatalogFreshnessConfig,
    CatalogFreshnessMonitor,
)
from fdai.delivery.persistence.state_store_action_promotion import (  # noqa: E402
    PromotionGateStatus,
    StateStoreActionPromotionRegistry,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog  # noqa: E402
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry  # noqa: E402
from fdai.shared.providers.testing.state_store import InMemoryStateStore  # noqa: E402
from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest  # noqa: E402
from fdai_deployment_cli.lifecycle_enrollment import (  # noqa: E402
    installation_key_id,
    raw_installation_public_key,
)
from fdai_deployment_cli.runtime_release import parse_runtime_release_manifest  # noqa: E402
from fdai_lifecycle_manager.runtime_bundle_generator import (  # type: ignore[import-not-found]  # noqa: E402
    generate_fdai_runtime_bundle,
    write_generated_runtime_bundle,
)
from fdai_service_contracts.catalog_roles import root_from_wire  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import conninfo_to_dict  # noqa: E402
from sqlalchemy import Engine, create_engine, select  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from fdai_lifecycle_agent.enrollment_cli import EnrollmentSubmitter, run_enroll  # noqa: E402
from fdai_lifecycle_hub import catalog_integrity_state, schemas  # noqa: E402
from fdai_lifecycle_hub.catalog_integrity import (  # noqa: E402
    IntegrityFloors,
    assess_roles,
)
from fdai_lifecycle_hub.catalog_trust import (  # noqa: E402
    AzureKeyVaultRoleSigningService,
    CatalogTrust,
    ManagedKeyCustodyReceipt,
    ManagedOnlineRoleKey,
    key_id_of,
    parse_metadata,
)
from fdai_lifecycle_hub.enrollment import EnrollmentStatus  # noqa: E402
from fdai_lifecycle_hub.migrations import migrate  # noqa: E402
from fdai_lifecycle_hub.remote_catalog import (  # noqa: E402
    CatalogSource,
    bind_catalog,
    bind_catalog_if_missing,
    trust_events,
    trust_state,
)
from fdai_lifecycle_hub.remote_catalog import metadata as trust_metadata  # noqa: E402
from fdai_lifecycle_hub.signing import (  # noqa: E402
    HubSigningKey,
    verify_key_proof,
)
from fdai_lifecycle_hub.store import HubStore  # noqa: E402
from fdai_release_hub.catalog_roles import CatalogRoleKeys  # noqa: E402
from fdai_release_hub.store import Change, ReleaseStore  # noqa: E402

NOW = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
_SAMPLE_DIGEST = "sha256:" + "d" * 64


def require_validation_postgres_dsn(dsn: str) -> str:
    """Accept only the loopback port-5433 validation PostgreSQL cluster."""

    normalized = dsn.strip().replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    try:
        params = conninfo_to_dict(normalized)
    except Exception as exc:
        raise ValueError("Catalog custody qualification PostgreSQL DSN is malformed") from exc
    if "hostaddr" in params or "service" in params:
        raise ValueError("Catalog custody qualification refuses hostaddr and service overrides")
    effective_host = str(params.get("host") or parsed.hostname or "")
    effective_port = str(params.get("port") or (parsed.port if parsed.port is not None else ""))
    if "," in effective_host or effective_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Catalog custody qualification DSN MUST target a single loopback host")
    if effective_port != "5433" or parsed.port != 5433:
        raise ValueError("Catalog custody qualification requires explicit port 5433")
    return normalized


class _MutableClock:
    def __init__(self, initial: datetime = NOW) -> None:
        self.now = initial

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


_VAULT_WORKER_CODE = """
import base64, hashlib, json, os, sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

keys = {}
for line in sys.stdin:
    req = json.loads(line)
    op = req["op"]
    if op == "ping":
        print(json.dumps({"pid": os.getpid()}), flush=True)
    elif op == "provision":
        priv = Ed25519PrivateKey.generate()
        keys[req["key_uri"]] = (req["role"], priv)
        pub_raw = priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        print(json.dumps({"public_hex": pub_raw.hex(), "pid": os.getpid()}), flush=True)
    elif op == "sign":
        sign_url = req["sign_url"]
        key_uri = sign_url.split("/sign?", 1)[0]
        bound_role, priv = keys[key_uri]
        body = req["body"]
        if body.get("fdai_role") != bound_role:
            raise ValueError("Role mismatch")
        raw_val = str(body["value"])
        padded = raw_val + "=" * (-len(raw_val) % 4)
        msg = base64.urlsafe_b64decode(padded.encode("ascii"))
        sig = priv.sign(msg)
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
        print(
            json.dumps(
                {
                    "kid": key_uri,
                    "value": sig_b64,
                    "message_sha256": hashlib.sha256(msg).hexdigest(),
                }
            ),
            flush=True,
        )
"""


class _IsolatedSubprocessVaultServer:
    """Out-of-process Key Vault / Managed HSM signing server in a separate OS process."""

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-c", _VAULT_WORKER_CODE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.audit_log: list[dict[str, Any]] = []
        ping = self._rpc({"op": "ping"})
        self.pid = int(ping["pid"])
        if self.pid == os.getpid():
            raise RuntimeError("Vault subprocess must have a distinct OS PID")
        self.signing_service = AzureKeyVaultRoleSigningService(
            allowed_vault_hosts=frozenset({"kv-fdai-release-hub.vault.azure.net"}),
            get_bearer_token=lambda: "managed-identity-vault-token-2498",
            post_json=self._post_json,
            signer_process_id=self.pid,
        )

    def _rpc(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("Vault subprocess pipes unavailable")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError("Vault subprocess exited unexpectedly")
        return dict(json.loads(line))

    def _post_json(
        self,
        sign_url: str,
        headers: Mapping[str, str],
        body: Mapping[str, str],
    ) -> Mapping[str, object]:
        if not str(headers.get("Authorization", "")).startswith("Bearer "):
            raise PermissionError("Missing Bearer token")
        resp = self._rpc({"op": "sign", "sign_url": sign_url, "body": dict(body)})
        self.audit_log.append(
            {
                "sign_url": sign_url,
                "role": body.get("fdai_role"),
                "message_sha256": resp["message_sha256"],
                "vault_pid": self.pid,
            }
        )
        return resp

    def provision_key(
        self,
        key_uri: str,
        role: Literal["snapshot", "timestamp"],
    ) -> ManagedOnlineRoleKey:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        resp = self._rpc({"op": "provision", "key_uri": key_uri, "role": role})
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(str(resp["public_hex"])))
        return ManagedOnlineRoleKey(
            key_vault_key_uri=key_uri,
            role=role,
            public_key=pub,
            service=self.signing_service,
        )

    def close(self) -> None:
        if self._proc.stdin is not None:
            self._proc.stdin.close()
        self._proc.terminate()
        self._proc.wait(timeout=5)


@dataclass(frozen=True)
class _ClusterWorkloadSource:
    namespace: str

    def list_entity_workloads(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        deployment = {
            "metadata": {
                "name": "core-control-plane",
                "namespace": self.namespace,
                "generation": 1,
                "labels": {
                    "fdai.io/entity": "fdai-workloads",
                    "app.kubernetes.io/version": "1.5.0",
                },
                "annotations": {"fdai.io/schema-revision": "15"},
            },
            "spec": {
                "replicas": 2,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "core-control-plane",
                                "image": f"registry.example.com/fdai/core@{_SAMPLE_DIGEST}",
                            }
                        ]
                    }
                },
            },
            "status": {
                "observedGeneration": 1,
                "replicas": 2,
                "updatedReplicas": 2,
                "availableReplicas": 2,
                "readyReplicas": 2,
            },
        }
        return [deployment], []


_SERVICES = (
    "core-control-plane",
    "operator-service",
    "document-ingestion-api",
    "document-processing-worker",
    "isolated-executor",
)


def _artifact(role: str, *kinds: str, image: bool = False) -> dict[str, str]:
    record = {kind: f"runtime/{role}/{kind}.bin" for kind in kinds}
    record |= {
        f"{kind}_sha256": hashlib.sha256(f"{role}-{kind}".encode()).hexdigest() for kind in kinds
    }
    if image:
        record["image_digest"] = _SAMPLE_DIGEST
    return record


def _sample_manifest_dict(version: str = "1.5.0") -> dict[str, Any]:
    service = ("archive", "sbom", "provenance")
    return {
        "schema_version": "fdai.runtime-release.v3",
        "source_commit": "2be7053a8756b6cfd9b450c44b38e6c20a7cf457",
        "platform_tag": "linux-x86_64",
        "deployment_bundle_sha256": hashlib.sha256(f"bundle-{version}".encode()).hexdigest(),
        "services": {role: _artifact(role, *service, image=True) for role in _SERVICES},
        "sidecars": {
            role: _artifact(role, *service, image=True) for role in ("clamav", "pgvector")
        },
        "installation_agents": {
            role: _artifact(role, *service, image=True)
            for role in ("infrastructure-agent", "lifecycle-agent")
        },
        "console": _artifact("console", "archive", "sbom"),
        "deployment_support": _artifact("deployment-support", "archive", "sbom"),
        "schema": {"target": 15, "tolerates": {"minimum": 12, "maximum": 16}},
        "capabilities": {"action:scale-service": {"kind": "ActionType", "maximum_mode": "enforce"}},
        "downtime": {"entities": []},
    }


def _publish_release(store: ReleaseStore, version: str, clock: _MutableClock) -> None:
    clock.advance(minutes=1)
    manifest = parse_runtime_release_manifest(canonical_bytes(_sample_manifest_dict(version)))
    manifest_json = canonical_bytes(manifest.to_mapping()).decode("utf-8")
    for action, target_channel in (
        ("register", None),
        ("publish", None),
        ("contribute", "RELEASE"),
    ):
        store.change(
            action,
            version,
            Change(
                revision=store.snapshot()["revision"],
                confirmation=version,
                reason="Catalog custody qualification release",
                manifest=manifest_json if action == "register" else None,
                channel=target_channel,
            ),
        )


def _write_public_pem(path: Path, pub_key: Any) -> Path:
    pem = pub_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path.write_bytes(pem)
    return path


def _run_aks_freshness_override_demotion(
    *,
    metadata_bytes_valid: bytes,
    metadata_bytes_expired: bytes,
    root_key_ids: tuple[str, ...],
    root_threshold: int,
    now_valid: datetime,
    now_expired: datetime,
) -> dict[str, Any]:
    workloads = {
        "core-control-plane": {
            "image": f"registry.example.com/fdai/core@{_SAMPLE_DIGEST}",
            "identity_client_id": "00000000-0000-0000-0000-000000000001",
            "identity_resource_id": (
                "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
                "rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-core"
            ),
            "readiness_path": "/healthz",
            "environment": {"FDAI_ENVIRONMENT": "development"},
        },
        "operator-service": {
            "image": f"registry.example.com/fdai/operator@{_SAMPLE_DIGEST}",
            "identity_client_id": "00000000-0000-0000-0000-000000000002",
            "identity_resource_id": (
                "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
                "rg-example/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-op"
            ),
            "readiness_path": "/healthz",
            "environment": {"FDAI_ENVIRONMENT": "development"},
        },
    }
    scheduled_jobs = {
        "analyzer": {
            "image": f"registry.example.com/fdai/core@{_SAMPLE_DIGEST}",
            "identity_client_id": "00000000-0000-0000-0000-000000000001",
            "identity_resource_id": workloads["core-control-plane"]["identity_resource_id"],
            "schedule": "*/5 * * * *",
            "command": ["fdai-analyzer"],
        },
        "inventory": {
            "image": f"registry.example.com/fdai/core@{_SAMPLE_DIGEST}",
            "identity_client_id": "00000000-0000-0000-0000-000000000001",
            "identity_resource_id": workloads["core-control-plane"]["identity_resource_id"],
            "schedule": "*/15 * * * *",
            "command": ["fdai-inventory"],
        },
    }
    freshness_cfg = {
        "metadata_url": "https://release.example.com/v1/catalog/metadata",
        "root_key_ids": list(root_key_ids),
        "root_threshold": root_threshold,
        "refresh_seconds": 60,
    }
    topology = generate_fdai_runtime_bundle(
        workloads=workloads,
        scheduled_jobs=scheduled_jobs,
        installation_id="inst-2498-aks",
        catalog_freshness=freshness_cfg,
    )
    core_env = topology.prerequisites.config_map_data["core-control-plane-env"]
    config = CatalogFreshnessConfig.from_environment(core_env)
    if config is None:
        raise RuntimeError("AKS core-control-plane-env failed to configure CatalogFreshnessConfig")

    with tempfile.TemporaryDirectory(prefix="fdai-2498-aks-bundle-") as bundle_tmp_raw:
        bundle_tmp = Path(bundle_tmp_raw)
        topo_input_path = bundle_tmp / "topology-input.json"
        topo_input_path.write_text(
            json.dumps(
                {
                    "workloads": workloads,
                    "scheduled_jobs": scheduled_jobs,
                    "catalog_freshness": freshness_cfg,
                }
            ),
            encoding="utf-8",
        )
        topo_input_path.chmod(0o600)
        out_bundle_dir = bundle_tmp / "generated-bundle"
        write_generated_runtime_bundle(
            topology_input_path=topo_input_path,
            destination=out_bundle_dir,
            installation_id="inst-2498-aks",
        )
        cm_file = out_bundle_dir / "prerequisites.json"
        cm_json = json.loads(cm_file.read_text(encoding="utf-8"))
        file_backed_data = (cm_json.get("config_map_data") or {}).get(
            "core-control-plane-env"
        ) or {}
        file_backed_freshness_verified = (
            CatalogFreshnessConfig.from_environment(file_backed_data) == config
        )
        if not file_backed_freshness_verified:
            raise RuntimeError(
                "write_generated_runtime_bundle dropped catalog_freshness ConfigMap env vars"
            )

    async def _exercise() -> dict[str, Any]:
        store = InMemoryStateStore()

        class _OverrideVerifier:
            async def verify_override(self, **_kwargs: object) -> bool:
                return True

        registry = StateStoreActionPromotionRegistry(
            store=store,
            override_authority_verifier=_OverrideVerifier(),
        )
        action_type = next(
            item
            for item in load_action_type_catalog(
                _REPO_ROOT / "rule-catalog" / "action-types",
                schema_registry=PackageResourceSchemaRegistry(),
            )
            if item.name == "remediate.tag-add"
        )
        await registry.consider_operator_override(
            action_type=action_type,
            gate_status=PromotionGateStatus.PASSED,
            gate_evidence_digest="a" * 64,
            approval_receipt_digest="b" * 64,
            operator_principal="owner@example.com",
            reason="Bounded development override for catalog freshness test",
            recorded_at=now_valid,
        )
        mode_before = str(registry.mode_of("remediate.tag-add"))
        current_bytes = metadata_bytes_valid
        current_now = now_valid

        async def _fetch(_url: str) -> bytes:
            return current_bytes

        monitor = CatalogFreshnessMonitor(
            config,
            fetch=_fetch,
            clock=lambda: current_now,
        )
        expired_first = await monitor.apply(registry)
        mode_fresh = str(registry.mode_of("remediate.tag-add"))

        current_bytes = metadata_bytes_expired
        current_now = now_expired
        expired_second = await monitor.apply(registry)
        mode_when_expired = str(registry.mode_of("remediate.tag-add"))

        return {
            "aks_config_map_keys_present": all(
                k in core_env
                for k in (
                    "FDAI_CATALOG_FRESHNESS_METADATA_URL",
                    "FDAI_CATALOG_FRESHNESS_ROOT_KEY_IDS",
                    "FDAI_CATALOG_FRESHNESS_ROOT_THRESHOLD",
                    "FDAI_CATALOG_FRESHNESS_REFRESH_SECONDS",
                )
            )
            and file_backed_freshness_verified,
            "file_backed_bundle_verified": file_backed_freshness_verified,
            "mode_before": mode_before,
            "expired_when_fresh": expired_first,
            "mode_when_fresh": mode_fresh,
            "expired_when_timestamp_expired": expired_second,
            "mode_when_timestamp_expired": mode_when_expired,
            "monitor_status": monitor.status(),
        }

    return asyncio.run(_exercise())


def _run_offline_ceremony_in_subprocess(
    *,
    work_dir: Path,
    version: int,
    snapshot_pub: Path,
    timestamp_pub: Path,
    export_pub: Path,
    signed_at_iso: str,
    expires_at_iso: str,
    previous_root_path: Path | None = None,
) -> tuple[int, bytes]:
    """Run offline root keygen, build, 2-of-3 signing, and verify in an isolated OS process."""

    script = """
import json, os, sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
sys.path[:0] = json.loads(sys.argv[1])
from fdai_lifecycle_hub.catalog_trust import key_id_of
from fdai_lifecycle_hub.signing import load_private_key
from fdai_release_hub import root_ceremony
from fdai_service_contracts.catalog_roles import root_from_wire

cfg = json.loads(sys.argv[2])
work_dir = Path(cfg["work_dir"])
ver = int(cfg["version"])
custodians = [work_dir / f"custodian-{c}" for c in ("a", "b", "c")]
pubs, privs = [], []
for idx, cdir in enumerate(custodians, 1):
    name = f"root-v{ver}-holder-{idx}"
    if root_ceremony.main(["keygen", "--out-dir", str(cdir), "--name", name, "--count", "1"]) != 0:
        raise RuntimeError("keygen failed")
    privs.append(cdir / f"{name}-1.pem")
    pubs.append(cdir / f"{name}-1.pub.pem")

out_path = work_dir / f"root-v{ver}.json"
if root_ceremony.main([
    "build", "--out", str(out_path), "--version", str(ver), "--threshold", "2",
    "--root-public", *[str(p) for p in pubs],
    "--snapshot-public", cfg["snapshot_pub"],
    "--timestamp-public", cfg["timestamp_pub"],
    "--export-public", cfg["export_pub"],
    "--valid-days", "365",
]) != 0:
    raise RuntimeError("build failed")

if ver == 1:
    for p in privs[:2]:
        if root_ceremony.main(["sign", "--record", str(out_path), "--key", str(p)]) != 0:
            raise RuntimeError("sign failed")
    if root_ceremony.main(["verify", "--record", str(out_path)]) != 0:
        raise RuntimeError("verify v1 failed")

rec = root_from_wire(json.loads(out_path.read_bytes()))
det = replace(
    rec,
    signed_at=datetime.fromisoformat(cfg["signed_at_iso"]),
    expires_at=datetime.fromisoformat(cfg["expires_at_iso"]),
    signatures={},
)
signer_paths = list(privs[:2])
if cfg.get("previous_root_path"):
    v1_privs = [cdir / f"root-v1-holder-{idx}-1.pem" for idx, cdir in enumerate(custodians, 1)]
    signer_paths = [*v1_privs[:2], *privs[:2]]

sigs = {}
for sp in signer_paths:
    pk = load_private_key(sp)
    sigs[key_id_of(pk.public_key())] = root_ceremony.sign_role(pk, det.canonical_payload())
signed_rec = replace(det, signatures=sigs)
wire_dict = root_ceremony.root_to_wire(signed_rec)
wire = json.dumps(wire_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
out_path.write_bytes(wire)
if cfg.get("previous_root_path"):
    verify_args = ["verify", "--previous", cfg["previous_root_path"], "--record", str(out_path)]
    if root_ceremony.main(verify_args) != 0:
        raise RuntimeError("verify v1->v2 chain failed")
    for p in [*v1_privs, *privs]:
        p.unlink(missing_ok=True)
print(json.dumps({"pid": os.getpid(), "wire_hex": wire.hex()}))
"""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            json.dumps(sys.path),
            json.dumps(
                {
                    "work_dir": str(work_dir),
                    "version": version,
                    "snapshot_pub": str(snapshot_pub),
                    "timestamp_pub": str(timestamp_pub),
                    "export_pub": str(export_pub),
                    "signed_at_iso": signed_at_iso,
                    "expires_at_iso": expires_at_iso,
                    "previous_root_path": str(previous_root_path) if previous_root_path else None,
                }
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    last_line = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
    res = json.loads(last_line)
    return int(res["pid"]), bytes.fromhex(str(res["wire_hex"]))


def qualify_signed_catalog_custody(
    *,
    release_engine: Engine | None = None,
    hub_engine: Engine | None = None,
    venue: str = "sqlite-in-memory",
) -> dict[str, Any]:
    """Run all 4 exit criteria of #2498 and return a deterministic qualification receipt."""

    clock = _MutableClock(NOW)
    with (
        tempfile.TemporaryDirectory(prefix="fdai-2498-ceremony-") as tmp_raw,
        closing(_IsolatedSubprocessVaultServer()) as custody_service,
    ):
        tmp = Path(tmp_raw)
        snapshot_v1 = custody_service.provision_key(
            "https://kv-fdai-release-hub.vault.azure.net/keys/catalog-snapshot/v1",
            "snapshot",
        )
        timestamp_v1 = custody_service.provision_key(
            "https://kv-fdai-release-hub.vault.azure.net/keys/catalog-timestamp/v1",
            "timestamp",
        )
        export_priv = Ed25519PrivateKey.generate()
        export_signing_key = HubSigningKey(export_priv, epoch=1)

        # Verify non-exportable custody invariants on online role keys.
        non_exportable_verified = False
        try:
            _ = snapshot_v1.private_key
        except PermissionError:
            non_exportable_verified = True
        if not non_exportable_verified or snapshot_v1.exportable or timestamp_v1.exportable:
            raise RuntimeError("Managed online role keys must be non-exportable")

        cross_role_refused = False
        try:
            snapshot_v1.sign(b'{"role":"timestamp"}')
        except ValueError:
            cross_role_refused = True
        if not cross_role_refused:
            raise RuntimeError("Managed online role key must refuse cross-role signing")

        pub_dir = tmp / "public-online-v1"
        pub_dir.mkdir(mode=0o700)
        snap_v1_pub = _write_public_pem(pub_dir / "snapshot-v1.pub.pem", snapshot_v1.public_key)
        ts_v1_pub = _write_public_pem(pub_dir / "timestamp-v1.pub.pem", timestamp_v1.public_key)
        exp_v1_pub = _write_public_pem(pub_dir / "export-v1.pub.pem", export_signing_key.public_key)

        ceremony_pid, root_v1_wire_bytes = _run_offline_ceremony_in_subprocess(
            work_dir=tmp,
            version=1,
            snapshot_pub=snap_v1_pub,
            timestamp_pub=ts_v1_pub,
            export_pub=exp_v1_pub,
            signed_at_iso=NOW.isoformat(),
            expires_at_iso=(NOW + timedelta(days=365)).isoformat(),
        )
        root_v1 = root_from_wire(json.loads(root_v1_wire_bytes))

        role_keys_v1 = CatalogRoleKeys(
            snapshot=snapshot_v1,
            timestamp=timestamp_v1,
            timestamp_ttl=timedelta(hours=24),
            snapshot_ttl=timedelta(days=7),
        )
        if not role_keys_v1.uses_managed_custody:
            raise RuntimeError("CatalogRoleKeys must report uses_managed_custody=True")

        rel_db: Engine | Path = (
            release_engine if release_engine is not None else (tmp / "release.db")
        )
        release_store = ReleaseStore(
            rel_db,
            export_signing_key,
            clock=clock,
            role_keys=role_keys_v1,
        )
        _publish_release(release_store, "1.5.0", clock)
        install_v1 = release_store.install_root(
            root_v1_wire_bytes, actor="vendor-ceremony-operator"
        )
        served_v1 = release_store.signed_metadata()

        custody_receipt = ManagedKeyCustodyReceipt.from_verified_custody(
            root_envelope_bytes=root_v1_wire_bytes,
            independent_root_holders=("custodian-a", "custodian-b", "custodian-c"),
            snapshot_key=snapshot_v1,
            timestamp_key=timestamp_v1,
            export_key_id=key_id_of(export_signing_key.public_key),
            hub_process_id=os.getpid(),
            ceremony_process_id=ceremony_pid,
            vault_signer_process_id=custody_service.pid,
        )

        # Criterion 2: Audited bind-catalog and rebind-catalog operations on Lifecycle Hub.
        own_hub_engine = hub_engine is None
        active_hub_engine = (
            hub_engine
            if hub_engine is not None
            else create_engine(
                f"sqlite:///{tmp / 'lifecycle_hub.db'}",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        )
        try:
            migrate(active_hub_engine, "lifecycle_hub", trust_metadata.create_all)
            legacy_pem = export_signing_key.public_key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
            legacy_source = CatalogSource(
                url="https://release.example.com/v1/catalog/export",
                access="anonymous",
                release_public_key=legacy_pem,
            )
            bind_catalog(
                active_hub_engine,
                legacy_source,
                actor="hub-operator",
                reason="Initial single-key development trust binding",
            )
            with active_hub_engine.begin() as conn:
                conn.execute(
                    trust_state.update()
                    .where(trust_state.c.id == 1)
                    .values(
                        floor=9,
                        approval_revision=9,
                        previous_digest="a" * 64,
                        approval_digest="a" * 64,
                        payload=b"legacy-accepted-bytes",
                    )
                )
            tuf_pin = CatalogTrust(
                mode="tuf",
                root_key_ids=tuple(sorted(root_v1.root_key_ids)),
                root_threshold=2,
            )
            tuf_source = CatalogSource(
                url="https://release.example.com/v1/catalog/export",
                access="anonymous",
                trust=tuf_pin,
            )
            unflagged_rebind_refused = False
            try:
                bind_catalog(
                    active_hub_engine,
                    tuf_source,
                    actor="hub-owner",
                    reason="Attempt switch without rebind flag",
                )
            except ValueError:
                unflagged_rebind_refused = True
            if not unflagged_rebind_refused:
                raise RuntimeError("Switching trust without rebind=True must be refused")

            bind_catalog(
                active_hub_engine,
                tuf_source,
                actor="hub-owner",
                reason="Audited rebind to threshold TUF root",
                rebind=True,
            )
            bind_catalog_if_missing(active_hub_engine, tuf_source, actor="system:migration")
            with active_hub_engine.connect() as conn:
                rebound_state = dict(conn.execute(select(trust_state)).mappings().one())
                audit_rows = [
                    (row.action, row.actor, row.revision)
                    for row in conn.execute(
                        select(trust_events).order_by(trust_events.c.sequence)
                    ).all()
                ]
            if (
                rebound_state["floor"] != 9
                or rebound_state["approval_revision"] != 9
                or rebound_state["payload"] is not None
                or audit_rows
                != [
                    ("source.bound", "hub-operator", 0),
                    ("source.rebound", "hub-owner", 9),
                ]
            ):
                raise RuntimeError("Audited rebind-catalog failed to preserve floor or audit")

            # Criterion 3: Refusal matrix (unsigned, wrong_key, review_required, expired_timestamp),
            # AKS CatalogFreshnessMonitor operator-override demotion, and threshold root rotation.
            bundle_v1 = parse_metadata(served_v1.raw)
            valid_v1_assessment = assess_roles(
                bundle_v1,
                trust=tuf_pin,
                floors=IntegrityFloors(),
                now=clock(),
            )
            with active_hub_engine.begin() as conn:
                catalog_integrity_state.persist(conn, valid_v1_assessment, now=clock())

            # 3a. Unsigned metadata/export refusal
            unsigned_snapshot = replace(bundle_v1.snapshot, signature=b"")
            unsigned_bundle = replace(bundle_v1, snapshot=unsigned_snapshot)
            unsigned_assessment = assess_roles(
                unsigned_bundle,
                trust=tuf_pin,
                floors=IntegrityFloors(),
                now=clock(),
            )

            # 3b. Wrong key / unpinned root refusal
            wrong_pin = CatalogTrust(
                mode="tuf",
                root_key_ids=("ed25519-" + "f" * 64,),
                root_threshold=1,
            )
            wrong_key_assessment = assess_roles(
                bundle_v1,
                trust=wrong_pin,
                floors=IntegrityFloors(),
                now=clock(),
            )

            # 3c. Expired timestamp refusal -> recall-rolloff only + AKS override demotion
            expired_now = clock() + timedelta(hours=25)
            with active_hub_engine.connect() as conn:
                floors_v1 = catalog_integrity_state.floors_of(
                    catalog_integrity_state.read_integrity(conn)
                )
            expired_assessment = assess_roles(
                bundle_v1,
                trust=tuf_pin,
                floors=floors_v1,
                now=expired_now,
            )
            aks_freshness = _run_aks_freshness_override_demotion(
                metadata_bytes_valid=served_v1.raw,
                metadata_bytes_expired=served_v1.raw,
                root_key_ids=tuf_pin.root_key_ids,
                root_threshold=tuf_pin.root_threshold,
                now_valid=clock(),
                now_expired=expired_now,
            )

            # 3d. Threshold Root Rotation (v1 -> v2) with new root keys + rotated managed keys
            snapshot_v2 = custody_service.provision_key(
                "https://kv-fdai-release-hub.vault.azure.net/keys/catalog-snapshot/v2",
                "snapshot",
            )
            timestamp_v2 = custody_service.provision_key(
                "https://kv-fdai-release-hub.vault.azure.net/keys/catalog-timestamp/v2",
                "timestamp",
            )
            pub_dir_v2 = tmp / "public-online-v2"
            pub_dir_v2.mkdir(mode=0o700)
            snap_v2_pub = _write_public_pem(
                pub_dir_v2 / "snapshot-v2.pub.pem", snapshot_v2.public_key
            )
            ts_v2_pub = _write_public_pem(
                pub_dir_v2 / "timestamp-v2.pub.pem", timestamp_v2.public_key
            )

            det_root_v1_file = tmp / "root-v1-deterministic.json"
            det_root_v1_file.write_bytes(root_v1_wire_bytes)

            _ceremony_pid_v2, root_v2_wire_bytes = _run_offline_ceremony_in_subprocess(
                work_dir=tmp,
                version=2,
                snapshot_pub=snap_v2_pub,
                timestamp_pub=ts_v2_pub,
                export_pub=exp_v1_pub,
                signed_at_iso=(NOW + timedelta(minutes=10)).isoformat(),
                expires_at_iso=(NOW + timedelta(days=365, minutes=10)).isoformat(),
                previous_root_path=det_root_v1_file,
            )

            if release_store.roles is None:
                raise RuntimeError("ReleaseStore roles service is not configured")
            release_store.roles.keys = CatalogRoleKeys(snapshot=snapshot_v2, timestamp=timestamp_v2)
            install_v2 = release_store.install_root(
                root_v2_wire_bytes, actor="vendor-ceremony-operator"
            )
            served_v2 = release_store.signed_metadata()
            bundle_v2 = parse_metadata(served_v2.raw)
            rotation_assessment = assess_roles(
                bundle_v2,
                trust=tuf_pin,
                floors=floors_v1,
                now=clock() + timedelta(minutes=15),
            )
            unreviewed_rotation_refused = False
            try:
                with active_hub_engine.begin() as conn:
                    catalog_integrity_state.persist(
                        conn,
                        rotation_assessment,
                        now=clock() + timedelta(minutes=15),
                        accept_rotation=False,
                    )
            except ValueError:
                unreviewed_rotation_refused = True
            if not unreviewed_rotation_refused:
                raise RuntimeError("Unreviewed root rotation must be held for review")

            with active_hub_engine.begin() as conn:
                catalog_integrity_state.persist(
                    conn,
                    rotation_assessment,
                    now=clock() + timedelta(minutes=15),
                    accept_rotation=True,
                )
            with active_hub_engine.connect() as conn:
                persisted_floors = catalog_integrity_state.floors_of(
                    catalog_integrity_state.read_integrity(conn)
                )

            # Criterion 4: Genuine Agent pending enrollment submission + ZRS state PVC
            state_volume_yaml = (_REPO_ROOT / "infra/lifecycle-agent/main.tf").read_text(
                encoding="utf-8"
            )
            zrs_storage_verified = (
                'name = "fdai-lifecycle-agent-state"' in state_volume_yaml
                and 'storage_provisioner    = "disk.csi.azure.com"' in state_volume_yaml
                and 'volume_binding_mode    = "WaitForFirstConsumer"' in state_volume_yaml
            )
            agent_private_dir = tmp / "agent-private"
            agent_private_dir.mkdir(mode=0o700)
            inst_key_path = agent_private_dir / "installation-private.pem"
            inst_priv = Ed25519PrivateKey.generate()
            inst_key_path.write_bytes(
                inst_priv.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            inst_key_path.chmod(0o600)
            inst_key_id = installation_key_id(raw_installation_public_key(inst_priv))

            declaration_path = agent_private_dir / "declaration.json"
            declaration_path.write_text(
                json.dumps(
                    {
                        "schema": "fdai.lifecycle-installation-declaration.v1",
                        "installation_id": "installation-2498-aks",
                        "settings": {
                            "channel": "stable",
                            "version_range": ">=1.4.0 <2.0.0",
                            "region": "westus3",
                            "allowed_regions": ["westus3"],
                            "windows": [
                                {
                                    "start": "02:00:00",
                                    "duration": "PT2H",
                                    "timezone": "UTC",
                                    "allows_downtime": False,
                                }
                            ],
                        },
                        "configuration": {
                            "schema": {"replicas": {"default": 2, "x-fdai-owner": "customer"}},
                            "environment": {},
                            "entity_overrides": [
                                {"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}}
                            ],
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            declaration_path.chmod(0o600)

            hub_store = HubStore(active_hub_engine)
            hub_store.create_schema()

            class _DirectHubSubmitter(EnrollmentSubmitter):
                def submit_enrollment_request(
                    self,
                    installation_id: str,
                    signed_payload: bytes,
                    proof: bytes,
                ) -> None:
                    req = schemas.enrollment_request(signed_payload, proof)
                    if req.installation.installation_id != installation_id:
                        raise ValueError("installation_id mismatch")
                    hub_store.request_enrollment(
                        req,
                        verify=verify_key_proof,
                        now=NOW,
                        requested_by="uami-lifecycle-agent-2498",
                        requested_via="agent",
                    )

            @contextmanager
            def _connect_hub(
                _url: str, _scope: str, _timeout: float
            ) -> Iterator[EnrollmentSubmitter]:
                yield _DirectHubSubmitter()

            enroll_args = argparse.Namespace(
                installation_id="installation-2498-aks",
                installation_key=inst_key_path,
                declaration=declaration_path,
                namespace="fdai-runtime",
                hub_url="https://lchub1.example.com",
                hub_scope="api://fdai-lifecycle-hub/.default",
                timeout_seconds=10.0,
            )
            enroll_exit = run_enroll(
                enroll_args,
                clock=lambda: NOW,
                connect_source=lambda ns: _ClusterWorkloadSource(namespace=ns),
                connect_hub=_connect_hub,
            )
            pending_status = hub_store.enrollment_status("installation-2498-aks")
            pending_list = hub_store.list_pending_enrollments()
            if (
                enroll_exit != 0
                or pending_status is not EnrollmentStatus.PENDING
                or len(pending_list) != 1
                or pending_list[0].requested_via != "agent"
            ):
                raise RuntimeError("Agent pending enrollment submission failed")

            hub_store.approve(
                "installation-2498-aks",
                approver="owner@example.com",
                installation_key_id=inst_key_id,
                now=NOW + timedelta(minutes=5),
            )
            enrolled_status = hub_store.enrollment_status("installation-2498-aks")
            enrolled_detail = hub_store.load("installation-2498-aks")
            if enrolled_status is not EnrollmentStatus.ENROLLED:
                raise RuntimeError("Enrollment approval readback failed")

            expired_recall_rolloff_only = expired_assessment.allowed_plan_types == frozenset(
                {"recall-rolloff"}
            )
            summary = {
                "venue": venue,
                "criteria_verified": {
                    "c01_production_root_and_managed_online_key_custody": (
                        role_keys_v1.uses_managed_custody
                        and non_exportable_verified
                        and cross_role_refused
                        and install_v1["version"] == 1
                        and len(custody_service.audit_log) >= 2
                    ),
                    "c02_audited_bind_and_rebind_catalog": (
                        unflagged_rebind_refused
                        and rebound_state["floor"] == 9
                        and rebound_state["approval_revision"] == 9
                        and rebound_state["payload"] is None
                    ),
                    "c03_refusal_paths_root_rotation_and_aks_freshness": (
                        not unsigned_assessment.verified
                        and not wrong_key_assessment.verified
                        and expired_assessment.expired
                        and expired_recall_rolloff_only
                        and expired_assessment.demote_operator_overrides_to_shadow
                        and aks_freshness["aks_config_map_keys_present"]
                        and aks_freshness["mode_when_fresh"] == "enforce"
                        and aks_freshness["mode_when_timestamp_expired"] == "shadow"
                        and install_v2["version"] == 2
                        and rotation_assessment.verified
                        and rotation_assessment.root_rotation
                        and unreviewed_rotation_refused
                        and persisted_floors.root_version == 2
                    ),
                    "c04_agent_and_operator_enrollment_with_zrs_and_key_delivery": (
                        zrs_storage_verified
                        and enroll_exit == 0
                        and pending_status is EnrollmentStatus.PENDING
                        and enrolled_status is EnrollmentStatus.ENROLLED
                        and "fdai-workloads" in enrolled_detail.reported.entities
                    ),
                },
                "custody_receipt": {
                    "custody_mode": custody_receipt.custody_mode,
                    "root_version": custody_receipt.root_version,
                    "root_threshold": custody_receipt.root_threshold,
                    "independent_root_holders": list(custody_receipt.independent_root_holders),
                    "root_private_keys_entered_hub": custody_receipt.root_private_keys_entered_hub,
                    "snapshot_exportable": custody_receipt.snapshot_exportable,
                    "timestamp_exportable": custody_receipt.timestamp_exportable,
                    "snapshot_key_uri": custody_receipt.snapshot_key_uri,
                    "timestamp_key_uri": custody_receipt.timestamp_key_uri,
                },
                "rebinding_audit_actions": [action for action, _, _ in audit_rows],
                "refusal_and_rotation": {
                    "unsigned_reason": unsigned_assessment.reason_code,
                    "wrong_key_reason": wrong_key_assessment.reason_code,
                    "expired_timestamp_recall_rolloff_only": expired_recall_rolloff_only,
                    "root_rotation_review_required": rotation_assessment.root_rotation,
                    "persisted_root_version": persisted_floors.root_version,
                    "aks_freshness": {
                        "aks_config_map_keys_present": (
                            aks_freshness["aks_config_map_keys_present"]
                        ),
                        "mode_when_fresh": aks_freshness["mode_when_fresh"],
                        "mode_when_timestamp_expired": (
                            aks_freshness["mode_when_timestamp_expired"]
                        ),
                    },
                },
                "enrollment": {
                    "installation_id": "installation-2498-aks",
                    "requested_via": "agent",
                    "initial_status": "pending",
                    "approved_status": "enrolled",
                    "entities": sorted(enrolled_detail.reported.entities),
                    "zrs_storage_verified": zrs_storage_verified,
                },
                "not_production_qualification": True,
                "execution_authority": False,
            }
            if not all(summary["criteria_verified"].values()):
                raise RuntimeError(f"Unverified #2498 criteria: {summary['criteria_verified']}")
            return {
                **summary,
                "qualification_digest": "sha256:" + canonical_digest(summary),
            }
        finally:
            if own_hub_engine:
                active_hub_engine.dispose()


def qualify_signed_catalog_custody_postgres(dsn: str) -> dict[str, Any]:
    """Run #2498 qualification against isolated loopback PostgreSQL (port 5433)."""

    loopback_dsn = require_validation_postgres_dsn(dsn)
    rel_schema = f"rel_hub_2498_{uuid.uuid4().hex[:10]}"
    hub_schema = f"lc_hub_2498_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(loopback_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(rel_schema)))
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(hub_schema)))
        try:
            sa_url = loopback_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
            rel_engine = create_engine(
                sa_url,
                connect_args={"options": f"-c search_path={rel_schema},public"},
            )
            hub_engine = create_engine(
                sa_url,
                connect_args={"options": f"-c search_path={hub_schema},public"},
            )
            try:
                return qualify_signed_catalog_custody(
                    release_engine=rel_engine,
                    hub_engine=hub_engine,
                    venue="isolated-validation-postgres-5433",
                )
            finally:
                rel_engine.dispose()
                hub_engine.dispose()
        finally:
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(rel_schema))
            )
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(hub_schema))
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true")
    args = parser.parse_args()
    sqlite_res = qualify_signed_catalog_custody()
    out: dict[str, Any] = {"sqlite": sqlite_res}
    if args.postgres:
        dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
        if not dsn:
            raise RuntimeError("FDAI_DATABASE_URL is required when --postgres is set")
        out["postgres"] = qualify_signed_catalog_custody_postgres(dsn)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
