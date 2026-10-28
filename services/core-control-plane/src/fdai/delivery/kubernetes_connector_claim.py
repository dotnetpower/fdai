"""Single-use pre-effect claims and a cluster-wide lease for observer installation operations.

A claim is written and synced before the first mutating call. A claim without an outcome means an
earlier attempt may have changed the cluster, so the same approval is never replayed: the operator
verifies the cluster and issues a fresh approval. The lease serializes operations across hosts.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fdai_service_contracts.cluster_connector import connector_time

LEASE_SECONDS = 600
MANIFEST_FILE = "@manifest"


@dataclass(frozen=True, slots=True)
class Claim:
    """One open claim; settling it records the observed outcome and never reopens it."""

    path: Path

    def settle(self, outcome: str, *, at: datetime) -> None:
        _append(self.path, {"outcome": outcome, "at": connector_time(at).isoformat()})


def _append(path: Path, record: dict[str, object]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, (json.dumps(record, sort_keys=True) + "\n").encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def claim_effect(directory: Path, key: str, *, operation: str, at: datetime) -> Claim:
    """Create the claim exclusively before any mutating call, or refuse the replay."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"claim-{hashlib.sha256(key.encode()).hexdigest()[:32]}.json"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        lines = path.read_text().splitlines()
        settled = len(lines) > 1 and json.loads(lines[-1]).get("outcome") != "unknown"
        raise ValueError(
            f"this {operation} approval was already used"
            + (
                "; request a fresh approval"
                if settled
                else " and its outcome is unknown; run verify against the cluster, then request "
                "a fresh approval. The same approval is never replayed"
            )
        ) from None
    try:
        os.write(
            descriptor,
            (
                json.dumps(
                    {"claim": operation, "at": connector_time(at).isoformat()}, sort_keys=True
                )
                + "\n"
            ).encode(),
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return Claim(path)


def _lease(
    namespace: str, name: str, holder: str, now: datetime, version: str | None
) -> dict[str, Any]:
    stamp = connector_time(now).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    metadata: dict[str, Any] = {
        "name": lease_name(name),
        "namespace": namespace,
        "labels": {"app.kubernetes.io/managed-by": "fdai-observer-install"},
    }
    if version is not None:
        metadata["resourceVersion"] = version
    return {
        "apiVersion": "coordination.k8s.io/v1",
        "kind": "Lease",
        "metadata": metadata,
        "spec": {
            "holderIdentity": holder,
            "leaseDurationSeconds": LEASE_SECONDS,
            "acquireTime": stamp,
            "renewTime": stamp,
        },
    }


def lease_name(name: str) -> str:
    return "fdai-install-" + hashlib.sha256(name.encode()).hexdigest()[:16]


def _expired(lease: dict[str, Any], now: datetime) -> bool:
    spec = lease.get("spec", {})
    try:
        renewed = connector_time(str(spec["renewTime"]).replace("Z", "+00:00"))
        duration = int(spec["leaseDurationSeconds"])
    except (KeyError, ValueError, TypeError):
        return False
    return connector_time(now) >= renewed + timedelta(seconds=duration)


def _read(transport: Any, kind: str, name: str, namespace: str | None) -> dict[str, Any] | None:
    args = ["get", kind, name, "--output", "json", "--ignore-not-found"]
    if namespace is not None:
        args += ["--namespace", namespace]
    result = transport.run(args, manifest=None, timeout=90)
    if result.exit_code != 0:
        raise ValueError(f"reading {kind} failed (exit {result.exit_code})")
    if not result.output.strip():
        return None
    value = json.loads(result.output)
    if not isinstance(value, dict):
        raise ValueError(f"reading {kind} failed: the response is not an object")
    return value


@contextmanager
def cluster_lock(
    transport: Any, *, namespace: str, name: str, holder: str, now: datetime
) -> Iterator[str]:
    """Hold a Lease in the observer namespace; yield the lock scope that is in force.

    Before the namespace exists there is nothing to lock in the cluster, so only the host lock
    serializes the first installation and the scope is reported as `host`.
    """
    if _read(transport, "namespace", namespace, None) is None:
        yield "host"
        return
    body = _lease(namespace, name, holder, now, None)
    payload = json.dumps(body).encode()
    created = transport.run(["create", "--filename", MANIFEST_FILE], manifest=payload, timeout=90)
    if created.exit_code != 0:
        live = _read(transport, "lease", lease_name(name), namespace)
        if live is None or not _expired(live, now):
            owner = (live or {}).get("spec", {}).get("holderIdentity", "unknown")
            raise ValueError(
                f"another observer installation operation holds the cluster lock ({owner})"
            )
        version = str(live.get("metadata", {}).get("resourceVersion", ""))
        taken = transport.run(
            ["replace", "--filename", MANIFEST_FILE],
            manifest=json.dumps(_lease(namespace, name, holder, now, version)).encode(),
            timeout=90,
        )
        if taken.exit_code != 0:
            raise ValueError("the expired cluster lock could not be taken over safely")
    try:
        yield "cluster"
    finally:
        transport.run(
            [
                "delete",
                "lease",
                lease_name(name),
                "--namespace",
                namespace,
                "--ignore-not-found",
                "--wait=false",
            ],
            manifest=None,
            timeout=90,
        )
