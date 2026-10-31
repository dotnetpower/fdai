"""Private, bounded, atomic IPC for the customer-side first-install worker."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fdai_deployment_cli.contracts import load_json_object

MAX_BYTES = 65536
STALE_SECONDS = 12
INSTALL_FIELDS = {
    "subscription_id",
    "region",
    "monthly_cost_ceiling",
    "artifact_source",
    "source_root",
    "hub_public_key",
}


def prepare_directory(root: Path) -> None:
    """Create an owner-only IPC root; refuse symlinks and unsafe existing paths."""
    root = root.absolute()
    for path in (*reversed(root.parents), root):
        if path.is_symlink():
            raise ValueError("Bootstrap directory must not contain symlinks")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("Bootstrap directory must be owned by this user with mode 0700")


def _read(root: Path, name: str = "channel.json") -> dict[str, Any]:
    path = root / name
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ValueError("Bootstrap private file is unavailable or unsafe") from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError("Bootstrap private files require mode 0600 and one owner")
        raw = stream.read(MAX_BYTES + 1)
    try:
        value = load_json_object(raw, label="Bootstrap state", max_bytes=MAX_BYTES, strict=True)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Bootstrap state is malformed; preserve the private directory") from exc
    if len(raw) > MAX_BYTES or not isinstance(value, dict):
        raise ValueError("Bootstrap state exceeds its bounded object schema")
    return value


def _write(root: Path, value: dict[str, object], name: str = "channel.json") -> None:
    raw = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("Bootstrap state exceeds its size bound")
    target = root / name
    if target.is_symlink():
        raise ValueError("Bootstrap private files must not be symlinks")
    staging = root / f".write-{uuid4().hex}"
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, target)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        staging.unlink(missing_ok=True)


@contextmanager
def locked(root: Path) -> Iterator[None]:
    prepare_directory(root)
    fd = os.open(root / "channel.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise ValueError("Bootstrap lock is unsafe")
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise ValueError(
                        "Bootstrap state is busy; wait for the current private update."
                    ) from exc
                time.sleep(0.01)
        yield
    finally:
        os.close(fd)


def initial_status() -> dict[str, object]:
    return {
        "phase": "idle",
        "request_id": None,
        "action": None,
        "message": "Sign in to Azure to begin first installation.",
        "error_code": None,
        "accounts": [],
        "review": None,
        "deployment_ready": False,
        "console_url": None,
    }


def _status(record: dict[str, object]) -> dict[str, object]:
    stored = record.get("status")
    result = initial_status()
    if isinstance(stored, dict):
        result.update({key: stored[key] for key in result if key in stored})
    if record.get("active_request_id") is not None and result["phase"] in {
        "idle",
        "ready",
        "blocked",
        "failed",
    }:
        result.update(
            phase="working",
            deployment_ready=False,
            console_url=None,
            message="Finalizing local executor cleanup before accepting another request.",
        )
    heartbeat = record.get("heartbeat")
    if result["phase"] in {"working", "review"} and (
        not isinstance(heartbeat, (int, float)) or time.time() - heartbeat > STALE_SECONDS
    ):
        result.update(
            phase="interrupted",
            review=None,
            deployment_ready=False,
            console_url=None,
            error_code="worker_interrupted",
            message="Worker interrupted. Inspect retained state before explicitly resuming.",
        )
    if result["phase"] == "ready" and result["deployment_ready"] is not True:
        result.update(phase="blocked", message="Independent deployment acceptance is unavailable.")
    return result


def read_status(root: Path) -> dict[str, object]:
    """Read only allowlisted setup metadata, never engine output or Azure credentials."""
    with locked(root):
        return _status(_read(root))


def validate_request(action: str, payload: dict[str, object]) -> dict[str, object]:
    if (
        not isinstance(action, str)
        or action not in {"login", "accounts", "install", "resume", "inspect", "reset"}
        or not isinstance(payload, dict)
    ):
        raise ValueError("Unsupported Bootstrap action or payload")
    try:
        encoded = json.dumps(payload, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Bootstrap payload must be a bounded JSON object") from exc
    if len(encoded) > 16384:
        raise ValueError("Bootstrap payload exceeds its size bound")
    if action == "login":
        if not payload:
            return {}
        if set(payload) - {"tenant_id", "use_device_code"}:
            raise ValueError("Login accepts only optional tenant_id and use_device_code")
        validated: dict[str, object] = {}
        if "tenant_id" in payload:
            tenant = payload.get("tenant_id")
            if (
                not isinstance(tenant, str)
                or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", tenant) is None
                or tenant in {".", ".."}
            ):
                raise ValueError("Choose a valid Azure tenant ID or domain")
            validated["tenant_id"] = tenant
        if "use_device_code" in payload:
            if type(payload.get("use_device_code")) is not bool:
                raise ValueError("use_device_code must be a boolean")
            if payload["use_device_code"]:
                validated["use_device_code"] = True
        return validated
    if action != "install":
        if payload:
            raise ValueError("This action accepts no replacement inputs")
        return {}
    if set(payload) - INSTALL_FIELDS:
        raise ValueError("Unknown installation fields; use only the documented setup inputs")
    subscription = payload.get("subscription_id")
    try:
        if not isinstance(subscription, str) or str(UUID(subscription)) != subscription.lower():
            raise ValueError
    except ValueError as exc:
        raise ValueError("Select one valid Azure subscription UUID") from exc
    region, ceiling = payload.get("region"), payload.get("monthly_cost_ceiling")
    if not isinstance(region, str) or re.fullmatch(r"[a-z][a-z0-9]{1,31}", region) is None:
        raise ValueError("Choose a valid Azure region token")
    if type(ceiling) is not int or ceiling <= 0 or ceiling > 1_000_000_000:
        raise ValueError("Monthly cost ceiling must be a positive bounded integer")
    result = {**payload, "artifact_source": payload.get("artifact_source", "hub")}
    if not isinstance(result["artifact_source"], str) or result["artifact_source"] not in {
        "hub",
        "source",
    }:
        raise ValueError("Artifact source must be hub or source")
    source = payload.get("source_root")
    if source is not None and (
        not isinstance(source, str) or not source or len(source) > 4096 or "\0" in source
    ):
        raise ValueError("Source root must be a local checkout path")
    key = payload.get("hub_public_key")
    if result["artifact_source"] == "source":
        if not source or key is not None:
            raise ValueError("Source mode requires source_root and does not accept a Hub key")
    else:
        if not isinstance(key, str) or len(key) > 4096:
            raise ValueError("Hub mode requires an independently supplied Ed25519 public PEM")
        from fdai_deployment_cli.hub_image_trust import public_key

        try:
            public_key(key.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "Hub trust requires an Ed25519 public PEM, never a private key"
            ) from exc
    return result


def submit_request(root: Path, action: str, payload: dict[str, object]) -> dict[str, object]:
    payload = validate_request(action, payload)
    with locked(root):
        record = _read(root)
        status = _status(record)
        stored_status = record.get("status", {})
        if (
            record.get("pending") is not None
            or record.get("active_request_id") is not None
            or stored_status.get("phase") in {"working", "review"}
        ):
            raise ValueError(
                "A Bootstrap request is already pending or running. "
                "If its worker is interrupted, restart setup before explicit resume."
            )
        if status["phase"] == "interrupted" and action not in {
            "inspect",
            "resume",
            "login",
            "accounts",
            "reset",
        }:
            raise ValueError(
                "Inspect or resume the interrupted installation before starting other work"
            )
        request_id = str(uuid4())
        status.update(
            phase="working",
            request_id=request_id,
            action=action,
            review=None,
            error_code=None,
            message="Request queued for the local customer executor.",
            deployment_ready=False,
            console_url=None,
        )
        record.update(
            status=status,
            heartbeat=time.time(),
            decision=None,
            pending={"id": request_id, "action": action, "payload": payload},
        )
        _write(root, record)
        return dict(status)


def submit_decision(root: Path, payload: dict[str, object]) -> dict[str, object]:
    fields = {"request_id", "review_id", "digest", "approved", "confirmation"}
    if (
        not isinstance(payload, dict)
        or set(payload) != fields
        or type(payload.get("approved")) is not bool
        or any(not isinstance(payload.get(key), str) for key in fields - {"approved"})
    ):
        raise ValueError(
            "Decision requires exact request, review, digest, approval and confirmation"
        )
    with locked(root):
        record = _read(root)
        status = _status(record)
        review = status.get("review")
        if (
            status["phase"] != "review"
            or not isinstance(review, dict)
            or record.get("decision") is not None
            or payload["request_id"] != status["request_id"]
            or payload["review_id"] != review["id"]
            or payload["digest"] != review["digest"]
        ):
            raise ValueError("Decision does not match the current pending review")
        expires = datetime.fromisoformat(str(review["expires_at"]))
        if expires <= datetime.now(UTC):
            raise ValueError("Review expired; explicitly resume to obtain a fresh exact plan")
        if payload["approved"] and payload["confirmation"] != review["confirmation_required"]:
            raise ValueError("Type the exact confirmation shown for this checkpoint")
        record["decision"] = payload
        status.update(
            phase="working", review=None, message="Decision submitted to the exact checkpoint."
        )
        record["status"] = status
        _write(root, record)
        return dict(status)
