"""Plan exact Console content updates for existing Azure installations."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import (
    copy_private_file,
    read_private_bytes,
    write_private_output,
)
from fdai_deployment_cli.standalone_application import publish_verified_console
from fdai_deployment_cli.target import compute_target_binding

_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_HOSTNAME = re.compile(r"[a-z0-9-]+(?:[.][0-9]+)?[.]azurestaticapps[.]net")
_RESOURCE_ID = re.compile(
    r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
    r"Microsoft[.]Web/staticSites/([^/]+)",
    re.IGNORECASE,
)
_MAX_TARGET_BYTES = 16_384
_MAX_MANIFEST_BYTES = 4096
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_ARTIFACT_FIELDS = frozenset({"schema_version", "source_commit", "archive_sha256"})
_TARGET_FIELDS = frozenset(
    {
        "schema_version",
        "environment",
        "subscription_id",
        "tenant_id",
        "console_static_web_app_id",
        "console_hostname",
        "operator_api_base_url",
        "ingestion_api_base_url",
        "entra_console_spa_client_id",
        "entra_console_api_scope",
    }
)
_PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "environment",
        "source_commit",
        "rollback_source_commit",
        "target_binding",
        "target_digest",
        "candidate_archive_sha256",
        "rollback_archive_sha256",
        "action",
        "stop_condition",
        "rollback_action",
        "blast_radius",
        "logical_target",
        "idempotency_key",
        "created_at",
        "expires_at",
        "mutation_performed",
        "plan_digest",
    }
)


@dataclass(frozen=True, slots=True)
class ConsoleUpdateTarget:
    """Secret-free existing Console binding supplied outside source control."""

    environment: str
    subscription_id: str
    tenant_id: str
    console_static_web_app_id: str
    console_hostname: str
    operator_api_base_url: str
    ingestion_api_base_url: str
    entra_console_spa_client_id: str
    entra_console_api_scope: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConsoleUpdateTarget:
        """Decode a closed target manifest and reject unsafe endpoint bindings."""

        if (
            set(value) != _TARGET_FIELDS
            or value.get("schema_version") != "fdai.console-update-target.v1"
        ):
            raise ValueError("Console update target fields are invalid")
        text = {
            key: item
            for key, item in value.items()
            if key != "schema_version" and isinstance(item, str)
        }
        if len(text) != len(_TARGET_FIELDS) - 1:
            raise ValueError("Console update target values MUST be strings")
        target = cls(**text)
        target.validate()
        return target

    def validate(self) -> None:
        """Validate the development-only target and its public, non-secret bindings."""

        if self.environment != "dev":
            raise ValueError("existing Console source updates are supported only in dev")
        for label, value in (
            ("subscription", self.subscription_id),
            ("tenant", self.tenant_id),
            ("Console SPA client", self.entra_console_spa_client_id),
        ):
            if _GUID.fullmatch(value) is None:
                raise ValueError(f"Console update {label} id is invalid")
        match = _RESOURCE_ID.fullmatch(self.console_static_web_app_id)
        if match is None or match.group(1).casefold() != self.subscription_id:
            raise ValueError("Console update Static Web App resource id is invalid")
        if _HOSTNAME.fullmatch(self.console_hostname) is None:
            raise ValueError("Console update hostname is invalid")
        for label, value in (
            ("Operator API", self.operator_api_base_url),
            ("ingestion API", self.ingestion_api_base_url),
        ):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"Console update {label} URL is invalid")
        expected_scope_prefix = f"api://{self.entra_console_spa_client_id}/"
        if not self.entra_console_api_scope.startswith(expected_scope_prefix):
            raise ValueError("Console update API scope does not match the SPA client")

    @property
    def target_binding(self) -> str:
        """Return the canonical tenant and subscription binding."""

        return compute_target_binding(
            tenant_id=self.tenant_id,
            subscription_id=self.subscription_id,
        )

    def to_mapping(self) -> dict[str, str]:
        """Return canonical target data for a private plan."""

        return {
            "schema_version": "fdai.console-update-target.v1",
            "environment": self.environment,
            "subscription_id": self.subscription_id,
            "tenant_id": self.tenant_id,
            "console_static_web_app_id": self.console_static_web_app_id,
            "console_hostname": self.console_hostname,
            "operator_api_base_url": self.operator_api_base_url,
            "ingestion_api_base_url": self.ingestion_api_base_url,
            "entra_console_spa_client_id": self.entra_console_spa_client_id,
            "entra_console_api_scope": self.entra_console_api_scope,
        }


def prepare_console_update_plan(
    *,
    source_root: Path,
    candidate_archive: Path,
    candidate_manifest: Path,
    rollback_archive: Path,
    rollback_manifest: Path,
    target_file: Path,
    work_dir: Path,
    ttl_seconds: int = 1200,
    timeout_seconds: int = 60,
) -> dict[str, object]:
    """Create a private exact plan without changing Azure or published content."""

    if not 60 <= ttl_seconds <= 1200:
        raise ValueError("Console update plan TTL MUST be between 60 and 1200 seconds")
    source_commit = _verified_source_commit(source_root, timeout_seconds=timeout_seconds)
    target = _load_target(target_file)
    _verify_active_target(target, timeout_seconds=timeout_seconds)
    _verify_static_site(target, timeout_seconds=timeout_seconds)
    candidate = _load_artifact_manifest(candidate_manifest, candidate_archive)
    rollback = _load_artifact_manifest(rollback_manifest, rollback_archive)
    if candidate["source_commit"] != source_commit:
        raise ValueError("Console candidate artifact does not match protected origin/main")
    if rollback["source_commit"] == source_commit:
        raise ValueError("Console rollback artifact MUST use a distinct source revision")
    candidate_digest = candidate["archive_sha256"]
    rollback_digest = rollback["archive_sha256"]
    if candidate_digest == rollback_digest:
        raise ValueError("Console candidate and rollback archives MUST differ")
    if work_dir.exists() or work_dir.is_symlink():
        raise ValueError("Console update work directory already exists")
    work_dir.mkdir(mode=0o700, parents=False)
    copy_private_file(
        candidate_archive, work_dir / "candidate.tar.gz", max_bytes=_MAX_ARCHIVE_BYTES
    )
    copy_private_file(rollback_archive, work_dir / "rollback.tar.gz", max_bytes=_MAX_ARCHIVE_BYTES)
    target_copy = work_dir / "target.json"
    write_private_output(
        target_copy,
        json.dumps(target.to_mapping(), sort_keys=True, separators=(",", ":")) + "\n",
    )
    plan: dict[str, object] = {
        "schema_version": "fdai.console-update-plan.v1",
        "environment": target.environment,
        "source_commit": source_commit,
        "rollback_source_commit": rollback["source_commit"],
        "target_binding": target.target_binding,
        "target_digest": canonical_digest(target.to_mapping()),
        "candidate_archive_sha256": candidate_digest,
        "rollback_archive_sha256": rollback_digest,
        "action": "publish_console_static_content",
        "stop_condition": "candidate_readback_mismatch",
        "rollback_action": "republish_verified_rollback_archive",
        "blast_radius": "one_existing_static_web_app",
        "logical_target": canonical_digest(
            {
                "target_binding": target.target_binding,
                "resource_id": target.console_static_web_app_id.casefold(),
            }
        ),
        "idempotency_key": canonical_digest(
            {
                "target_binding": target.target_binding,
                "candidate_archive_sha256": candidate_digest,
            }
        ),
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat(),
        "mutation_performed": False,
    }
    plan["plan_digest"] = canonical_digest(plan)
    write_private_output(
        work_dir / "plan.json",
        json.dumps(plan, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return plan


def apply_console_update_plan(
    *,
    source_root: Path,
    work_dir: Path,
    approved_plan_digest: str,
    scripts: Path,
    timeout_seconds: int = 900,
) -> dict[str, object]:
    """Apply one exact Console plan, or recover an existing claim by readback."""

    plan = _load_plan(work_dir / "plan.json")
    if approved_plan_digest != plan["plan_digest"]:
        raise ValueError("Console update approval does not match the exact plan digest")
    source_commit = _verified_source_commit(source_root, timeout_seconds=min(timeout_seconds, 60))
    if source_commit != plan["source_commit"]:
        raise ValueError("Console update source changed after planning")
    target = _load_target(work_dir / "target.json")
    if (
        target.target_binding != plan["target_binding"]
        or canonical_digest(target.to_mapping()) != plan["target_digest"]
    ):
        raise ValueError("Console update target changed after planning")
    _verify_active_target(target, timeout_seconds=min(timeout_seconds, 60))
    _verify_static_site(target, timeout_seconds=min(timeout_seconds, 60))
    _require_digest(work_dir / "candidate.tar.gz", str(plan["candidate_archive_sha256"]))
    _require_digest(work_dir / "rollback.tar.gz", str(plan["rollback_archive_sha256"]))

    lock_descriptor = os.open(
        work_dir / "target.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Console update target is locked by another local operation") from exc
        receipt_path = work_dir / "receipt.json"
        if receipt_path.exists():
            return _load_receipt(receipt_path, plan)
        failure_path = work_dir / "failure.json"
        if failure_path.exists():
            _load_failure(failure_path, plan)
            raise ValueError(
                "Console update previously failed and the verified rollback was restored"
            )
        claim_path = work_dir / "claim.json"
        actor_digest = _active_actor_digest(target, timeout_seconds=min(timeout_seconds, 60))
        if claim_path.exists():
            try:
                candidate = _publish(
                    source_root=source_root,
                    work_dir=work_dir / "candidate-verify",
                    archive=work_dir / "candidate.tar.gz",
                    archive_digest=str(plan["candidate_archive_sha256"]),
                    target=target,
                    scripts=scripts,
                    timeout_seconds=timeout_seconds,
                    verify_only=True,
                )
            except (OSError, subprocess.SubprocessError, ValueError) as verification_error:
                try:
                    rollback = _publish(
                        source_root=source_root,
                        work_dir=work_dir / "rollback-recovery",
                        archive=work_dir / "rollback.tar.gz",
                        archive_digest=str(plan["rollback_archive_sha256"]),
                        target=target,
                        scripts=scripts,
                        timeout_seconds=timeout_seconds,
                        verify_only=False,
                    )
                except (OSError, subprocess.SubprocessError, ValueError) as rollback_error:
                    raise ValueError(
                        "Console update readback and rollback both failed; retain the claim for review"
                    ) from rollback_error
                _write_failure_receipt(
                    failure_path,
                    plan=plan,
                    actor_digest=actor_digest,
                    rollback=rollback,
                    reason="claimed_candidate_readback_failed",
                )
                raise ValueError(
                    "Console update readback failed and the verified rollback was restored"
                ) from verification_error
            return _write_apply_receipt(
                receipt_path,
                plan=plan,
                actor_digest=actor_digest,
                publication=candidate,
                recovered_by_readback=True,
            )
        approval = {
            "schema_version": "fdai.console-update-approval.v1",
            "plan_digest": plan["plan_digest"],
            "target_binding": plan["target_binding"],
            "actor_digest": actor_digest,
            "approved_at": datetime.now(UTC).isoformat(),
        }
        approval["approval_digest"] = canonical_digest(approval)
        write_private_output(
            work_dir / "approval.json",
            json.dumps(approval, sort_keys=True, separators=(",", ":")) + "\n",
        )
        claim = {
            "schema_version": "fdai.console-update-claim.v1",
            "plan_digest": plan["plan_digest"],
            "approval_digest": approval["approval_digest"],
            "idempotency_key": plan["idempotency_key"],
            "claimed_at": datetime.now(UTC).isoformat(),
        }
        claim["claim_digest"] = canonical_digest(claim)
        write_private_output(
            claim_path,
            json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
        )
        try:
            candidate = _publish(
                source_root=source_root,
                work_dir=work_dir / "candidate-publish",
                archive=work_dir / "candidate.tar.gz",
                archive_digest=str(plan["candidate_archive_sha256"]),
                target=target,
                scripts=scripts,
                timeout_seconds=timeout_seconds,
                verify_only=False,
            )
        except (OSError, subprocess.SubprocessError, ValueError) as publish_error:
            try:
                rollback = _publish(
                    source_root=source_root,
                    work_dir=work_dir / "rollback-publish",
                    archive=work_dir / "rollback.tar.gz",
                    archive_digest=str(plan["rollback_archive_sha256"]),
                    target=target,
                    scripts=scripts,
                    timeout_seconds=timeout_seconds,
                    verify_only=False,
                )
            except (OSError, subprocess.SubprocessError, ValueError) as rollback_error:
                raise ValueError(
                    "Console update and rollback both failed; retain the claim for review"
                ) from rollback_error
            _write_failure_receipt(
                failure_path,
                plan=plan,
                actor_digest=actor_digest,
                rollback=rollback,
                reason="candidate_publication_failed",
            )
            raise ValueError(
                "Console update failed and the verified rollback was restored"
            ) from publish_error
        return _write_apply_receipt(
            receipt_path,
            plan=plan,
            actor_digest=actor_digest,
            publication=candidate,
            recovered_by_readback=False,
        )
    finally:
        os.close(lock_descriptor)


def _publish(
    *,
    source_root: Path,
    work_dir: Path,
    archive: Path,
    archive_digest: str,
    target: ConsoleUpdateTarget,
    scripts: Path,
    timeout_seconds: int,
    verify_only: bool,
) -> dict[str, object]:
    work_dir.mkdir(mode=0o700)
    return publish_verified_console(
        console_archive=archive,
        console_archive_sha256=archive_digest,
        bundle_root=source_root,
        prepared_root=work_dir,
        entra_bindings={
            "ENTRA_CONSOLE_SPA_CLIENT_ID": target.entra_console_spa_client_id,
            "ENTRA_CONSOLE_API_SCOPE": target.entra_console_api_scope,
        },
        browser_console={
            "console_hostname": target.console_hostname,
            "console_origin": f"https://{target.console_hostname}",
            "console_static_web_app_id": target.console_static_web_app_id,
            "operator_api_base_url": target.operator_api_base_url,
            "ingestion_api_base_url": target.ingestion_api_base_url,
        },
        scripts=scripts,
        subscription_id=target.subscription_id,
        tenant_id=target.tenant_id,
        timeout_seconds=timeout_seconds,
        redirect_changed=False,
        verify_only=verify_only,
    )


def _write_apply_receipt(
    path: Path,
    *,
    plan: dict[str, object],
    actor_digest: str,
    publication: dict[str, object],
    recovered_by_readback: bool,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "fdai.console-update-receipt.v1",
        "state": "applied",
        "plan_digest": plan["plan_digest"],
        "target_binding": plan["target_binding"],
        "candidate_archive_sha256": plan["candidate_archive_sha256"],
        "actor_digest": actor_digest,
        "publication_receipt_digest": publication["receipt_digest"],
        "artifact_readback_verified": True,
        "api_health_verified": publication["api_health_verified"],
        "authorization_preflight_verified": publication["authorization_preflight_verified"],
        "entra_redirect_verified": publication["entra_redirect_verified"],
        "recovered_by_readback": recovered_by_readback,
        "completed_at": datetime.now(UTC).isoformat(),
        "mutation_performed": not recovered_by_readback,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    write_private_output(path, json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
    return receipt


def _write_failure_receipt(
    path: Path,
    *,
    plan: dict[str, object],
    actor_digest: str,
    rollback: dict[str, object],
    reason: str,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "fdai.console-update-failure.v1",
        "state": "rolled_back",
        "reason": reason,
        "plan_digest": plan["plan_digest"],
        "target_binding": plan["target_binding"],
        "rollback_archive_sha256": plan["rollback_archive_sha256"],
        "actor_digest": actor_digest,
        "rollback_publication_receipt_digest": rollback["receipt_digest"],
        "rollback_readback_verified": True,
        "completed_at": datetime.now(UTC).isoformat(),
        "mutation_performed": True,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    write_private_output(path, json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
    return receipt


def load_console_update_plan(path: Path) -> dict[str, object]:
    """Load and validate one unexpired private Console update plan."""

    return _load_plan(path)


def _load_plan(path: Path) -> dict[str, object]:
    try:
        value = json.loads(read_private_bytes(path, max_bytes=32_768))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Console update plan is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != _PLAN_FIELDS:
        raise ValueError("Console update plan fields are invalid")
    plan = cast(dict[str, object], value)
    digest = plan.get("plan_digest")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("Console update plan digest is invalid")
    if (
        canonical_digest({key: item for key, item in plan.items() if key != "plan_digest"})
        != digest
    ):
        raise ValueError("Console update plan content digest is invalid")
    expiry = plan.get("expires_at")
    try:
        expires_at = datetime.fromisoformat(str(expiry))
    except ValueError as exc:
        raise ValueError("Console update plan expiry is invalid") from exc
    if expires_at.tzinfo is None or expires_at <= datetime.now(UTC):
        raise ValueError("Console update plan is expired")
    return plan


def _load_receipt(path: Path, plan: dict[str, object]) -> dict[str, object]:
    try:
        value = json.loads(read_private_bytes(path, max_bytes=32_768))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Console update receipt is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "fdai.console-update-receipt.v1"
        or value.get("state") != "applied"
        or value.get("plan_digest") != plan["plan_digest"]
        or value.get("artifact_readback_verified") is not True
    ):
        raise ValueError("Console update receipt does not match the plan")
    digest = value.get("receipt_digest")
    if digest != canonical_digest(
        {key: item for key, item in value.items() if key != "receipt_digest"}
    ):
        raise ValueError("Console update receipt digest is invalid")
    return cast(dict[str, object], value)


def _load_failure(path: Path, plan: dict[str, object]) -> dict[str, object]:
    try:
        value = json.loads(read_private_bytes(path, max_bytes=32_768))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Console update failure receipt is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "fdai.console-update-failure.v1"
        or value.get("state") != "rolled_back"
        or value.get("plan_digest") != plan["plan_digest"]
        or value.get("rollback_readback_verified") is not True
    ):
        raise ValueError("Console update failure receipt does not match the plan")
    digest = value.get("receipt_digest")
    if digest != canonical_digest(
        {key: item for key, item in value.items() if key != "receipt_digest"}
    ):
        raise ValueError("Console update failure receipt digest is invalid")
    return cast(dict[str, object], value)


def _active_actor_digest(target: ConsoleUpdateTarget, *, timeout_seconds: int) -> str:
    completed = subprocess.run(
        (
            "az",
            "account",
            "show",
            "--query",
            "{subscription_id:id,tenant_id:tenantId,user_name:user.name,user_type:user.type}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Console update approval actor is unavailable") from exc
    if (
        completed.returncode != 0
        or value.get("subscription_id") != target.subscription_id
        or value.get("tenant_id") != target.tenant_id
        or str(value.get("user_type", "")).casefold() != "user"
        or not isinstance(value.get("user_name"), str)
        or not value["user_name"]
    ):
        raise ValueError("Console update requires the active Azure human user")
    return hashlib.sha256(
        f"{target.target_binding}:{value['user_name'].casefold()}".encode()
    ).hexdigest()


def _require_digest(path: Path, expected: str) -> None:
    if _regular_digest(path) != expected:
        raise ValueError("Console update archive changed after planning")


def _load_target(path: Path) -> ConsoleUpdateTarget:
    try:
        value = json.loads(read_private_bytes(path, max_bytes=_MAX_TARGET_BYTES))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Console update target is not valid JSON") from exc
    if not isinstance(value, dict):
        raise TypeError("Console update target MUST contain an object")
    return ConsoleUpdateTarget.from_mapping(value)


def _load_artifact_manifest(path: Path, archive: Path) -> dict[str, str]:
    try:
        value = json.loads(read_private_bytes(path, max_bytes=_MAX_MANIFEST_BYTES))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Console artifact manifest is not valid JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) != _ARTIFACT_FIELDS
        or value.get("schema_version") != "fdai.console-update-artifact.v1"
        or not isinstance(value.get("source_commit"), str)
        or _COMMIT.fullmatch(str(value["source_commit"])) is None
        or not isinstance(value.get("archive_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(value["archive_sha256"])) is None
    ):
        raise ValueError("Console artifact manifest fields are invalid")
    result = cast(dict[str, str], value)
    if _regular_digest(archive) != result["archive_sha256"]:
        raise ValueError("Console artifact does not match its manifest")
    return result


def _verified_source_commit(source_root: Path, *, timeout_seconds: int) -> str:
    if not source_root.is_absolute() or not source_root.is_dir() or source_root.is_symlink():
        raise ValueError("Console update source MUST be an absolute regular directory")
    head = _git(source_root, "rev-parse", "HEAD", timeout_seconds=timeout_seconds).stdout.strip()
    if _COMMIT.fullmatch(head) is None:
        raise ValueError("Console update source revision is invalid")
    status = _git(
        source_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
        timeout_seconds=timeout_seconds,
    )
    if status.stdout:
        raise ValueError("Console update source has tracked changes")
    protected_head = _git(
        source_root,
        "rev-parse",
        "refs/remotes/origin/main",
        timeout_seconds=timeout_seconds,
    ).stdout.strip()
    if head != protected_head:
        raise ValueError("Console update source MUST match protected origin/main")
    return head


def _git(
    source_root: Path, *arguments: str, timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ("git", "-C", str(source_root), *arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise ValueError("Console update source could not be verified")
    return completed


def _verify_active_target(target: ConsoleUpdateTarget, *, timeout_seconds: int) -> None:
    completed = subprocess.run(
        (
            "az",
            "account",
            "show",
            "--query",
            "{subscription_id:id,tenant_id:tenantId}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    try:
        observed = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("active Azure target is unavailable") from exc
    if completed.returncode != 0 or observed != {
        "subscription_id": target.subscription_id,
        "tenant_id": target.tenant_id,
    }:
        raise ValueError("active Azure target does not match the Console update target")


def _verify_static_site(target: ConsoleUpdateTarget, *, timeout_seconds: int) -> None:
    completed = subprocess.run(
        (
            "az",
            "rest",
            "--method",
            "get",
            "--url",
            (
                "https://management.azure.com"
                f"{target.console_static_web_app_id}?api-version=2023-12-01"
            ),
            "--query",
            "properties.defaultHostname",
            "--output",
            "tsv",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0 or completed.stdout.strip().casefold() != target.console_hostname:
        raise ValueError("Console update target does not match Azure readback")


def _regular_digest(path: Path) -> str:
    if not path.is_absolute():
        raise ValueError("Console archives MUST use absolute paths")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or not 0 < before.st_size <= _MAX_ARCHIVE_BYTES
        ):
            raise ValueError("Console archive is not an owned bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(descriptor)
        if (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Console archive changed while it was read")
        return digest
    finally:
        os.close(descriptor)
