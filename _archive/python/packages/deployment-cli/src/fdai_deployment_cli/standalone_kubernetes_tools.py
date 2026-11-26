"""Verified managed-host Kubernetes tool execution."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlencode


def tools(context: Mapping[str, object]) -> tuple[str, str, dict[str, str]]:
    """Return the sealed kubectl pair and an environment that resolves its exec plugin."""

    root = Path(str(context.get("kit_bin", "")))
    selected: list[str] = []
    for name in ("kubectl", "kubelogin"):
        path = root / name
        try:
            details = path.lstat()
        except OSError as exc:
            raise ValueError(f"managed-host {name} is unavailable") from exc
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or not details.st_mode & stat.S_IXUSR
        ):
            raise ValueError(f"managed-host {name} is unavailable")
        selected.append(str(path))
    environment = dict(os.environ)
    current_path = environment.get("PATH", "")
    environment["PATH"] = str(root) if not current_path else f"{root}{os.pathsep}{current_path}"
    return selected[0], selected[1], environment


def capture_deployments(
    context: Mapping[str, object],
    *,
    namespace: str,
    service: str | None,
    capture: Callable[..., str],
) -> str:
    """Read the typed Deployment collection with the sealed Kubernetes tools."""

    kubeconfig = Path(str(context.get("kubeconfig", "")))
    if not kubeconfig.is_file():
        raise ValueError("AKS kubeconfig is unavailable for service update readback")
    kubectl, _kubelogin, environment = tools(context)
    endpoint = f"/apis/apps/v1/namespaces/{namespace}/deployments"
    if service is not None:
        endpoint = f"{endpoint}?{urlencode({'labelSelector': f'app.kubernetes.io/name={service}'})}"
    return capture(
        (
            kubectl,
            "get",
            f"--raw={endpoint}",
            "--request-timeout=60s",
            f"--kubeconfig={kubeconfig}",
        ),
        cwd=kubeconfig.parent,
        timeout=90,
        reason="AKS Deployment observation failed",
        env=environment,
    )


def capture_pods(
    context: Mapping[str, object],
    *,
    namespace: str,
    service: str,
    capture: Callable[..., str],
) -> str:
    """Read one service's Pod collection with the sealed Kubernetes tools."""

    kubeconfig = Path(str(context.get("kubeconfig", "")))
    if not kubeconfig.is_file():
        raise ValueError("AKS kubeconfig is unavailable for service update readback")
    kubectl, _kubelogin, environment = tools(context)
    return capture(
        (
            kubectl,
            "get",
            "pods",
            "--namespace",
            namespace,
            "--output",
            "json",
            "--request-timeout=60s",
            f"--selector=app.kubernetes.io/name={service}",
            f"--kubeconfig={kubeconfig}",
        ),
        cwd=kubeconfig.parent,
        timeout=90,
        reason="AKS Pod observation failed",
        env=environment,
    )


__all__ = ["capture_deployments", "capture_pods", "tools"]
