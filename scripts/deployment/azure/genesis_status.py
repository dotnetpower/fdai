#!/usr/bin/env python3
"""Persist and render sanitized progress for Azure Genesis orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = "fdai.genesis-orchestration-status.v2"
_LEGACY_SCHEMA_VERSION = "fdai.genesis-orchestration-status.v1"
_LEGACY_STAGES = frozenset(
    {"toolchain", "target", "source", "providers", "policy", "route", "execution", "verification"}
)
PRIVATE_FOUNDATION_STAGES = (
    "runner-image-plan",
    "runner-image-apply",
    "foundation-plan",
    "foundation-apply",
    "runner-enrollment",
    "foundation-state",
)
STAGES = (
    ("toolchain", "Toolchain prerequisites"),
    ("target", "Azure target verification"),
    ("source", "Source and required CI"),
    ("providers", "Azure resource providers"),
    ("policy", "Tenant policy route"),
    ("route", "Deployment route selection"),
    ("runner-image-plan", "Runner image exact plan"),
    ("runner-image-apply", "Runner image exact apply"),
    ("foundation-plan", "Foundation exact plan"),
    ("foundation-apply", "Foundation exact apply"),
    ("runner-enrollment", "Runner enrollment and attestation"),
    ("foundation-state", "Foundation private state handoff"),
    ("application-plan", "Protected application exact plan"),
    ("application-apply", "Protected application exact apply"),
    ("verification", "Post-deployment verification"),
)


class StatusStoreError(RuntimeError):
    """Report an unsafe or invalid local progress record."""


class StatusStore:
    """Persist sanitized monotonic progress in one owner-only JSON record."""

    def __init__(
        self,
        *,
        path: Path,
        source_commit: str,
        target_binding: str,
        mode: str,
        deadline_at: str,
    ) -> None:
        self.path = path
        self.source_commit = source_commit
        self.target_binding = target_binding
        self.mode = mode
        self._ensure_private_directory(path.parent)
        prior = self._read_prior()
        prior_deadline_is_current = bool(prior) and _timestamp_is_future(str(prior["deadline_at"]))
        prior_policy = _prior_report(prior, "policy_report") if prior else None
        unresolved_policy_probe = bool(
            prior_policy
            and prior_policy.get("state") == "probing"
            and prior.get("mutation_performed") is True
        )
        private_checkpoint_resume = bool(
            prior
            and prior.get("route") == "private-runner"
            and _prior_report(prior, "foundation_report") is not None
        )
        continuing = (
            bool(prior)
            and prior.get("state") != "complete"
            and (prior_deadline_is_current or unresolved_policy_probe or private_checkpoint_resume)
        )
        self.deadline_at = (
            str(prior["deadline_at"]) if continuing and prior_deadline_is_current else deadline_at
        )
        self.attempt = int(prior.get("attempt", 0)) + 1 if prior else 1
        self.sequence = int(prior.get("sequence", 0)) if continuing else 0
        self.started_at = str(prior.get("started_at", _timestamp())) if continuing else _timestamp()
        self.completed = set(prior.get("completed_stages", ())) if continuing else set()
        self.skipped = set(prior.get("skipped_stages", ())) if continuing else set()
        self.mutation_performed = (
            bool(prior.get("mutation_performed", False)) if continuing else False
        )
        self.route = str(prior.get("route", "undetermined")) if continuing else "undetermined"
        self.provider_report = _prior_report(prior, "provider_report") if continuing else None
        self.policy_report = prior_policy if continuing else None
        self.foundation_report = _prior_report(prior, "foundation_report") if continuing else None
        self.payload: dict[str, object] = {}

    def mark_skipped(self, *stages: str) -> None:
        """Mark route-inapplicable stages terminal without claiming their effects occurred."""

        stage_ids = {item[0] for item in STAGES}
        if not stages or any(stage not in stage_ids for stage in stages):
            raise ValueError("unknown orchestration stage")
        self.skipped.update(stages)
        self.completed.update(stages)

    def update(
        self,
        *,
        stage: str,
        state: str,
        completed: bool = False,
        reason_code: str | None = None,
        next_action: str | None = None,
    ) -> None:
        """Append one monotonic progress transition by atomic file replacement."""

        stage_ids = [item[0] for item in STAGES]
        if stage not in stage_ids:
            raise ValueError("unknown orchestration stage")
        if completed:
            self.completed.add(stage)
        self.sequence += 1
        completed_stages = [value for value in stage_ids if value in self.completed]
        skipped_stages = [value for value in stage_ids if value in self.skipped]
        remaining = [value for value in stage_ids if value not in self.completed]
        percent = len(completed_stages) * 100 // len(stage_ids)
        self.payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": _run_id(self.target_binding, self.source_commit, self.mode),
            "attempt": self.attempt,
            "sequence": self.sequence,
            "mode": self.mode,
            "state": state,
            "route": self.route,
            "current_stage": stage,
            "stages_completed": len(completed_stages),
            "stages_total": len(stage_ids),
            "progress_percent": percent,
            "completed_stages": completed_stages,
            "skipped_stages": skipped_stages,
            "stages_skipped": len(skipped_stages),
            "remaining_stages": remaining,
            "reason_code": reason_code,
            "next_action": next_action,
            "source_commit": self.source_commit,
            "target_binding": self.target_binding,
            "started_at": self.started_at,
            "last_progress_at": _timestamp(),
            "deadline_at": self.deadline_at,
            "mutation_performed": self.mutation_performed,
            "subscription_ready": False,
            "provider_report": self.provider_report,
            "policy_report": self.policy_report,
            "foundation_report": self.foundation_report,
        }
        self._write()
        render_progress(self.payload)

    def remaining_seconds(self) -> int:
        """Return the nonnegative whole seconds left in the persisted run deadline."""

        current = datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint
        return max(0, int((_parse_timestamp(self.deadline_at) - current).total_seconds()))

    def _read_prior(self) -> dict[str, Any]:
        try:
            self.path.lstat()
        except FileNotFoundError:
            return {}
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags)
        except OSError as exc:
            raise StatusStoreError("unsafe_existing_status_file") from exc
        try:
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or stat.S_IMODE(details.st_mode) != 0o600
                or details.st_uid != os.geteuid()
            ):
                raise StatusStoreError("unsafe_existing_status_file")
            with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
                descriptor = -1
                value = json.load(stream)
        except json.JSONDecodeError as exc:
            raise StatusStoreError("invalid_existing_status_file") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if not isinstance(value, dict):
            raise StatusStoreError("invalid_existing_status_file")
        schema_version = value.get("schema_version")
        if schema_version not in {_SCHEMA_VERSION, _LEGACY_SCHEMA_VERSION}:
            raise StatusStoreError("invalid_existing_status_file")
        for field in ("attempt", "sequence"):
            item = value.get(field)
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise StatusStoreError("invalid_existing_status_file")
        if not isinstance(value.get("state"), str):
            raise StatusStoreError("invalid_existing_status_file")
        if not isinstance(value.get("started_at"), str):
            raise StatusStoreError("invalid_existing_status_file")
        deadline = value.get("deadline_at")
        if not isinstance(deadline, str):
            raise StatusStoreError("invalid_existing_status_file")
        _parse_timestamp(deadline)
        completed_stages = value.get("completed_stages")
        if not isinstance(completed_stages, list) or not all(
            isinstance(item, str) for item in completed_stages
        ):
            raise StatusStoreError("invalid_existing_status_file")
        accepted_stages = (
            _LEGACY_STAGES
            if schema_version == _LEGACY_SCHEMA_VERSION
            else {item[0] for item in STAGES}
        )
        if not set(completed_stages).issubset(accepted_stages):
            raise StatusStoreError("invalid_existing_status_file")
        skipped_stages = value.get("skipped_stages", [])
        if not isinstance(skipped_stages, list) or not all(
            isinstance(item, str) for item in skipped_stages
        ):
            raise StatusStoreError("invalid_existing_status_file")
        if schema_version == _SCHEMA_VERSION and not set(skipped_stages).issubset(
            {item[0] for item in STAGES}
        ):
            raise StatusStoreError("invalid_existing_status_file")
        if not isinstance(value.get("mutation_performed"), bool):
            raise StatusStoreError("invalid_existing_status_file")
        if value.get("route") not in {"undetermined", "public-dev", "private-runner"}:
            raise StatusStoreError("invalid_existing_status_file")
        _prior_report(value, "provider_report")
        _prior_report(value, "policy_report")
        _prior_report(value, "foundation_report")
        expected = (self.source_commit, self.target_binding, self.mode)
        actual = (value.get("source_commit"), value.get("target_binding"), value.get("mode"))
        if actual != expected:
            raise StatusStoreError("status_context_mismatch")
        if schema_version == _LEGACY_SCHEMA_VERSION:
            value = dict(value)
            value["schema_version"] = _SCHEMA_VERSION
            value["completed_stages"] = [
                stage for stage in completed_stages if stage in {item[0] for item in STAGES}
            ]
            value["skipped_stages"] = []
        return value

    def _write(self) -> None:
        temporary = self.path.parent / f".{self.path.name}.tmp-{os.getpid()}"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(self.payload, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _ensure_private_directory(path: Path) -> None:
        try:
            details = path.lstat()
        except FileNotFoundError:
            path.mkdir(parents=True, mode=0o700)
            details = path.lstat()
        if (
            not stat.S_ISDIR(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o700
            or details.st_uid != os.geteuid()
        ):
            raise StatusStoreError("unsafe_orchestration_work_dir")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise StatusStoreError("unsafe_orchestration_work_dir") from exc
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o700
                or opened.st_uid != os.geteuid()
            ):
                raise StatusStoreError("unsafe_orchestration_work_dir")
        finally:
            os.close(descriptor)


def render_progress(payload: dict[str, object]) -> None:
    """Render an ASCII progress bar with exact completed and remaining counts."""

    total = int(payload["stages_total"])
    completed = int(payload["stages_completed"])
    skipped = int(payload["stages_skipped"])
    percent = int(payload["progress_percent"])
    width = 24
    filled = width * completed // total
    bar = "#" * filled + "." * (width - filled)
    current = str(payload["current_stage"])
    label = dict(STAGES)[current]
    stage_number = [item[0] for item in STAGES].index(current) + 1
    state = str(payload["state"]).upper()
    remaining = total - completed
    print(
        f"[{bar}] {percent:3d}%  done {completed}/{total} | stage {stage_number}/{total} "
        f"{label} - {state} | skipped {skipped} | remaining {remaining}",
        file=sys.stderr,
    )


def render_plan(mode: str) -> None:
    """Render the fixed procedure and fail-closed route outcomes before execution."""

    display_mode = "mutation-enabled preflight" if mode == "apply" else "read-only inspection"
    print("FDAI Azure Genesis", file=sys.stderr)
    print(f"Mode: {display_mode}; prompts: none", file=sys.stderr)
    print("Procedure:", file=sys.stderr)
    for number, (_stage, label) in enumerate(STAGES, start=1):
        print(f"  {number}. {label}", file=sys.stderr)
    print(
        "Routes: public-dev -> preview and exact-plan wait; "
        "private-runner -> image, Foundation, enrollment, and state checkpoints",
        file=sys.stderr,
    )
    print("Safety: no route fallback, unsealed apply, or readiness claim", file=sys.stderr)


def _timestamp() -> str:
    current = datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint
    return current.isoformat().replace("+00:00", "Z")


def _run_id(target_binding: str, source_commit: str, mode: str) -> str:
    return hashlib.sha256(f"{target_binding}:{source_commit}:{mode}".encode()).hexdigest()


def _prior_report(payload: dict[str, Any], field: str) -> dict[str, object] | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise StatusStoreError("invalid_existing_status_file")
    return value


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StatusStoreError("invalid_existing_status_file") from exc
    if parsed.tzinfo is None:
        raise StatusStoreError("invalid_existing_status_file")
    return parsed


def _timestamp_is_future(value: str) -> bool:
    current = datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint
    return _parse_timestamp(value) > current
