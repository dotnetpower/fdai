#!/usr/bin/env python3
"""Run bounded tool, target, source, and checkout checks for Genesis."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from genesis_subprocess import run_with_heartbeat

_GITHUB_REMOTE = re.compile(
    r"^(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)"
    r"(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$"
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class SignedSourceEvidence:
    """Verified distribution evidence supplied by the installed package boundary."""

    source_commit: str
    kit_manifest_digest: str
    bundle_manifest_digest: str
    runtime_release_digest: str

    @classmethod
    def from_environment(cls) -> SignedSourceEvidence | None:
        """Load a bounded non-secret projection created after package-level verification."""

        raw = os.environ.get("FDAI_SIGNED_SOURCE_EVIDENCE")
        if raw is None:
            return None
        if len(raw) > 4096:
            raise CheckError("signed_source_evidence_invalid", 64)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CheckError("signed_source_evidence_invalid", 64) from exc
        expected = {
            "source_commit",
            "kit_manifest_digest",
            "bundle_manifest_digest",
            "runtime_release_digest",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise CheckError("signed_source_evidence_invalid", 64)
        evidence = cls(**{name: str(value[name]) for name in expected})
        if _COMMIT.fullmatch(evidence.source_commit) is None or any(
            _DIGEST.fullmatch(item) is None
            for item in (
                evidence.kit_manifest_digest,
                evidence.bundle_manifest_digest,
                evidence.runtime_release_digest,
            )
        ):
            raise CheckError("signed_source_evidence_invalid", 64)
        return evidence


def trusted_tool(name: str) -> str:
    """Resolve one executable only from fixed installation roots."""

    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) is None:
        raise CheckError("required_tool_unavailable")
    candidates = (
        Path("/usr/bin") / name,
        Path("/usr/local/bin") / name,
        Path.home() / ".local" / "bin" / name,
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            details = resolved.stat()
        except OSError:
            continue
        if (
            stat.S_ISREG(details.st_mode)
            and not details.st_mode & 0o022
            and details.st_uid in {0, os.getuid()}
            and os.access(resolved, os.X_OK)
        ):
            return str(resolved)
    raise CheckError("required_tool_unavailable")


class CheckError(RuntimeError):
    """Carry a stable prerequisite failure and documented exit code."""

    def __init__(self, reason_code: str, exit_code: int = 4) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.exit_code = exit_code


class GenesisChecks:
    """Execute fixed external checks without exposing provider error output."""

    def __init__(self, repository_root: Path, *, environment: dict[str, str] | None = None) -> None:
        self.repository_root = repository_root
        self.environment = environment
        self.az = trusted_tool("az")
        self.bash = trusted_tool("bash")
        self.source_evidence = SignedSourceEvidence.from_environment()
        self.git = None if self.source_evidence is not None else trusted_tool("git")
        self.gh = None if self.source_evidence is not None else trusted_tool("gh")

    def verify_toolchain(self, *, apply: bool) -> None:
        """Require only read tools for inspection and the full apply toolchain for mutation."""

        required = [self.az, self.bash, trusted_tool("python3"), trusted_tool("timeout")]
        if self.source_evidence is None:
            git = self._required_git()
            required.append(git)
            if apply:
                gh = self._required_gh()
                required.extend(
                    (trusted_tool("azd"), gh, trusted_tool("terraform"), trusted_tool("uv"))
                )
        if any(not Path(command).is_file() for command in required):
            raise CheckError("required_tool_unavailable")

    def prepare_access_tools(self, *, timeout: int) -> None:
        """Pin and verify connected-access CLI extensions without creating Azure resources."""

        self.run_required(
            (
                self.bash,
                str(
                    self.repository_root
                    / "scripts/deployment/azure/prepare-genesis-access-tools.sh"
                ),
            ),
            "azure_access_tool_preparation_failed",
            timeout=timeout,
            capture=True,
        )

    def verify_target(self, *, subscription_id: str, tenant_id: str, region: str) -> None:
        """Verify both Azure identity axes and region availability without mutation."""

        account = self.capture(
            (
                self.az,
                "account",
                "show",
                "--subscription",
                subscription_id,
                "--query",
                "{id:id,tenantId:tenantId}",
                "--output",
                "json",
                "--only-show-errors",
            ),
            "azure_context_mismatch",
        )
        try:
            target = json.loads(account)
        except json.JSONDecodeError as exc:
            raise CheckError("azure_context_mismatch") from exc
        if (
            not isinstance(target, dict)
            or target.get("id") != subscription_id
            or target.get("tenantId") != tenant_id
        ):
            raise CheckError("azure_context_mismatch", 3)
        available = self.capture(
            (
                self.az,
                "rest",
                "--method",
                "get",
                "--url",
                (
                    "https://management.azure.com/subscriptions/"
                    f"{subscription_id}/locations?api-version=2022-12-01"
                ),
                "--query",
                f"value[?name == '{region}'].name | [0]",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            "azure_region_unavailable",
        )
        if available != region:
            raise CheckError("azure_region_unavailable", 3)

    def verify_source(
        self,
        *,
        source_commit: str,
        repository: str | None,
        apply: bool,
    ) -> None:
        """Require a clean pushed revision with an exact green required check before apply."""

        if not apply:
            return
        if self.source_evidence is not None:
            if source_commit != self.source_evidence.source_commit:
                raise CheckError("signed_source_revision_mismatch", 3)
            return
        git = self._required_git()
        gh = self._required_gh()
        dirty = self.capture(
            (git, "status", "--porcelain", "--untracked-files=all"),
            "source_status_unavailable",
        )
        if dirty:
            raise CheckError("apply_requires_clean_checkout", 3)
        if repository is None:
            raise CheckError("repository_required_for_apply", 64)
        remote = self.capture(
            (git, "remote", "get-url", "origin"),
            "source_repository_unavailable",
        )
        match = _GITHUB_REMOTE.fullmatch(remote)
        if match is None or match.group("repository").casefold() != repository.casefold():
            raise CheckError("repository_context_mismatch", 3)
        checks_raw = self.capture(
            (
                gh,
                "api",
                "-X",
                "GET",
                f"repos/{repository}/commits/{source_commit}/check-runs"
                "?check_name=required&filter=latest&per_page=100",
            ),
            "required_ci_unavailable",
            strip=False,
        )
        checks = json.loads(checks_raw).get("check_runs")
        if not isinstance(checks, list):
            raise CheckError("required_ci_unavailable")
        required = [
            item
            for item in checks
            if isinstance(item, dict)
            and item.get("name") == "required"
            and item.get("head_sha") == source_commit
            and isinstance(item.get("id"), int)
        ]
        required.sort(key=lambda item: int(item["id"]))
        latest = required[-1] if required else {}
        if (
            not required
            or not isinstance(latest.get("app"), dict)
            or latest["app"].get("slug") != "github-actions"
            or latest.get("status") != "completed"
            or latest.get("conclusion") != "success"
        ):
            raise CheckError("required_ci_not_green", 3)

    def verify_checkout_unchanged(self) -> None:
        """Fail when deployment tooling rewrites tracked or untracked source files."""

        if self.source_evidence is not None:
            return
        git = self._required_git()
        dirty = self.capture(
            (git, "status", "--porcelain", "--untracked-files=all"),
            "source_status_unavailable",
        )
        if dirty:
            raise CheckError("deployment_changed_tracked_source")

    def _required_git(self) -> str:
        if self.git is None:
            raise CheckError("source_verifier_unavailable")
        return self.git

    def _required_gh(self) -> str:
        if self.gh is None:
            raise CheckError("source_verifier_unavailable")
        return self.gh

    def run_required(
        self,
        arguments: tuple[str, ...],
        reason_code: str,
        *,
        timeout: int,
        env: dict[str, str] | None = None,
        capture: bool = False,
    ) -> None:
        """Run one bounded command and map all nonzero results to a stable reason."""

        try:
            completed = run_with_heartbeat(
                arguments,
                cwd=self.repository_root,
                env=env or self.environment,
                capture_output=capture,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CheckError(reason_code) from exc
        if completed.returncode != 0:
            raise CheckError(reason_code)

    def capture(
        self,
        arguments: tuple[str, ...],
        reason_code: str,
        *,
        strip: bool = True,
        timeout: int = 60,
        env: dict[str, str] | None = None,
    ) -> str:
        """Capture bounded command output or raise one stable error."""

        try:
            completed = run_with_heartbeat(
                arguments,
                cwd=self.repository_root,
                env=env or self.environment,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CheckError(reason_code) from exc
        if completed.returncode != 0:
            raise CheckError(reason_code)
        return completed.stdout.strip() if strip else completed.stdout
