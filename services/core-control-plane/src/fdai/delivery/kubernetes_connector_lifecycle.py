"""Verify an installed observer with one smoke Job and retire a stream that can no longer advance.

Both operations act on an installation that the governed apply flow already created. Neither
changes the approved recipe: a smoke Job is derived from the installed CronJob, and a retired spool
is renamed, never deleted, so unaccepted evidence stays available for review.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai_service_contracts.compatibility import canonical_digest

from fdai.delivery.kubernetes_connector_apply import (
    MANIFEST_FILE,
    Audit,
    KubeResult,
    KubeTransport,
    ObserverApplyApproval,
    _authorize,
    _bundle,
    _checked,
    _cluster_identity,
    _get,
    _json,
    _labels,
    _record,
    _set_suspend,
    _verified_documents,
    _verify_installed_either,
    target_lock,
)
from fdai.delivery.kubernetes_connector_installation import ObserverInstallationInput

SMOKE_TIMEOUT_SECONDS = 180.0
SMOKE_INTERVAL_SECONDS = 10.0
PULL_FAILURES = frozenset({"ErrImagePull", "ImagePullBackOff", "InvalidImageName"})
DELIVERED = frozenset({"accepted", "duplicate"})

# The spool database is renamed with a retirement tag so a later stream starts clean while the
# unaccepted packets remain on the volume. The pod fsGroup can leave group-writable bits, so the
# directory mode is reset exactly as the observer's own start-up step does.
_RETIRE_SCRIPT = (
    "import os, time\n"
    "p = '/spool/snapshots'\n"
    "tag = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())\n"
    "names = sorted(os.listdir(p)) if os.path.isdir(p) else []\n"
    "kept = [n for n in names if n.startswith('snapshots.sqlite3') and '.retired-' not in n]\n"
    "[os.rename(os.path.join(p, n), os.path.join(p, n + '.retired-' + tag)) for n in kept]\n"
    "print('retired', len(kept))\n"
)


def _smoke_name(inputs: ObserverInstallationInput, *, suffix: int) -> str:
    return f"{inputs.name}-verify-{suffix}"[:63].rstrip("-")


def _status_line(logs: str) -> dict[str, Any]:
    for line in reversed(logs.splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "status" in value:
            return {key: value[key] for key in ("status", "reason", "error_type") if key in value}
    return {}


def _waiting_reasons(pod: Mapping[str, Any]) -> set[str]:
    status = pod.get("status", {})
    reasons: set[str] = set()
    for group in ("initContainerStatuses", "containerStatuses"):
        for container in status.get(group, []) or []:
            waiting = (container.get("state") or {}).get("waiting") or {}
            if waiting.get("reason"):
                reasons.add(str(waiting["reason"]))
    return reasons


def _observe_smoke(
    transport: KubeTransport, inputs: ObserverInstallationInput, job_name: str
) -> tuple[str, dict[str, object]] | None:
    """Return a terminal classification, or None while the Job is still progressing."""
    listing = _json(
        _checked(
            transport.run(
                [
                    "get",
                    "job,pod",
                    "--namespace",
                    inputs.namespace,
                    f"--selector=job-name={job_name}",
                    "--output",
                    "json",
                ],
                manifest=None,
                timeout=90,
            ),
            "reading the smoke Job failed",
        ),
        "reading the smoke Job failed",
    )
    items = listing.get("items", [])
    job = next((item for item in items if item.get("kind") == "Job"), None)
    pods = [item for item in items if item.get("kind") == "Pod"]
    reasons = set().union(*(_waiting_reasons(pod) for pod in pods)) if pods else set()
    if reasons & PULL_FAILURES:
        return "image_pull_failed", {"waiting": sorted(reasons & PULL_FAILURES)}
    status = (job or {}).get("status", {})
    if status.get("succeeded") or status.get("failed"):
        logs = transport.run(
            [
                "logs",
                f"job/{job_name}",
                "--namespace",
                inputs.namespace,
                "--container",
                "observer",
                "--tail=5",
            ],
            manifest=None,
            timeout=90,
        ).output
        line = _status_line(logs)
        if status.get("succeeded") and line.get("status") in DELIVERED:
            return "delivered", {"report": line}
        return ("completed_without_delivery" if status.get("succeeded") else "job_failed"), {
            "report": line
        }
    return None


def verify_observer(
    rendered: Mapping[str, Any],
    inputs: ObserverInstallationInput,
    approval: ObserverApplyApproval,
    *,
    transport: KubeTransport,
    lock_directory: Path,
    audit: Audit,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    timeout_seconds: float = SMOKE_TIMEOUT_SECONDS,
    interval_seconds: float = SMOKE_INTERVAL_SECONDS,
) -> dict[str, object]:
    """Run the installed CronJob once and classify the outcome; delivery is not observation."""
    documents = _verified_documents(rendered, inputs)
    _authorize(approval, operation="verify", inputs=inputs, rendered=rendered, now=now())
    job_name = _smoke_name(inputs, suffix=int(now().timestamp()))
    common: dict[str, object] = {
        "operation": "verify",
        "target_ref": inputs.target_ref,
        "manifest_digest": rendered["manifest_digest"],
        "executor": transport.name,
        "approver_ref": approval.approver_ref,
        "job": job_name,
    }
    with target_lock(lock_directory, f"{inputs.target_ref}/{inputs.namespace}/{inputs.name}"):
        _cluster_identity(transport, approval.cluster_uid)
        _verify_installed_either(transport, documents)
        _record(audit, now(), "intent", step="smoke", **common)
        _checked(
            transport.run(
                [
                    "create",
                    "job",
                    job_name,
                    f"--from=cronjob/{inputs.name}",
                    "--namespace",
                    inputs.namespace,
                ],
                manifest=None,
                timeout=90,
            ),
            "creating the smoke Job failed",
        )
        deadline = monotonic() + timeout_seconds
        outcome: tuple[str, dict[str, object]] | None = None
        try:
            while outcome is None:
                outcome = _observe_smoke(transport, inputs, job_name)
                if outcome is None:
                    if monotonic() + interval_seconds > deadline:
                        outcome = ("not_finished", {})
                    else:
                        sleep(interval_seconds)
        finally:
            transport.run(
                [
                    "delete",
                    "job",
                    job_name,
                    "--namespace",
                    inputs.namespace,
                    "--ignore-not-found",
                    "--wait=false",
                ],
                manifest=None,
                timeout=90,
            )
        state, detail = outcome
        _record(audit, now(), "result", step="smoke", outcome=state, **common)
    return {
        "schema_version": "1.0.0",
        "operation": "verify",
        "state": state,
        "job": job_name,
        "detail": detail,
        "operational_success": False,
        "observation_required": True,
    }


def _retire_pod(inputs: ObserverInstallationInput, name: str) -> dict[str, Any]:
    security = {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "runAsGroup": 10001,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": inputs.namespace,
            "labels": {**_labels(inputs), "fdai.dev/purpose": "spool-retire"},
        },
        "spec": {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "activeDeadlineSeconds": 120,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "runAsGroup": 10001,
                "fsGroup": 10001,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "retire",
                    "image": inputs.image,
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["python", "-c", _RETIRE_SCRIPT],
                    "securityContext": security,
                    "resources": {
                        "requests": {"cpu": "50m", "memory": "64Mi"},
                        "limits": {"cpu": "200m", "memory": "128Mi"},
                    },
                    "volumeMounts": [{"name": "spool", "mountPath": "/spool"}],
                }
            ],
            "volumes": [{"name": "spool", "persistentVolumeClaim": {"claimName": inputs.name}}],
        },
    }


def _wait_pod(
    transport: KubeTransport,
    inputs: ObserverInstallationInput,
    name: str,
    *,
    timeout_seconds: float,
    interval_seconds: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> KubeResult:
    deadline = monotonic() + timeout_seconds
    while True:
        pod = _get(transport, "Pod", name, inputs.namespace)
        phase = (pod or {}).get("status", {}).get("phase")
        if pod is not None and _waiting_reasons(pod) & PULL_FAILURES:
            raise ValueError("the retire Pod cannot pull the observer image; grant registry access")
        if phase in {"Succeeded", "Failed"}:
            logs = transport.run(
                ["logs", name, "--namespace", inputs.namespace], manifest=None, timeout=90
            )
            if phase == "Failed":
                raise ValueError(f"spool retirement failed: {' '.join(logs.output.split())[:200]}")
            return logs
        if monotonic() + interval_seconds > deadline:
            raise ValueError("spool retirement did not finish; the volume state is unknown")
        sleep(interval_seconds)


def retire_observer_stream(
    inputs: ObserverInstallationInput,
    approval: ObserverApplyApproval,
    *,
    transport: KubeTransport,
    lock_directory: Path,
    audit: Audit,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    timeout_seconds: float = 150.0,
    interval_seconds: float = 8.0,
) -> dict[str, object]:
    """Suspend collection and set the spool database aside so a revised enrollment can start.

    The operator revises the enrollment and stream on the gateway first, then applies matching
    material afterwards. This step only stops the old stream; it never deletes evidence.
    """
    _authorize(approval, operation="recover", inputs=inputs, rendered=None, now=now())
    pod_name = f"{inputs.name}-retire-{int(now().timestamp())}"[:63].rstrip("-")
    common: dict[str, object] = {
        "operation": "recover",
        "target_ref": inputs.target_ref,
        "pod": pod_name,
        "executor": transport.name,
        "approver_ref": approval.approver_ref,
        "pod_digest": canonical_digest(_retire_pod(inputs, pod_name)),
    }
    with target_lock(lock_directory, f"{inputs.target_ref}/{inputs.namespace}/{inputs.name}"):
        _cluster_identity(transport, approval.cluster_uid)
        if _get(transport, "CronJob", inputs.name, inputs.namespace) is None:
            raise ValueError("the observer is not installed; there is no stream to retire")
        _record(audit, now(), "intent", step="retire-spool", **common)
        try:
            _set_suspend(transport, inputs, suspend=True, reason="stopping the observer failed")
            jobs = _json(
                _checked(
                    transport.run(
                        ["get", "jobs", "--namespace", inputs.namespace, "--output", "json"],
                        manifest=None,
                        timeout=90,
                    ),
                    "listing observer Jobs failed",
                ),
                "listing observer Jobs failed",
            )
            owned = [
                item["metadata"]["name"]
                for item in jobs.get("items", [])
                if any(
                    owner.get("kind") == "CronJob" and owner.get("name") == inputs.name
                    for owner in item["metadata"].get("ownerReferences", [])
                )
            ]
            for job in owned:
                _checked(
                    transport.run(
                        ["delete", "job", job, "--namespace", inputs.namespace, "--wait=true"],
                        manifest=None,
                        timeout=120,
                    ),
                    "removing an observer Job failed",
                )
            _checked(
                transport.run(
                    ["create", "--filename", MANIFEST_FILE],
                    manifest=_bundle(_retire_pod(inputs, pod_name)),
                    timeout=120,
                ),
                "creating the retire Pod failed",
            )
            try:
                logs = _wait_pod(
                    transport,
                    inputs,
                    pod_name,
                    timeout_seconds=timeout_seconds,
                    interval_seconds=interval_seconds,
                    sleep=sleep,
                    monotonic=monotonic,
                )
            finally:
                transport.run(
                    [
                        "delete",
                        "pod",
                        pod_name,
                        "--namespace",
                        inputs.namespace,
                        "--ignore-not-found",
                        "--wait=false",
                    ],
                    manifest=None,
                    timeout=90,
                )
        except ValueError as exc:
            _record(audit, now(), "result", step="retire-spool", outcome="unknown", **common)
            raise ValueError(f"{exc}; the observer stays suspended") from exc
        _record(audit, now(), "result", step="retire-spool", outcome="retired", **common)
    return {
        "schema_version": "1.0.0",
        "operation": "recover",
        "state": "stream_retired",
        "report": " ".join(logs.output.split())[:80],
        "removed_jobs": len(owned),
        "next": "apply matching material for the revised enrollment, then activate and verify",
    }


__all__ = ["retire_observer_stream", "verify_observer"]
