"""Execute one content-addressed AKS Job from a reviewed CronJob template."""

from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fdai_deployment_cli.aks_job_execution import (
    AksOneShotJob,
    aks_job_contract_digest,
    job_terminal_state,
    materialize_cronjob_execution,
    validate_existing_job,
)
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.standalone_host_state import (
    private_json,
    replace_or_verify_private_json,
)

_NAMESPACE = "fdai-runtime"
_CHECKPOINT_SCHEMA = "fdai.aks-one-shot-execution-checkpoint.v1"
_GUID = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
_MANAGED_IDENTITY_ID = re.compile(
    r"^/subscriptions/([0-9a-f-]{36})/resourcegroups/[^/]+/providers/"
    r"microsoft[.]managedidentity/userassignedidentities/[^/]+$"
)
_WORKLOAD_IDENTITY_ANNOTATION_PREFIX = "azure.workload.identity/"
_JOB_TTL_SECONDS = 3_600
_DISPATCH_ABSENCE_MARGIN = timedelta(seconds=60)
_CHECKPOINT_CLOCK_SKEW = timedelta(seconds=60)


def protected_service_account_binding(
    scheduled_job: object,
    *,
    template_name: str,
    namespace: str,
    tenant_id: str,
    subscription_id: str,
) -> dict[str, object]:
    """Retain the reviewed UAMI binding independently from the live ServiceAccount."""

    if not isinstance(scheduled_job, dict) or any(
        not isinstance(key, str) for key in scheduled_job
    ):
        raise ValueError("protected AKS scheduled job identity binding is invalid")
    client_id = scheduled_job.get("identity_client_id")
    resource_id = scheduled_job.get("identity_resource_id")
    if (
        not isinstance(client_id, str)
        or _GUID.fullmatch(client_id) is None
        or not isinstance(resource_id, str)
        or _GUID.fullmatch(tenant_id) is None
        or _GUID.fullmatch(subscription_id) is None
        or re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", template_name) is None
        or re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace) is None
    ):
        raise ValueError("protected AKS scheduled job identity binding is invalid")
    normalized_resource_id = resource_id.casefold()
    resource_match = _MANAGED_IDENTITY_ID.fullmatch(normalized_resource_id)
    if resource_match is None or resource_match.group(1) != subscription_id.casefold():
        raise ValueError("protected AKS scheduled job identity resource is invalid")
    normalized_client_id = client_id.casefold()
    normalized_tenant_id = tenant_id.casefold()
    material: dict[str, object] = {
        "schema_version": "fdai.aks-service-account-binding.v1",
        "service_account_name": f"{template_name}-job",
        "namespace": namespace,
        "identity_client_id": normalized_client_id,
        "identity_resource_id": normalized_resource_id,
        "tenant_id": normalized_tenant_id,
        "subscription_id": subscription_id.casefold(),
        "annotations": {
            "azure.workload.identity/client-id": normalized_client_id,
            "azure.workload.identity/tenant-id": normalized_tenant_id,
        },
    }
    return {**material, "binding_digest": canonical_digest(material)}


def execute_aks_cronjob_once(
    context: dict[str, Any],
    work_dir: Path,
    *,
    template_name: str,
    purpose: str,
    expected_container_name: str,
    expected_image: str,
    expected_command: tuple[str, ...],
    expected_service_account: str,
    args: tuple[str, ...],
    environment: dict[str, str],
    require_suspended: bool,
    timeout_seconds: int,
) -> AksOneShotJob:
    """Create once, or verify and observe the exact retained Kubernetes Job."""

    kubeconfig = Path(str(context.get("kubeconfig", "")))
    if not kubeconfig.is_file():
        raise ValueError("AKS kubeconfig is unavailable for one-shot execution")
    read_private_bytes(kubeconfig, max_bytes=1024 * 1024)
    cronjob = _json_capture(
        (
            "kubectl",
            "get",
            "cronjob",
            template_name,
            "--namespace",
            _NAMESPACE,
            "--output",
            "json",
            f"--kubeconfig={kubeconfig}",
        ),
        cwd=work_dir,
        timeout=60,
        reason=f"AKS {purpose} CronJob template is unavailable",
    )
    protected_template_digest = _protected_template_digest(
        context,
        template_name=template_name,
    )
    identity_binding = _protected_identity_binding(
        context,
        template_name=template_name,
        expected_service_account=expected_service_account,
    )
    _verify_service_account(
        _json_capture(
            (
                "kubectl",
                "get",
                "serviceaccount",
                expected_service_account,
                "--namespace",
                _NAMESPACE,
                "--output",
                "json",
                f"--kubeconfig={kubeconfig}",
            ),
            cwd=work_dir,
            timeout=60,
            reason=f"AKS {purpose} ServiceAccount identity is unavailable",
        ),
        expected=identity_binding,
    )
    identity_binding_digest = str(identity_binding["binding_digest"])
    execution = materialize_cronjob_execution(
        cronjob,
        purpose=purpose,
        source_revision=str(context.get("source_commit", "")),
        target_binding=str(context.get("target_binding", "")),
        expected_template_name=template_name,
        expected_container_name=expected_container_name,
        expected_image=expected_image,
        expected_command=expected_command,
        expected_service_account=expected_service_account,
        args=args,
        environment=environment,
        require_suspended=require_suspended,
        protected_template_digest=protected_template_digest,
        protected_identity_binding_digest=identity_binding_digest,
    )
    manifest_path = work_dir / f"{execution.name}.json"
    replace_or_verify_private_json(manifest_path, execution.manifest)
    checkpoint = _checkpoint_binding(
        execution,
        protected_template_digest=protected_template_digest,
        protected_identity_binding_digest=identity_binding_digest,
    )
    prepared_path = work_dir / f"{execution.name}.prepared.json"
    dispatch_intent_path = work_dir / f"{execution.name}.dispatch-intent.json"
    dispatched_path = work_dir / f"{execution.name}.dispatched.json"
    ambiguous_path = work_dir / f"{execution.name}.dispatch-ambiguous.json"
    terminal_path = work_dir / f"{execution.name}.terminal.json"
    replace_or_verify_private_json(
        prepared_path,
        _checkpoint_record(checkpoint, state="prepared"),
    )
    if terminal_path.exists():
        outcome = _terminal_checkpoint_outcome(
            private_json(terminal_path, f"AKS {purpose} terminal checkpoint"),
            checkpoint=checkpoint,
            execution=execution,
        )
        if outcome == "succeeded":
            return execution
        raise ValueError(f"AKS {purpose} Job failed")

    dispatch_intent_at: datetime | None = None
    if dispatch_intent_path.exists():
        dispatch_intent_at = _validate_timed_checkpoint(
            private_json(dispatch_intent_path, f"AKS {purpose} dispatch intent checkpoint"),
            checkpoint=checkpoint,
            state="dispatch-intent",
        )
    dispatched = dispatched_path.exists()
    if dispatched:
        _validate_checkpoint(
            private_json(dispatched_path, f"AKS {purpose} dispatch checkpoint"),
            checkpoint=checkpoint,
            state="dispatched",
        )
    ambiguous = ambiguous_path.exists()
    if ambiguous:
        _validate_timed_checkpoint(
            private_json(ambiguous_path, f"AKS {purpose} ambiguous dispatch checkpoint"),
            checkpoint=checkpoint,
            state="dispatch-ambiguous",
            reason="create-timeout",
        )
    existing = _existing_job(
        execution,
        kubeconfig=kubeconfig,
        work_dir=work_dir,
        purpose=purpose,
    )
    if existing is not None:
        if dispatch_intent_at is None:
            raise ValueError(f"AKS {purpose} Job exists without a retained dispatch intent")
        validate_existing_job(existing, expected=execution)
        if not dispatched:
            replace_or_verify_private_json(
                dispatched_path,
                _checkpoint_record(checkpoint, state="dispatched"),
            )
    else:
        if dispatched:
            raise ValueError(
                f"AKS {purpose} Job outcome is ambiguous; the dispatched execution was not repeated"
            )
        if ambiguous:
            raise ValueError(
                f"AKS {purpose} Job create outcome remains ambiguous; "
                "the dispatch intent was not repeated"
            )
        now = _utc_now()
        if dispatch_intent_at is None:
            dispatch_intent_at = now
            replace_or_verify_private_json(
                dispatch_intent_path,
                _timed_checkpoint_record(
                    checkpoint,
                    state="dispatch-intent",
                    recorded_at=dispatch_intent_at,
                ),
            )
        elif not _absent_job_can_be_dispatched(
            dispatch_intent_at,
            observed_at=now,
        ):
            raise ValueError(
                f"AKS {purpose} Job absence may follow terminal TTL deletion; "
                "the dispatch intent was not repeated"
            )
        try:
            _run(
                (
                    "kubectl",
                    "create",
                    "--filename",
                    str(manifest_path),
                    f"--kubeconfig={kubeconfig}",
                ),
                cwd=work_dir,
                timeout=60,
                reason=f"AKS {purpose} Job start failed",
            )
        except subprocess.TimeoutExpired as exc:
            replace_or_verify_private_json(
                ambiguous_path,
                _timed_checkpoint_record(
                    checkpoint,
                    state="dispatch-ambiguous",
                    recorded_at=_utc_now(),
                    reason="create-timeout",
                ),
            )
            existing = _existing_job(
                execution,
                kubeconfig=kubeconfig,
                work_dir=work_dir,
                purpose=purpose,
            )
            if existing is None:
                raise ValueError(
                    f"AKS {purpose} Job create timed out with an ambiguous outcome; "
                    "the dispatched execution was not repeated"
                ) from exc
            validate_existing_job(existing, expected=execution)
            replace_or_verify_private_json(
                dispatched_path,
                _checkpoint_record(checkpoint, state="dispatched"),
            )
        else:
            replace_or_verify_private_json(
                dispatched_path,
                _checkpoint_record(checkpoint, state="dispatched"),
            )

    deadline = time.monotonic() + timeout_seconds
    current = existing
    while time.monotonic() < deadline:
        if current is None:
            current = _existing_job(
                execution,
                kubeconfig=kubeconfig,
                work_dir=work_dir,
                purpose=purpose,
            )
        if current is None:
            raise ValueError(
                f"AKS {purpose} Job terminal evidence is unavailable; "
                "the dispatched execution was not repeated"
            )
        validate_existing_job(current, expected=execution)
        state = job_terminal_state(current)
        if state == "succeeded":
            replace_or_verify_private_json(
                terminal_path,
                _terminal_checkpoint_record(
                    checkpoint,
                    execution=execution,
                    job=current,
                    outcome="succeeded",
                ),
            )
            return execution
        if state == "failed":
            replace_or_verify_private_json(
                terminal_path,
                _terminal_checkpoint_record(
                    checkpoint,
                    execution=execution,
                    job=current,
                    outcome="failed",
                ),
            )
            raise ValueError(f"AKS {purpose} Job failed")
        current = None
        time.sleep(5)
    raise ValueError(f"AKS {purpose} Job exceeded its bounded deadline")


def _protected_template_digest(
    context: dict[str, Any],
    *,
    template_name: str,
) -> str:
    values = context.get("protected_aks_job_template_digests")
    if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
        raise ValueError("protected AKS Job template digests are unavailable")
    digest = values.get(template_name)
    if not isinstance(digest, str):
        raise ValueError("protected AKS Job template digest is unavailable")
    return digest


def _protected_identity_binding(
    context: dict[str, Any],
    *,
    template_name: str,
    expected_service_account: str,
) -> dict[str, object]:
    bindings = context.get("protected_aks_job_identity_bindings")
    if not isinstance(bindings, dict) or any(not isinstance(key, str) for key in bindings):
        raise ValueError("protected AKS Job identity bindings are unavailable")
    value = bindings.get(template_name)
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("protected AKS Job identity binding is unavailable")
    binding = {str(key): item for key, item in value.items()}
    supplied_digest = binding.pop("binding_digest", None)
    context_subscription = str(context.get("subscription_id", "")).casefold()
    context_tenant = str(context.get("tenant_id", "")).casefold()
    resource_id = binding.get("identity_resource_id")
    client_id = binding.get("identity_client_id")
    resource_match = (
        _MANAGED_IDENTITY_ID.fullmatch(resource_id) if isinstance(resource_id, str) else None
    )
    expected_annotations = {
        "azure.workload.identity/client-id": client_id,
        "azure.workload.identity/tenant-id": context_tenant,
    }
    if (
        set(binding)
        != {
            "schema_version",
            "service_account_name",
            "namespace",
            "identity_client_id",
            "identity_resource_id",
            "tenant_id",
            "subscription_id",
            "annotations",
        }
        or supplied_digest != canonical_digest(binding)
        or binding.get("schema_version") != "fdai.aks-service-account-binding.v1"
        or binding.get("service_account_name") != expected_service_account
        or binding.get("namespace") != _NAMESPACE
        or binding.get("tenant_id") != context_tenant
        or binding.get("subscription_id") != context_subscription
        or resource_match is None
        or resource_match.group(1) != context_subscription
        or not isinstance(client_id, str)
        or _GUID.fullmatch(client_id) is None
        or binding.get("annotations") != expected_annotations
    ):
        raise ValueError("protected AKS Job identity binding differs")
    binding["binding_digest"] = supplied_digest
    return binding


def _verify_service_account(value: object, *, expected: dict[str, object]) -> None:
    if (
        not isinstance(value, dict)
        or value.get("apiVersion") != "v1"
        or value.get("kind") != "ServiceAccount"
    ):
        raise ValueError("AKS one-shot ServiceAccount is invalid")
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("AKS one-shot ServiceAccount metadata is invalid")
    annotations = metadata.get("annotations", {})
    if not isinstance(annotations, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in annotations.items()
    ):
        raise ValueError("AKS one-shot ServiceAccount annotations are invalid")
    workload_annotations = {
        key: annotations[key]
        for key in sorted(annotations)
        if key.startswith(_WORKLOAD_IDENTITY_ANNOTATION_PREFIX)
    }
    if (
        metadata.get("name") != expected.get("service_account_name")
        or metadata.get("namespace") != expected.get("namespace")
        or workload_annotations != expected.get("annotations")
    ):
        raise ValueError("AKS one-shot ServiceAccount identity binding changed")


def _existing_job(
    execution: AksOneShotJob,
    *,
    kubeconfig: Path,
    work_dir: Path,
    purpose: str,
) -> object | None:
    raw = _capture(
        (
            "kubectl",
            "get",
            "job",
            execution.name,
            "--namespace",
            _NAMESPACE,
            "--output",
            "json",
            "--ignore-not-found",
            f"--kubeconfig={kubeconfig}",
        ),
        cwd=work_dir,
        timeout=60,
        reason=f"AKS {purpose} Job recovery readback failed",
    ).strip()
    if not raw:
        return None
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AKS {purpose} Job recovery readback is invalid") from exc
    return value


def _checkpoint_binding(
    execution: AksOneShotJob,
    *,
    protected_template_digest: str,
    protected_identity_binding_digest: str,
) -> dict[str, object]:
    return {
        "schema_version": _CHECKPOINT_SCHEMA,
        "name": execution.name,
        "execution_digest": execution.execution_digest,
        "manifest_digest": canonical_digest(execution.manifest),
        "protected_template_digest": protected_template_digest,
        "protected_identity_binding_digest": protected_identity_binding_digest,
        "job_ttl_seconds": _JOB_TTL_SECONDS,
    }


def _checkpoint_record(
    checkpoint: dict[str, object],
    *,
    state: str,
) -> dict[str, object]:
    value = {**checkpoint, "state": state}
    value["checkpoint_digest"] = canonical_digest(value)
    return value


def _validate_checkpoint(
    value: dict[str, Any],
    *,
    checkpoint: dict[str, object],
    state: str,
) -> None:
    supplied_digest = value.get("checkpoint_digest")
    material = {str(key): item for key, item in value.items() if key != "checkpoint_digest"}
    if material != {**checkpoint, "state": state} or supplied_digest != canonical_digest(material):
        raise ValueError(f"retained AKS Job {state} checkpoint differs")


def _timed_checkpoint_record(
    checkpoint: dict[str, object],
    *,
    state: str,
    recorded_at: datetime,
    reason: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        **checkpoint,
        "state": state,
        "recorded_at": _format_moment(recorded_at),
    }
    if reason is not None:
        value["reason"] = reason
    value["checkpoint_digest"] = canonical_digest(value)
    return value


def _validate_timed_checkpoint(
    value: dict[str, Any],
    *,
    checkpoint: dict[str, object],
    state: str,
    reason: str | None = None,
) -> datetime:
    supplied_digest = value.get("checkpoint_digest")
    material = {str(key): item for key, item in value.items() if key != "checkpoint_digest"}
    recorded_at = _parse_moment(material.get("recorded_at"))
    expected = {**checkpoint, "state": state, "recorded_at": material.get("recorded_at")}
    if reason is not None:
        expected["reason"] = reason
    if (
        recorded_at is None
        or recorded_at > _utc_now() + _CHECKPOINT_CLOCK_SKEW
        or material != expected
        or supplied_digest != canonical_digest(material)
    ):
        raise ValueError(f"retained AKS Job {state} checkpoint differs")
    return recorded_at


def _absent_job_can_be_dispatched(
    intent_at: datetime,
    *,
    observed_at: datetime,
) -> bool:
    if observed_at < intent_at - _CHECKPOINT_CLOCK_SKEW:
        raise ValueError("AKS Job dispatch intent clock is invalid")
    possible_ttl_deletion_at = intent_at + timedelta(seconds=_JOB_TTL_SECONDS)
    return observed_at < possible_ttl_deletion_at - _DISPATCH_ABSENCE_MARGIN


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _format_moment(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_moment(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _terminal_checkpoint_record(
    checkpoint: dict[str, object],
    *,
    execution: AksOneShotJob,
    job: object,
    outcome: str,
) -> dict[str, object]:
    evidence = _terminal_evidence(job)
    value: dict[str, object] = {
        **checkpoint,
        "state": "terminal",
        "outcome": outcome,
        "observed_job_contract_digest": aks_job_contract_digest(job),
        "terminal_evidence": evidence,
        "terminal_evidence_digest": canonical_digest(evidence),
        "effect_verified": outcome == "succeeded",
        "mutation_performed": True,
    }
    if value["observed_job_contract_digest"] != aks_job_contract_digest(execution.manifest):
        raise ValueError("AKS Job terminal controlled contract changed")
    value["checkpoint_digest"] = canonical_digest(value)
    return value


def _terminal_checkpoint_outcome(
    value: dict[str, Any],
    *,
    checkpoint: dict[str, object],
    execution: AksOneShotJob,
) -> str:
    supplied_digest = value.get("checkpoint_digest")
    material = {str(key): item for key, item in value.items() if key != "checkpoint_digest"}
    evidence = material.get("terminal_evidence")
    outcome = material.get("outcome")
    if (
        any(material.get(key) != expected for key, expected in checkpoint.items())
        or material.get("state") != "terminal"
        or outcome not in {"succeeded", "failed"}
        or not isinstance(evidence, dict)
        or material.get("terminal_evidence_digest") != canonical_digest(evidence)
        or material.get("observed_job_contract_digest")
        != aks_job_contract_digest(execution.manifest)
        or material.get("effect_verified") is not (outcome == "succeeded")
        or material.get("mutation_performed") is not True
        or supplied_digest != canonical_digest(material)
    ):
        raise ValueError("retained AKS Job terminal checkpoint differs")
    return str(outcome)


def _terminal_evidence(job: object) -> dict[str, object]:
    if not isinstance(job, dict):
        raise ValueError("AKS Job terminal evidence is invalid")
    status = job.get("status")
    if not isinstance(status, dict):
        raise ValueError("AKS Job terminal evidence is invalid")
    conditions = status.get("conditions", [])
    if not isinstance(conditions, list):
        raise ValueError("AKS Job terminal evidence is invalid")
    normalized_conditions: list[dict[str, str]] = []
    for item in conditions:
        if not isinstance(item, dict):
            raise ValueError("AKS Job terminal evidence is invalid")
        condition_type = item.get("type")
        condition_status = item.get("status")
        if not isinstance(condition_type, str) or not isinstance(condition_status, str):
            raise ValueError("AKS Job terminal evidence is invalid")
        normalized_conditions.append(
            {
                "type": condition_type,
                "status": condition_status,
                **({"reason": str(item["reason"])} if isinstance(item.get("reason"), str) else {}),
            }
        )
    return {
        "conditions": sorted(
            normalized_conditions,
            key=lambda condition: (condition["type"], condition["status"]),
        ),
        "succeeded": status.get("succeeded", 0),
        "failed": status.get("failed", 0),
        "completion_time": status.get("completionTime"),
    }


def _json_capture(
    command: tuple[str, ...],
    *,
    cwd: Path,
    timeout: int,
    reason: str,
) -> object:
    raw = _capture(command, cwd=cwd, timeout=timeout, reason=reason)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{reason}: invalid JSON") from exc


def _capture(command: tuple[str, ...], *, cwd: Path, timeout: int, reason: str) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError(reason)
    return result.stdout


def _run(command: tuple[str, ...], *, cwd: Path, timeout: int, reason: str) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError(reason)


__all__ = ["execute_aks_cronjob_once", "protected_service_account_binding"]
