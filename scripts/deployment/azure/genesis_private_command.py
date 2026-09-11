#!/usr/bin/env python3
"""Run private Genesis child commands and project only portable result fields."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from genesis_private_errors import PrivateExecutionError
from genesis_subprocess import run_with_heartbeat

_DIGEST = re.compile(r"[0-9a-f]{64}")
_SAFE_RESULT_FIELDS: dict[str, frozenset[str]] = {
    "fdai.genesis-runner-image-plan-result.v1": frozenset(
        {
            "schema_version",
            "state",
            "review_digest",
            "plan_digest",
            "expires_at",
            "create_count",
            "retained_resource_count",
            "lifecycle_actions",
            "effect_summary",
            "apply_authorized",
            "mutation_performed",
            "subscription_ready",
            "plan_ref",
        }
    ),
    "fdai.genesis-runner-image-apply-receipt.v1": frozenset(
        {
            "schema_version",
            "state",
            "review_digest",
            "plan_digest",
            "toolchain_digest",
            "effect_verified",
            "runner_registered",
            "mutation_performed",
            "subscription_ready",
            "completed_at",
            "receipt_digest",
        }
    ),
    "fdai.genesis-foundation-plan.v1": frozenset(
        {
            "schema_version",
            "state",
            "plan_ref",
            "attempt",
            "review_digest",
            "plan_digest",
            "expires_at",
            "integrity_verified",
            "apply_authorized",
            "mutation_performed",
            "subscription_ready",
        }
    ),
    "fdai.genesis-foundation-apply-receipt.v1": frozenset(
        {
            "schema_version",
            "state",
            "review_digest",
            "plan_digest",
            "handoff_digest",
            "control_plane_readback_verified",
            "zero_change_verified",
            "remote_backend_authority_verified",
            "runner_attested",
            "mutation_performed",
            "subscription_ready",
            "completed_at",
            "receipt_digest",
        }
    ),
    "fdai.genesis-runner-enrollment-receipt.v1": frozenset(
        {
            "schema_version",
            "state",
            "runner_count",
            "identity_attested",
            "services_attested",
            "github_readback_verified",
            "manual_host_readback_verified",
            "effect_verified",
            "mutation_performed",
            "subscription_ready",
            "receipt_digest",
        }
    ),
    "fdai.genesis-foundation-state-handoff-receipt.v1": frozenset(
        {
            "schema_version",
            "state",
            "managed_resource_count",
            "remote_backend_authority_verified",
            "zero_change_verified",
            "local_state_deleted",
            "remote_transient_deleted",
            "effect_verified",
            "mutation_performed",
            "subscription_ready",
            "receipt_digest",
        }
    ),
}

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class PrivateCommandContext:
    """Target and source paths supplied to every private child command."""

    repository_root: Path
    subscription_id: str
    tenant_id: str


class PrivateCommandExecutor:
    """Execute fixed repository scripts with bounded, redacted failure behavior."""

    def __init__(
        self,
        context: PrivateCommandContext,
        *,
        run_child: CommandRunner = run_with_heartbeat,
    ) -> None:
        self.context = context
        self._run_child = run_child

    def run_json(
        self,
        script_name: str,
        arguments: tuple[str, ...],
        *,
        stage: str,
        reason: str,
        timeout: int,
    ) -> dict[str, object]:
        """Run one fixed child and parse its successful JSON without retaining diagnostics."""

        script = self.context.repository_root / "scripts/deployment/azure" / script_name
        environment = {
            **os.environ,
            "AZURE_SUBSCRIPTION_ID": self.context.subscription_id,
            "AZURE_TENANT_ID": self.context.tenant_id,
        }
        try:
            completed = self._run_child(
                ("/bin/bash", str(script), *arguments),
                cwd=self.context.repository_root,
                env=environment,
                capture_output=True,
                timeout=timeout,
                umask=0o077,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PrivateExecutionError(stage, reason, 3) from exc
        if completed.returncode != 0:
            exit_code = 3 if completed.returncode in {2, 3} else 4
            raise PrivateExecutionError(stage, reason, exit_code)
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise PrivateExecutionError(stage, f"{reason}_result_invalid") from exc
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            raise PrivateExecutionError(stage, f"{reason}_result_invalid")
        return {key: item for key, item in value.items()}


def require_private_result(
    value: Mapping[str, object],
    *,
    stage: str,
    schema: str,
    state: str,
    receipt: bool = False,
) -> None:
    """Validate the no-readiness result envelope returned by a private child."""

    digest = value.get("receipt_digest")
    if (
        value.get("schema_version") != schema
        or value.get("state") != state
        or value.get("subscription_ready") is not False
        or (receipt and (not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None))
    ):
        raise PrivateExecutionError(stage, "private_checkpoint_result_invalid")


def safe_private_projection(value: Mapping[str, object], *, stage: str) -> dict[str, object]:
    """Drop resource identities, host paths, and other private child-only fields."""

    schema = value.get("schema_version")
    if not isinstance(schema, str) or schema not in _SAFE_RESULT_FIELDS:
        raise PrivateExecutionError(stage, "private_checkpoint_result_invalid")
    return {key: item for key, item in value.items() if key in _SAFE_RESULT_FIELDS[schema]}
