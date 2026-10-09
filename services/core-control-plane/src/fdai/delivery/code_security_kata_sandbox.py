"""Observe each scanner process through an authenticated Kubernetes API, outside its Kata VM."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

from fdai.delivery.code_security_kata_client import InClusterKataClient, KataApiError
from fdai.delivery.code_security_kata_job import (
    KataScanConfig,
    build_scanner_job,
    validate_deny_all_policy,
    validate_scanner_pod,
)
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox, ScannerRunResult
from fdai.rule_catalog.code_security_scanners import ScannerSpec


class KataCleanupError(KataApiError):
    """Stop the attempt while retaining the independently observed process outcome."""

    def __init__(self, observation: ScannerRunResult | None) -> None:
        super().__init__("scanner Job cleanup is unconfirmed; process evidence was retained")
        self.observation = observation


class KataScannerSandbox(BubblewrapScannerSandbox):
    """Use separate, identity-free Jobs; never accept a process's own completion claim."""

    def __init__(
        self,
        config: KataScanConfig,
        client: InClusterKataClient,
        *,
        journal_directory: Path | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self._journal_directory = journal_directory
        self._observations: list[ScannerRunResult] = []

    @property
    def observations(self) -> tuple[ScannerRunResult, ...]:
        return tuple(self._observations)

    def _journal(
        self,
        name: str,
        scanner_id: str,
        phase: str,
        *,
        uid: str | None = None,
        observation: ScannerRunResult | None = None,
    ) -> None:
        if self._journal_directory is None:
            return
        self._journal_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self._journal_directory / f"{name}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "job_name": name,
                    "job_uid": uid,
                    "scanner_id": scanner_id,
                    "phase": phase,
                    "execution_authority": False,
                    **(
                        {
                            "exit_code": observation.exit_code,
                            "process_completed": observation.completed,
                            "stdout_sha256": hashlib.sha256(observation.stdout).hexdigest(),
                        }
                        if observation is not None
                        else {}
                    ),
                },
                sort_keys=True,
            )
            + "\n"
        )
        temporary.chmod(0o600)
        temporary.replace(target)

    async def _preflight(self) -> None:
        namespace = await self.client.request("GET", f"/api/v1/namespaces/{self.config.namespace}")
        metadata = namespace.get("metadata")
        labels = metadata.get("labels") if isinstance(metadata, dict) else None
        if (
            not isinstance(labels, dict)
            or labels.get("pod-security.kubernetes.io/enforce") != "restricted"
        ):
            raise KataApiError("scanner namespace must enforce Restricted Pod Security")
        policies = await self.client.request(
            "GET", f"/apis/networking.k8s.io/v1/namespaces/{self.config.namespace}/networkpolicies"
        )
        items = policies.get("items")
        if not isinstance(items, list):
            raise KataApiError("scanner network-policy inventory is unavailable")
        found = False
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("metadata"), dict):
                raise KataApiError("scanner network-policy inventory is malformed")
            policy = item.get("spec")
            if not isinstance(policy, dict):
                raise KataApiError("scanner network policy is malformed")
            # Policies are additive: another allow rule would defeat the deny-all namespace.
            if policy.get("egress") or policy.get("ingress"):
                raise KataApiError("scanner namespace contains a network allowance")
            if item["metadata"].get("name") == self.config.network_policy:
                validate_deny_all_policy(item)
                found = True
        if not found:
            raise KataApiError("scanner namespace has no deny-all network policy")
        runtime = await self.client.request(
            "GET", "/apis/node.k8s.io/v1/runtimeclasses/kata-vm-isolation"
        )
        if runtime.get("handler") not in {"kata", "kata-vm-isolation"}:
            raise KataApiError("scanner runtime class is not the installed Kata handler")

    async def run(
        self,
        scanner_id: str,
        spec: ScannerSpec,
        executable: Path,
        source: Path,
        *,
        rules: Path | None = None,
        cache: Path | None = None,
        environ: Mapping[str, str] | None = None,
        limit_address_space: bool = True,
        system_config: Sequence[Path] = (),
    ) -> ScannerRunResult:
        if environ or system_config or not limit_address_space:
            raise ValueError("Kata deterministic scanners cannot receive ambient or proof bindings")
        name = "fdai-scan-" + uuid4().hex
        job = build_scanner_job(self.config, scanner_id, spec, executable, source, name)
        root = f"/apis/batch/v1/namespaces/{self.config.namespace}/jobs"
        self._journal(name, scanner_id, "dispatch_intent")
        try:
            await self._preflight()
        except (KataApiError, ValueError):
            self._journal(name, scanner_id, "preflight_failed")
            raise
        try:
            created = await self.client.request("POST", root, body=job)
        except KataApiError:
            self._journal(name, scanner_id, "dispatch_unknown")
            raise
        metadata = created.get("metadata")
        if (
            not isinstance(metadata, dict)
            or metadata.get("name") != name
            or not isinstance(metadata.get("uid"), str)
            or not metadata["uid"]
        ):
            self._journal(name, scanner_id, "dispatch_identity_unavailable")
            raise KataApiError("created scanner Job has no exact identity")
        uid = metadata["uid"]
        self._journal(name, scanner_id, "observing", uid=uid)
        started = time.monotonic()
        deadline = started + spec.timeout_seconds + 330
        last_progress = started
        previous_status = ""
        running_started: float | None = None
        result: ScannerRunResult | None = None
        primary_error: Exception | None = None
        observed_pod_uid: str | None = None
        try:
            while time.monotonic() < deadline:
                current = await self.client.request("GET", f"{root}/{name}")
                current_meta = current.get("metadata")
                if not isinstance(current_meta, dict) or current_meta.get("uid") != uid:
                    raise KataApiError("scanner Job identity changed")
                pods = await self.client.request(
                    "GET",
                    f"/api/v1/namespaces/{self.config.namespace}/pods"
                    f"?labelSelector=job-name%3D{name}",
                )
                pod_items = pods.get("items")
                if not isinstance(pod_items, list) or len(pod_items) > 1:
                    raise KataApiError("scanner Job pod count is ambiguous")
                if pod_items:
                    pod = pod_items[0]
                    if not isinstance(pod, dict):
                        raise KataApiError("scanner pod metadata is malformed")
                    validate_scanner_pod(job, pod, uid)
                    pod_metadata = pod.get("metadata")
                    pod_uid = pod_metadata.get("uid") if isinstance(pod_metadata, dict) else None
                    if not isinstance(pod_uid, str) or not 1 <= len(pod_uid) <= 128:
                        raise KataApiError("scanner pod has no exact identity")
                    if observed_pod_uid is not None and observed_pod_uid != pod_uid:
                        raise KataApiError("scanner pod identity changed")
                    observed_pod_uid = pod_uid
                    status = pod.get("status")
                    if not isinstance(status, dict):
                        status = {}
                    progress = repr(status)
                    if progress != previous_status:
                        previous_status = progress
                        last_progress = time.monotonic()
                    statuses = status.get("containerStatuses", [])
                    if isinstance(statuses, list) and len(statuses) == 1:
                        container_status = statuses[0]
                        if (
                            not isinstance(container_status, dict)
                            or container_status.get("name") != "scanner"
                        ):
                            raise KataApiError(
                                "scanner process observation has a different container"
                            )
                        state = container_status.get("state")
                        if isinstance(state, dict) and isinstance(state.get("running"), dict):
                            if running_started is None:
                                running_started = time.monotonic()
                            if time.monotonic() - running_started > spec.timeout_seconds:
                                result = ScannerRunResult(
                                    scanner_id,
                                    spec.producer,
                                    b"",
                                    None,
                                    False,
                                    False,
                                    True,
                                    int((time.monotonic() - started) * 1000),
                                    "",
                                )
                                self._observations.append(result)
                                self._journal(name, scanner_id, "timed_out", uid=uid)
                                return result
                        terminated = state.get("terminated") if isinstance(state, dict) else None
                        if isinstance(terminated, dict):
                            exit_code = terminated.get("exitCode")
                            pod_meta = pod.get("metadata")
                            pod_name = pod_meta.get("name") if isinstance(pod_meta, dict) else None
                            if (
                                type(exit_code) is not int
                                or not isinstance(pod_name, str)
                                or re.fullmatch(r"[a-z0-9][-a-z0-9]{0,62}", pod_name) is None
                                or container_status.get("restartCount", 0) != 0
                            ):
                                raise KataApiError("scanner termination observation is malformed")
                            stdout, truncated = await self.client.stdout(
                                self.config.namespace, pod_name, spec.max_output_bytes
                            )
                            result = ScannerRunResult(
                                scanner_id,
                                spec.producer,
                                stdout,
                                exit_code,
                                exit_code in spec.success_exit_codes and not truncated,
                                truncated,
                                False,
                                int((time.monotonic() - started) * 1000),
                                "",
                            )
                            self._observations.append(result)
                            self._journal(
                                name,
                                scanner_id,
                                "completed" if result.completed else "failed",
                                uid=uid,
                            )
                            return result
                if running_started is None and time.monotonic() - last_progress > 180:
                    raise KataApiError("scanner Job exceeded its no-progress deadline")
                await asyncio.sleep(2)
            result = ScannerRunResult(
                scanner_id,
                spec.producer,
                b"",
                None,
                False,
                False,
                True,
                int((time.monotonic() - started) * 1000),
                "",
            )
            self._observations.append(result)
            self._journal(name, scanner_id, "timed_out", uid=uid)
            return result
        except (KataApiError, ValueError, OSError) as error:
            primary_error = error
            self._journal(name, scanner_id, "observation_failed", uid=uid)
            raise
        finally:
            try:
                await self.client.request(
                    "DELETE",
                    f"{root}/{name}",
                    body={"propagationPolicy": "Foreground", "preconditions": {"uid": uid}},
                )
            except KataApiError as cleanup_error:
                self._journal(name, scanner_id, "cleanup_failed", uid=uid, observation=result)
                raise KataCleanupError(result) from (primary_error or cleanup_error)
