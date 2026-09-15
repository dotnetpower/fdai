"""Collect immutable initial installation preferences without granting apply authority."""

from __future__ import annotations

import os
import re
import select
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile


@dataclass(frozen=True, slots=True)
class InstallationOptions:
    """Requested cost, exposure and retention limits; no execution authorization."""

    setup_cost_ceiling: int | None = None
    console_access: str = "public-https-entra"
    allow_dedicated_identities: bool = False
    cleanup_temporary_resources: bool = False

    def __post_init__(self) -> None:
        if self.setup_cost_ceiling is not None:
            _budget(self.setup_cost_ceiling)
        if self.console_access not in {"public-https-entra", "private-https-entra"}:
            raise ValueError("installation Console access is invalid")
        if any(
            type(value) is not bool
            for value in (self.allow_dedicated_identities, self.cleanup_temporary_resources)
        ):
            raise ValueError("installation scope flags must be booleans")


def confirm_installation_scope(
    *,
    work_dir: Path,
    binding: dict[str, object],
    runtime_profile: RuntimeDeploymentProfile,
    options: InstallationOptions,
    interactive: bool,
    timeout_seconds: int,
    now: datetime | None = None,
) -> dict[str, object]:
    """Confirm once before execution, or verify an unchanged unexpired retained scope.

    Noninteractive, denied, legacy-started, changed and expired runs never prompt
    later or renew consent. The record is not accepted as a Genesis approval.
    """
    _validate_binding(binding)
    if runtime_profile.digest != binding["runtime_profile_digest"]:
        raise ValueError("installation scope changed: runtime profile digest differs")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 86400:
        raise ValueError("installation scope lifetime must be between 1 and 86400 seconds")
    moment = now or datetime.now(UTC)
    _utc(moment)
    path = work_dir / "installation-scope.json"
    try:
        retained = load_json_object(
            read_private_bytes(path, max_bytes=16384), label="installation scope"
        )
    except FileNotFoundError:
        retained = None
    if retained is not None:
        expected = {
            "schema_version",
            "scope",
            "confirmed_at",
            "expires_at",
            "apply_authorized",
            "digest",
        }
        unsigned = {key: value for key, value in retained.items() if key != "digest"}
        if (
            set(retained) != expected
            or retained["schema_version"] != "fdai.installation-scope.v1"
            or retained["apply_authorized"] is not False
            or retained["digest"] != canonical_digest(unsigned)
        ):
            raise ValueError("retained installation scope is invalid")
        scope = retained["scope"]
        if not isinstance(scope, dict):
            raise ValueError("retained installation scope is invalid")
        setup_cost = options.setup_cost_ceiling
        if setup_cost is None:
            setup_cost = _budget(scope.get("setup_cost_ceiling"))
        if canonical_bytes(scope) != canonical_bytes(
            _scope(binding, runtime_profile, options, setup_cost)
        ):
            raise ValueError(
                "installation scope changed; preserve the run and review before restarting"
            )
        confirmed = _timestamp(retained["confirmed_at"])
        expires = _timestamp(retained["expires_at"])
        if not confirmed <= moment < expires or not timedelta(0) < expires - confirmed <= timedelta(
            days=1
        ):
            return _result("installation_scope_expired")
        return _result("installation_scope_confirmed", str(retained["digest"]))
    if (work_dir / "foundation/status.json").exists():
        return _result("initial_confirmation_missing_for_started_run")
    if not interactive:
        return _result("initial_confirmation_required")
    deadline = time.monotonic() + min(600, timeout_seconds)
    setup_cost = options.setup_cost_ceiling
    if setup_cost is None:
        print(
            "Initial setup cost estimate ceiling (USD, whole number): ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        answer = _read_initial_answer(deadline)
        if re.fullmatch(r"[1-9][0-9]{0,6}", answer) is None:
            return _result("initial_confirmation_denied")
        setup_cost = _budget(int(answer))
    scope = _scope(binding, runtime_profile, options, setup_cost)
    print("Initial installation scope (not an exact-plan approval):", file=sys.stderr)
    for key, value in scope.items():
        print(f"  {key}: {value}", file=sys.stderr)
    print(
        "Estimates are not billing caps. Existing resources and runtime authority are excluded.\n"
        "Later missing authority or evidence stops the run without another prompt.\n"
        "Type install to confirm these settings, or anything else to stop: ",
        end="",
        file=sys.stderr,
        flush=True,
    )
    if _read_initial_answer(deadline) != "install":
        return _result("initial_confirmation_denied")
    elapsed = min(600, timeout_seconds) - max(0.0, deadline - time.monotonic())
    confirmed_at = moment + timedelta(seconds=elapsed)
    if confirmed_at >= moment + timedelta(seconds=timeout_seconds):
        return _result("installation_scope_expired")
    record: dict[str, object] = {
        "schema_version": "fdai.installation-scope.v1",
        "scope": scope,
        "confirmed_at": confirmed_at.isoformat(),
        "expires_at": (moment + timedelta(seconds=timeout_seconds)).isoformat(),
        "apply_authorized": False,
    }
    record["digest"] = canonical_digest(record)
    write_private_bytes(path, canonical_bytes(record))
    return _result("installation_scope_confirmed", str(record["digest"]))


def _scope(
    binding: dict[str, object],
    runtime_profile: RuntimeDeploymentProfile,
    options: InstallationOptions,
    setup_cost: int,
) -> dict[str, object]:
    return {
        **binding,
        "runtime_profile": runtime_profile.to_mapping(),
        **asdict(options),
        "setup_cost_ceiling": setup_cost,
        "resource_scope": "new-installation-only",
        "retain_services": True,
        "runtime_authority_change": False,
    }


def _result(reason: str, digest: str | None = None) -> dict[str, object]:
    return {
        "schema_version": "fdai.installation-scope-result.v1",
        "state": "confirmed" if digest else "review",
        "stage": "initial-confirmation",
        "reason_code": reason,
        "scope_digest": digest,
        "apply_authorized": False,
        "mutation_performed": False,
        "deployment_ready": False,
    }


def _validate_binding(binding: dict[str, object]) -> None:
    if set(binding) != {
        "source_commit",
        "target_binding",
        "preparation_digest",
        "runtime_profile_digest",
        "region",
        "monthly_cost_ceiling",
    }:
        raise ValueError("installation scope binding fields are invalid")
    for key in ("source_commit", "target_binding", "preparation_digest", "runtime_profile_digest"):
        value = binding[key]
        length = 40 if key == "source_commit" else 64
        if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
            raise ValueError("installation scope binding digest is invalid")
    region = binding["region"]
    if not isinstance(region, str) or re.fullmatch(r"[a-z][a-z0-9]{1,40}", region) is None:
        raise ValueError("installation scope region is invalid")
    _budget(binding["monthly_cost_ceiling"])


def _budget(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 1000000:
        raise ValueError(
            "installation cost ceiling must be a whole USD amount between 1 and 1000000"
        )
    return value


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("installation scope timestamp must be UTC")


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("installation scope timestamp is invalid")
    result = datetime.fromisoformat(value)
    _utc(result)
    return result


def _read_initial_answer(deadline: float) -> str:
    """Read one bounded TTY line without an unbounded readline after partial input."""
    if not sys.stdin.isatty():
        raise ValueError("initial confirmation requires an interactive terminal")
    descriptor = sys.stdin.fileno()
    answer = bytearray()
    while len(answer) <= 64:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([descriptor], [], [], remaining)[0]:
            raise TimeoutError("initial confirmation timed out; no consent was recorded")
        chunk = os.read(descriptor, 1)
        if not chunk:
            raise ValueError("initial confirmation input closed; no consent was recorded")
        if chunk == b"\n":
            return answer.decode("ascii").strip()
        answer.extend(chunk)
    raise ValueError("initial confirmation input exceeds its limit")
