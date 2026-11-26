"""Kubernetes command transports for observer installation: kubectl and AKS Run Command."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from fdai.delivery.kubernetes_connector_claim import MANIFEST_FILE

_READ_ONLY_VERBS = frozenset({"get", "logs"})


@dataclass(frozen=True, slots=True)
class KubeResult:
    """One Kubernetes command outcome; the output is never trusted as authority."""

    exit_code: int
    output: str


class KubeTransport(Protocol):
    """Run one fixed kubectl argument vector against exactly one cluster."""

    name: str

    def run(self, args: Sequence[str], *, manifest: bytes | None, timeout: int) -> KubeResult: ...


class KubectlTransport:
    """Direct kubectl for an existing or managed host that already reaches the private API."""

    name = "kubectl"

    def __init__(self, *, kubeconfig: Path, kubectl: str = "kubectl", tools: Path | None = None):
        if not kubeconfig.is_file():
            raise ValueError("observer apply kubeconfig is unavailable")
        self._kubeconfig, self._kubectl, self._tools = kubeconfig, kubectl, tools

    def run(self, args: Sequence[str], *, manifest: bytes | None, timeout: int) -> KubeResult:
        environment = dict(os.environ)
        if self._tools is not None:
            environment["PATH"] = f"{self._tools}{os.pathsep}{environment.get('PATH', '')}"
        command = [
            self._kubectl,
            f"--kubeconfig={self._kubeconfig}",
            "--request-timeout=60s",
            *("-" if item == MANIFEST_FILE else item for item in args),
        ]
        try:
            done = subprocess.run(  # noqa: S603 - fixed vector, no shell
                command,
                input=manifest,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("kubectl did not finish; the outcome is unknown") from exc
        return KubeResult(done.returncode, (done.stdout + done.stderr).decode(errors="replace"))


class AksRunCommandTransport:
    """AKS Run Command for a private cluster; it needs Azure RBAC, not network line of sight."""

    name = "aks-run-command"

    def __init__(
        self,
        *,
        subscription_id: str,
        resource_group: str,
        cluster_name: str,
        az: str = "az",
        run: Callable[..., Any] = subprocess.run,
    ) -> None:
        if (
            re.fullmatch(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", subscription_id)
            is None
            or re.fullmatch(r"[A-Za-z0-9._()-]{1,90}", resource_group) is None
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", cluster_name) is None
        ):
            raise ValueError("AKS Run Command target identity is invalid")
        self._target = (subscription_id, resource_group, cluster_name)
        self._az, self._run = az, run

    def run(self, args: Sequence[str], *, manifest: bytes | None, timeout: int) -> KubeResult:
        subscription, group, cluster = self._target
        command = "kubectl " + shlex.join(
            "manifest.json" if item == MANIFEST_FILE else item for item in args
        )
        vector = [
            self._az,
            "aks",
            "command",
            "invoke",
            "--subscription",
            subscription,
            "--resource-group",
            group,
            "--name",
            cluster,
            "--command",
            command,
            "--output",
            "json",
        ]
        with tempfile.TemporaryDirectory(prefix="fdai-observer-") as directory:
            if manifest is not None:
                path = Path(directory) / "manifest.json"
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(manifest)
                vector += ["--file", str(path)]
            # A read has no effect, so one unparseable service response may be retried. A write is
            # never repeated here: its unknown outcome is reported to the caller instead.
            attempts = 2 if args and args[0] in _READ_ONLY_VERBS else 1
            for attempt in range(attempts):
                try:
                    done = self._run(
                        vector, capture_output=True, text=True, timeout=timeout, check=False
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise ValueError(
                        "AKS Run Command did not finish; the outcome is unknown"
                    ) from exc
                try:
                    payload = json.loads(done.stdout)
                    return KubeResult(int(payload["exitCode"]), str(payload.get("logs") or ""))
                except (ValueError, KeyError, TypeError) as exc:
                    if attempt + 1 < attempts:
                        continue
                    detail = " ".join(str(done.stderr).split())[:200]
                    raise ValueError(
                        "AKS Run Command is unavailable; check that command invoke is enabled "
                        f"and permitted for the caller ({detail})"
                    ) from exc
        raise AssertionError("unreachable")  # pragma: no cover
