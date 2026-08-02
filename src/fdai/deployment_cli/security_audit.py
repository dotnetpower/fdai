"""Deterministic runtime and local-config security posture audit."""

from __future__ import annotations

import json
import os
import shutil
import stat
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

SECURITY_AUDIT_SCHEMA: Final = "fdai.deployment-cli.security-audit.v1"
_DEV_AUTH_FLAGS: Final = ("FDAI_OPERATOR_API_DEV_MODE", "FDAI_OPERATOR_API_LOCAL_AZURE_CLI")
_SECRET_KEY_PARTS: Final = (
    "password",
    "private_key",
    "access_key",
    "connection_string",
    "token",
    "secret",
)


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    check_id: str
    severity: str
    summary: str
    remediation: str
    fixed: bool = False


@dataclass(frozen=True, slots=True)
class SecurityAuditReport:
    findings: tuple[SecurityFinding, ...]
    schema_version: str = SECURITY_AUDIT_SCHEMA

    @property
    def secure(self) -> bool:
        return not any(
            finding.severity == "critical" and not finding.fixed for finding in self.findings
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "findings": [asdict(finding) for finding in self.findings],
                "schema_version": self.schema_version,
                "secure": self.secure,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def run_security_audit(
    *,
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    fix_permissions: bool = False,
    resolve_executable: Callable[[str], str | None] = shutil.which,
) -> SecurityAuditReport:
    """Inspect known high-risk FDAI runtime combinations without exposing values."""
    environ = dict(env if env is not None else os.environ)
    findings: list[SecurityFinding] = []
    runtime_env = environ.get("RUNTIME_ENV", "dev").strip().lower() or "dev"
    non_dev = runtime_env in {"staging", "prod"}

    active_dev_flags = [flag for flag in _DEV_AUTH_FLAGS if _enabled(environ.get(flag))]
    if non_dev and active_dev_flags:
        findings.append(
            SecurityFinding(
                check_id="auth.dev-bypass-non-dev",
                severity="critical",
                summary="A development authentication bypass is enabled outside development",
                remediation=(
                    "Disable local and anonymous auth flags before starting the Operator API."
                ),
            )
        )
    if non_dev and not all(
        environ.get(key, "").strip() for key in ("FDAI_ENTRA_TENANT_ID", "FDAI_API_AUDIENCE")
    ):
        findings.append(
            SecurityFinding(
                check_id="auth.entra-config-missing",
                severity="critical",
                summary="Production Entra verifier configuration is incomplete",
                remediation="Configure the tenant and API audience through deployment secrets.",
            )
        )
    if _enabled(environ.get("FDAI_VM_TASK_ENFORCE")) and not _enabled(
        environ.get("FDAI_VM_TASK_ENABLED")
    ):
        findings.append(
            SecurityFinding(
                check_id="execution.vm-task-enforce-without-enable",
                severity="critical",
                summary="VM task enforcement is set without the governed task runtime",
                remediation=(
                    "Disable enforcement or enable and configure the governed VM task path."
                ),
            )
        )
    if (
        _enabled(environ.get("FDAI_CHAOS_ENFORCE"))
        and not environ.get("FDAI_CHAOS_CONTEXT_JSON", "").strip()
    ):
        findings.append(
            SecurityFinding(
                check_id="execution.chaos-context-missing",
                severity="critical",
                summary="Chaos enforcement has no bounded runtime context",
                remediation="Disable chaos enforcement or provide the validated runtime context.",
            )
        )
    if environ.get("FDAI_COMMAND_RUNNER", "").strip().lower() == "bubblewrap" and (
        resolve_executable("bwrap") is None
    ):
        findings.append(
            SecurityFinding(
                check_id="sandbox.bubblewrap-missing",
                severity="critical",
                summary="The configured local command sandbox is unavailable",
                remediation="Install bubblewrap or disable the local command runner.",
            )
        )
    if config_path is not None:
        findings.extend(_audit_config(config_path, fix_permissions=fix_permissions))
    if not findings:
        findings.append(
            SecurityFinding(
                check_id="baseline.no-critical-findings",
                severity="info",
                summary="No critical findings were detected by the local audit",
                remediation="Continue with deployment preflight and policy validation.",
            )
        )
    return SecurityAuditReport(findings=tuple(sorted(findings, key=lambda item: item.check_id)))


def _audit_config(path: Path, *, fix_permissions: bool) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    if path.is_symlink():
        return [
            SecurityFinding(
                check_id="config.symlink",
                severity="critical",
                summary="Deployment configuration is a symbolic link",
                remediation="Replace it with a mode-0600 regular file in the local FDAI directory.",
            )
        ]
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [
            SecurityFinding(
                check_id="config.unreadable",
                severity="critical",
                summary="Deployment configuration is invalid or unreadable",
                remediation="Recreate it with fdaictl onboard init.",
            )
        ]
    if mode & 0o077:
        fixed = False
        if fix_permissions:
            path.chmod(0o600)
            fixed = True
        findings.append(
            SecurityFinding(
                check_id="config.file-permissions",
                severity="critical",
                summary="Deployment configuration is readable outside its owner",
                remediation="Set the configuration file mode to 0600.",
                fixed=fixed,
            )
        )
    parent_mode = stat.S_IMODE(path.parent.stat().st_mode)
    if parent_mode & 0o077:
        fixed = False
        if fix_permissions:
            path.parent.chmod(0o700)
            fixed = True
        findings.append(
            SecurityFinding(
                check_id="config.directory-permissions",
                severity="critical",
                summary="Deployment configuration directory is accessible outside its owner",
                remediation="Set the configuration directory mode to 0700.",
                fixed=fixed,
            )
        )
    if _contains_secret_key(parsed):
        findings.append(
            SecurityFinding(
                check_id="config.secret-like-key",
                severity="critical",
                summary="Deployment configuration contains a secret-like field name",
                remediation="Store only references and move secret values to the secret provider.",
            )
        )
    return findings


def _contains_secret_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in _SECRET_KEY_PARTS):
                return True
            if _contains_secret_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(child) for child in value)
    return False


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "SECURITY_AUDIT_SCHEMA",
    "SecurityAuditReport",
    "SecurityFinding",
    "run_security_audit",
]
