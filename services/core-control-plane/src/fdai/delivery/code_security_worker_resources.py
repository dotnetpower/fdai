"""Render suspended, explicitly bound scan-controller schedules without creating infrastructure."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from croniter import croniter

from fdai.delivery.code_security_kata_job import KataScanConfig
from fdai.delivery.code_security_kata_resources import scanner_runtime_resources

_NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class ScanWorkerInstallConfig:
    controller_namespace: str
    controller_service_account: str
    scanner_namespace: str
    image: str
    controller_source_pvc: str
    scanner_source_pvc: str
    controller_cache_pvc: str
    scanner_cache_pvc: str
    cache_subpath: str
    state_secret: str
    broker_config_map: str
    request_schedule: str
    scan_schedule: str
    max_batch: int = 1
    github_app_secret: str | None = None
    enabled: bool = False

    def __post_init__(self) -> None:
        for name in (
            self.controller_namespace,
            self.controller_service_account,
            self.scanner_namespace,
            self.controller_source_pvc,
            self.scanner_source_pvc,
            self.controller_cache_pvc,
            self.scanner_cache_pvc,
            self.state_secret,
            self.broker_config_map,
            self.github_app_secret,
        ):
            if name is not None and _NAME.fullmatch(name) is None:
                raise ValueError("worker installation references must be Kubernetes DNS labels")
        if self.controller_namespace == self.scanner_namespace:
            raise ValueError("worker credentials must remain outside the scanner namespace")
        if (
            self.controller_source_pvc == self.controller_cache_pvc
            or self.scanner_source_pvc == self.scanner_cache_pvc
        ):
            raise ValueError("source and vulnerability-cache claims must be separate")
        if type(self.max_batch) is not int or not 1 <= self.max_batch <= 20:
            raise ValueError("worker batch must be between 1 and 20")
        if type(self.enabled) is not bool:
            raise ValueError("worker enablement must be boolean")
        for schedule in (self.request_schedule, self.scan_schedule):
            if len(schedule) > 128 or len(schedule.split()) != 5 or not croniter.is_valid(schedule):
                raise ValueError("worker schedule must be a valid five-field UTC cron expression")
        if not re.fullmatch(r"snapshots/[0-9a-f]{64}/cache", self.cache_subpath):
            raise ValueError("worker cache must name an immutable published snapshot")
        KataScanConfig(
            namespace=self.scanner_namespace,
            image=self.image,
            source_pvc=self.scanner_source_pvc,
            source_mount=Path("/work"),
            cache_pvc=self.scanner_cache_pvc,
            cache_subpath=self.cache_subpath,
        )


def _secret_environment(name: str, secret: str, key: str) -> dict[str, object]:
    return {
        "name": name,
        "valueFrom": {
            "secretKeyRef": {"name": secret, "key": key, "optional": False},
        },
    }


def _cronjob(config: ScanWorkerInstallConfig, *, requests: bool) -> dict[str, object]:
    suffix = "requests" if requests else "schedule"
    command = "process-scan-requests" if requests else "process-scheduled-scans"
    args = [
        command,
        "--state-access",
        "restricted",
        "--scanner-runtime",
        "kata",
        "--scanner-namespace",
        config.scanner_namespace,
        "--scanner-image",
        config.image,
        "--scanner-source-pvc",
        config.scanner_source_pvc,
        "--scanner-source-mount",
        "/work",
        "--scanner-cache-pvc",
        config.scanner_cache_pvc,
        "--scanner-cache-subpath",
        config.cache_subpath,
        "--cache-dir",
        "/cache",
        "--work-root",
        "/work/controller",
        "--kafka-bootstrap-servers",
        "$(FDAI_SCAN_BROKER)",
        "--max-requests" if requests else "--max-repositories",
        str(config.max_batch),
    ]
    for scanner, executable in (
        ("opengrep", "opengrep"),
        ("gitleaks", "gitleaks"),
        ("osv-scanner", "osv-scanner"),
        ("trivy-config", "trivy"),
        ("trivy-vuln", "trivy"),
    ):
        args += ["--scanner-bin", f"{scanner}=/opt/scanners/bin/{executable}"]
    environment = [
        {"name": "HOME", "value": "/tmp"},  # noqa: S108 - private pod volume
        _secret_environment("FDAI_STATE_STORE_DSN", config.state_secret, "dsn"),
        {
            "name": "FDAI_SCAN_BROKER",
            "valueFrom": {
                "configMapKeyRef": {
                    "name": config.broker_config_map,
                    "key": "bootstrap-servers",
                    "optional": False,
                },
            },
        },
    ]
    if config.github_app_secret is not None:
        for variable, key in (
            ("FDAI_GITHUB_APP_CLIENT_ID", "client-id"),
            ("FDAI_GITHUB_APP_INSTALLATION_ID", "installation-id"),
            ("FDAI_GITHUB_APP_PRIVATE_KEY", "private-key"),
        ):
            environment.append(_secret_environment(variable, config.github_app_secret, key))
    return {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {
            "name": f"fdai-code-security-{suffix}",
            "namespace": config.controller_namespace,
        },
        "spec": {
            "schedule": config.request_schedule if requests else config.scan_schedule,
            "timeZone": "Etc/UTC",
            "suspend": not config.enabled,
            "concurrencyPolicy": "Forbid",
            "startingDeadlineSeconds": 300,
            "successfulJobsHistoryLimit": 1,
            "failedJobsHistoryLimit": 3,
            "jobTemplate": {
                "spec": {
                    "backoffLimit": 0,
                    "activeDeadlineSeconds": 3600,
                    "template": {
                        "metadata": {
                            "labels": {"app.kubernetes.io/name": f"fdai-code-security-{suffix}"},
                        },
                        "spec": {
                            "serviceAccountName": config.controller_service_account,
                            "automountServiceAccountToken": True,
                            "restartPolicy": "Never",
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 65532,
                                "runAsGroup": 65532,
                            },
                            "containers": [
                                {
                                    "name": "controller",
                                    "image": config.image,
                                    "command": ["/app/.venv/bin/fdai-code-security"],
                                    "args": args,
                                    "env": environment,
                                    "volumeMounts": [
                                        {"name": "source", "mountPath": "/work"},
                                        {
                                            "name": "cache",
                                            "mountPath": "/cache",
                                            "subPath": config.cache_subpath,
                                            "readOnly": True,
                                        },
                                        {"name": "tmp", "mountPath": "/tmp"},  # noqa: S108
                                    ],
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "readOnlyRootFilesystem": True,
                                        "capabilities": {"drop": ["ALL"]},
                                        "seccompProfile": {"type": "RuntimeDefault"},
                                    },
                                    "resources": {
                                        "requests": {"cpu": "1", "memory": "4Gi"},
                                        "limits": {"cpu": "2", "memory": "4Gi"},
                                    },
                                }
                            ],
                            "volumes": [
                                {
                                    "name": "source",
                                    "persistentVolumeClaim": {
                                        "claimName": config.controller_source_pvc,
                                    },
                                },
                                {
                                    "name": "cache",
                                    "persistentVolumeClaim": {
                                        "claimName": config.controller_cache_pvc,
                                        "readOnly": True,
                                    },
                                },
                                {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}},
                            ],
                        },
                    },
                }
            },
        },
    }


def scan_worker_resources(config: ScanWorkerInstallConfig) -> dict[str, object]:
    """Return installable schedules and scoped scanner RBAC, never credential values.

    PVCs in different namespaces must be prebound to the same source/cache backing stores. The
    scanner byte bootstrap checks actual content, not a matching claim name. Rendering neither
    applies resources nor proves cluster isolation; jobs start suspended unless explicitly enabled.
    """
    runtime = scanner_runtime_resources(
        config.scanner_namespace,
        controller_namespace=config.controller_namespace,
        controller_service_account=config.controller_service_account,
    )
    controller: list[dict[str, object]] = [
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": config.controller_namespace},
        },
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {
                "name": config.controller_service_account,
                "namespace": config.controller_namespace,
            },
            "automountServiceAccountToken": False,
        },
    ]
    runtime_items = runtime["items"]
    if not isinstance(runtime_items, list):
        raise ValueError("scanner runtime resource list is invalid")
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            *controller,
            *runtime_items,
            _cronjob(config, requests=True),
            _cronjob(config, requests=False),
        ],
    }


def add_worker_render_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    command = sub.add_parser(
        "render-scanner-workers", help="render explicitly bound scan schedules"
    )
    for field in (
        "controller-namespace",
        "controller-service-account",
        "scanner-namespace",
        "image",
        "controller-source-pvc",
        "scanner-source-pvc",
        "controller-cache-pvc",
        "scanner-cache-pvc",
        "cache-subpath",
        "state-secret",
        "broker-config-map",
        "request-schedule",
        "scan-schedule",
    ):
        command.add_argument("--" + field, required=True)
    command.add_argument("--github-app-secret")
    command.add_argument("--max-batch", type=int, default=1)
    command.add_argument("--enable-jobs", action="store_true")


def render_scanner_workers(args: argparse.Namespace) -> dict[str, object]:
    config = ScanWorkerInstallConfig(
        controller_namespace=args.controller_namespace,
        controller_service_account=args.controller_service_account,
        scanner_namespace=args.scanner_namespace,
        image=args.image,
        controller_source_pvc=args.controller_source_pvc,
        scanner_source_pvc=args.scanner_source_pvc,
        controller_cache_pvc=args.controller_cache_pvc,
        scanner_cache_pvc=args.scanner_cache_pvc,
        cache_subpath=args.cache_subpath,
        state_secret=args.state_secret,
        broker_config_map=args.broker_config_map,
        request_schedule=args.request_schedule,
        scan_schedule=args.scan_schedule,
        github_app_secret=args.github_app_secret,
        max_batch=args.max_batch,
        enabled=args.enable_jobs,
    )
    return {"ok": True, "resources": scan_worker_resources(config)}
