#!/usr/bin/env python3
"""Capture local FDAI profiles and bind GitHub Copilot development reviews."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai_runtime_diagnostics import DevelopmentProfilePacket, request_profile

SCHEMA = "1.0.0"
SERVICES = ("core-control-plane", "operator-service")
SEVERITIES = ("low", "medium", "high", "critical")
MAX_PACKETS = 20
MAX_FILE_BYTES = 1024 * 1024
MAX_LEDGER_BYTES = 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9_./-]{1,512}(?::[1-9][0-9]{0,6})?$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    capture = commands.add_parser("capture")
    _capture_arguments(capture)
    export = commands.add_parser("copilot-export")
    _capture_arguments(export)
    export.add_argument("--question", required=True)
    imported = commands.add_parser("copilot-import")
    imported.add_argument("--packet", required=True, type=Path)
    imported.add_argument("--result", required=True, type=Path)
    report = commands.add_parser("report")
    report.add_argument("--top", type=int, default=20)
    return parser


def _capture_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--service", choices=SERVICES, required=True)
    parser.add_argument("--duration-ms", type=int, default=0)
    parser.add_argument("--cpu", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--heap", action=argparse.BooleanOptionalAction, default=True)


def _root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return Path(result.stdout.strip()).resolve()


def _git_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    revision = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("workspace revision is invalid")
    return revision


def _worktree_digest(root: Path) -> str:
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "automation" / "local-service-input-digest.py"),
            "--paths-only",
            ".",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    value = result.stdout.strip()
    if _HEX64.fullmatch(value) is None:
        raise ValueError("workspace digest is invalid")
    return value


def _state(root: Path) -> Path:
    local_state = root / ".fdai"
    if local_state.is_symlink():
        raise ValueError("development diagnostic state cannot use a symlink")
    path = local_state / "dev-discuss"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


async def _capture(
    root: Path,
    *,
    service: str,
    duration_ms: int,
    cpu: bool,
    heap: bool,
) -> DevelopmentProfilePacket:
    if not 0 <= duration_ms <= 30_000:
        raise ValueError("duration MUST be between 0 and 30000 ms")
    socket_path = root / ".fdai" / "runtime-diagnostics" / f"{service}.sock"
    packet = await request_profile(
        socket_path,
        duration_ms=duration_ms,
        cpu=cpu,
        heap=heap,
        timeout_seconds=max(5.0, duration_ms / 1000 + 5.0),
    )
    if packet.source_revision != _git_revision(root):
        raise ValueError("running service revision does not match the workspace")
    if packet.worktree_digest != _worktree_digest(root):
        raise ValueError("running service worktree digest does not match the workspace")
    return packet


def _write_private_json(path: Path, value: object) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("development diagnostic output cannot use a symlink")
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("development diagnostic output exceeds the file limit")
    pending = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        output = os.fdopen(descriptor, "wb")
        descriptor = -1
        with output:
            output.write(encoded)
        pending.replace(path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        pending.unlink(missing_ok=True)


def _read_private_json(path: Path) -> dict[str, Any]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FILE_BYTES:
            raise ValueError("development diagnostic input is unavailable")
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise ValueError("development diagnostic input MUST be owner-only")
        with os.fdopen(descriptor, "rb") as input_file:
            descriptor = -1
            encoded = input_file.read(MAX_FILE_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("development diagnostic input exceeds the file limit")
    value = json.loads(encoded.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("development diagnostic input MUST be one object")
    return value


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _write_packet(root: Path, packet: DevelopmentProfilePacket) -> Path:
    directory = _state(root) / "profiles"
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / f"profile-{packet.profile_id}.json"
    _write_private_json(path, packet.model_dump(mode="json"))
    _prune(directory, "profile-*.json")
    return path


def _review_packet(root: Path, packet: DevelopmentProfilePacket, question: str) -> dict[str, Any]:
    normalized = question.strip()
    if not 1 <= len(normalized) <= 400:
        raise ValueError("Copilot review question MUST contain 1-400 characters")
    body = {
        "schema_version": SCHEMA,
        "review_id": str(uuid.uuid4()),
        "question": normalized,
        "profile_packet": packet.model_dump(mode="json"),
        "workspace_revision": _git_revision(root),
        "workspace_digest": _worktree_digest(root),
        "created_at": datetime.now(UTC).isoformat(),
        "reviewer_kind": "github_copilot_session",
        "qualification_authority": False,
        "execution_authority": False,
    }
    return {**body, "review_digest": _digest(body)}


def _import_review(root: Path, packet_path: Path, result_path: Path) -> dict[str, Any]:
    packet = _read_private_json(packet_path)
    result = _read_private_json(result_path)
    expected = packet.get("review_digest")
    if not isinstance(expected, str) or _SHA256.fullmatch(expected) is None:
        raise ValueError("Copilot review packet digest is invalid")
    if _digest({key: value for key, value in packet.items() if key != "review_digest"}) != expected:
        raise ValueError("Copilot review packet digest does not match content")
    profile_value = packet.get("profile_packet")
    if not isinstance(profile_value, dict):
        raise ValueError("Copilot review profile packet is missing")
    profile = DevelopmentProfilePacket.model_validate(profile_value)
    if not isinstance(packet.get("workspace_revision"), str) or not isinstance(
        packet.get("workspace_digest"), str
    ):
        raise ValueError("Copilot review workspace identity is missing")
    if packet.get("workspace_revision") != _git_revision(root):
        raise ValueError("Copilot review workspace revision changed")
    if packet.get("workspace_digest") != _worktree_digest(root):
        raise ValueError("Copilot review workspace digest changed")
    if result.get("schema_version") != SCHEMA or result.get("review_id") != packet.get("review_id"):
        raise ValueError("Copilot review identity does not match")
    if (
        result.get("review_digest") != expected
        or result.get("packet_digest") != profile.packet_digest
    ):
        raise ValueError("Copilot review result is not bound to the packet")
    severity = result.get("severity")
    diagnosis = result.get("diagnosis")
    refs = result.get("code_refs")
    if severity not in SEVERITIES:
        raise ValueError("Copilot review severity is invalid")
    if not isinstance(diagnosis, str) or not 1 <= len(diagnosis.strip()) <= 4000:
        raise ValueError("Copilot review diagnosis is invalid")
    if (
        not isinstance(refs, list)
        or len(refs) > 20
        or any(not isinstance(ref, str) or _SAFE_REF.fullmatch(ref) is None for ref in refs)
    ):
        raise ValueError("Copilot review code references are invalid")
    record = {
        "schema_version": SCHEMA,
        "review_id": packet["review_id"],
        "review_digest": expected,
        "packet_digest": profile.packet_digest,
        "service_id": profile.service_id,
        "severity": severity,
        "diagnosis": diagnosis.strip(),
        "code_refs": refs,
        "recorded_at": datetime.now(UTC).isoformat(),
        "merge_authority": False,
        "execution_authority": False,
    }
    _append_private_jsonl(_state(root) / "reviews.jsonl", record)
    return record


def _append_private_jsonl(path: Path, value: object) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("development diagnostic ledger cannot use a symlink")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    encoded_bytes = encoded.encode()
    if len(encoded_bytes) > MAX_FILE_BYTES:
        raise ValueError("development diagnostic ledger record exceeds the file limit")
    lock_path = path.with_suffix(f"{path.suffix}.lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError("development diagnostic ledger lock is invalid")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _append_locked(path, encoded, encoded_bytes)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _append_locked(path: Path, encoded: str, encoded_bytes: bytes) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        current_size = 0
    else:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError("development diagnostic ledger is invalid")
        current_size = metadata.st_size
    if current_size + len(encoded_bytes) > MAX_LEDGER_BYTES:
        rotated = path.with_suffix(f"{path.suffix}.1")
        if rotated.is_symlink():
            raise ValueError("development diagnostic ledger rotation cannot use a symlink")
        rotated.unlink(missing_ok=True)
        path.replace(rotated)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError("development diagnostic ledger is invalid")
        output = os.fdopen(descriptor, "a", encoding="utf-8")
        descriptor = -1
        with output:
            output.write(encoded)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _prune(directory: Path, pattern: str) -> None:
    entries = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in entries[MAX_PACKETS:]:
        path.unlink()


async def _socket_available(socket_path: Path) -> bool:
    if not socket_path.is_socket():
        return False
    try:
        await request_profile(
            socket_path,
            duration_ms=0,
            cpu=False,
            heap=False,
            timeout_seconds=2,
        )
    except (OSError, TimeoutError, RuntimeError, ValueError):
        return False
    return True


async def _status(root: Path) -> int:
    sockets = root / ".fdai" / "runtime-diagnostics"
    availability = await asyncio.gather(
        *(_socket_available(sockets / f"{service}.sock") for service in SERVICES)
    )
    value = dict(zip(SERVICES, availability, strict=True))
    print(json.dumps(value, sort_keys=True))
    return 0 if any(value.values()) else 1


def _report(root: Path, top: int) -> int:
    path = _state(root) / "reviews.jsonl"
    rows: list[dict[str, Any]] = []
    if path.is_file() and not path.is_symlink():
        for raw in path.read_text(encoding="utf-8").splitlines()[-max(1, min(top, 100)) :]:
            value = json.loads(raw)
            if isinstance(value, dict):
                rows.append(value)
    print(json.dumps({"count": len(rows), "reviews": rows}, ensure_ascii=False, indent=2))
    return 0


async def _main_async(options: argparse.Namespace) -> int:
    root = _root()
    if options.command == "status":
        return await _status(root)
    if options.command == "report":
        return _report(root, options.top)
    if options.command == "copilot-import":
        record = _import_review(root, options.packet.resolve(), options.result.resolve())
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    packet = await _capture(
        root,
        service=options.service,
        duration_ms=options.duration_ms,
        cpu=options.cpu,
        heap=options.heap,
    )
    profile_path = _write_packet(root, packet)
    if options.command == "capture":
        print(profile_path)
        return 0
    review = _review_packet(root, packet, options.question)
    review_directory = _state(root) / "copilot-packets"
    review_directory.mkdir(mode=0o700, exist_ok=True)
    review_path = review_directory / f"review-{review['review_id']}.json"
    _write_private_json(review_path, review)
    _prune(review_directory, "review-*.json")
    print(review_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(_main_async(_parser().parse_args(argv)))
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        print(f"dev-discuss: ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
