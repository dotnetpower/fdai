#!/usr/bin/env python3
"""Manage the durable roadmap implementation-verification queue."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO

import roadmap_verification_inventory as inventory

SCHEMA_VERSION = 1
UTC = timezone.utc  # noqa: UP017 - repository automation supports system Python 3.10.
TERMINAL_STATUSES = frozenset(
    {"verified", "reviewed", "gap_found", "designed", "not_applicable", "blocked"}
)


@dataclass(frozen=True, slots=True)
class QueuePaths:
    repo_root: Path
    state_root: Path
    jobs: Path
    receipts: Path
    ledger: Path
    lock: Path


def _git(*arguments: str, cwd: Path) -> str:
    return subprocess.check_output(["git", *arguments], cwd=cwd, text=True).strip()


def queue_paths(cwd: Path | None = None) -> QueuePaths:
    start = (cwd or Path.cwd()).resolve()
    repo_root = Path(_git("rev-parse", "--show-toplevel", cwd=start))
    raw_common = Path(_git("rev-parse", "--git-common-dir", cwd=repo_root))
    common = raw_common if raw_common.is_absolute() else repo_root / raw_common
    configured_state = os.environ.get("FDAI_ROADMAP_STATE_ROOT", "").strip()
    state_root = (
        Path(configured_state).expanduser().resolve()
        if configured_state
        else common.resolve() / "fdai-roadmap-verification"
    )
    return QueuePaths(
        repo_root=repo_root,
        state_root=state_root,
        jobs=state_root / "jobs",
        receipts=state_root / "receipts",
        ledger=state_root / "ledger.jsonl",
        lock=state_root / "run.lock",
    )


def _initialize(paths: QueuePaths) -> None:
    paths.jobs.mkdir(parents=True, exist_ok=True)
    paths.receipts.mkdir(parents=True, exist_ok=True)


@contextmanager
def _locked(paths: QueuePaths) -> Iterator[TextIO]:
    _initialize(paths)
    with paths.lock.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield handle


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _job_id(document: str) -> str:
    return hashlib.sha256(document.encode("utf-8")).hexdigest()[:20]


def _read_job(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"unsupported roadmap verification job: {path.name}")
    return payload


def _job_path(paths: QueuePaths, job_id: str) -> Path:
    if len(job_id) != 20 or any(character not in "0123456789abcdef" for character in job_id):
        raise ValueError("job id must be a 20-character lowercase hexadecimal value")
    return paths.jobs / f"{job_id}.json"


def sync(paths: QueuePaths, *, now: datetime | None = None) -> int:
    created = 0
    instant = now or _now()
    with _locked(paths):
        for document in inventory.canonical_documents(paths.repo_root):
            job_id = _job_id(document)
            destination = _job_path(paths, job_id)
            route_ids, commands = inventory.route_evidence(paths.repo_root, document)
            document_blob = inventory.file_blob(paths.repo_root, document)
            route_digest = inventory.route_digest(route_ids, commands)
            if destination.is_file():
                current = _read_job(destination)
                stale_reasons: list[str] = []
                if current["status"] in TERMINAL_STATUSES:
                    if current.get("document_blob") not in {None, document_blob}:
                        stale_reasons.append("document_changed")
                    if current.get("route_digest") not in {None, route_digest}:
                        stale_reasons.append("route_mapping_changed")
                    result = current.get("result")
                    if isinstance(result, dict) and isinstance(result.get("evidence_digest"), str):
                        evidence_paths = result.get("evidence_paths", [])
                        if isinstance(evidence_paths, list) and all(
                            isinstance(path, str) for path in evidence_paths
                        ):
                            observed = inventory.evidence_digest(paths.repo_root, evidence_paths)
                            if observed != result["evidence_digest"]:
                                stale_reasons.append("evidence_changed")
                if stale_reasons:
                    current["status"] = "queued"
                    current["checkpoint"] = "freshness_changed"
                    current["stale_reasons"] = stale_reasons
                    current.pop("result", None)
                    (paths.receipts / f"{job_id}.json").unlink(missing_ok=True)
                    _append_ledger(
                        paths,
                        {
                            "action": "freshness_requeued",
                            "job_id": job_id,
                            "reasons": stale_reasons,
                            "ts": _timestamp(instant),
                        },
                    )
                current["route_ids"] = route_ids
                current["validation_commands"] = commands
                current["document_blob"] = document_blob
                current["route_digest"] = route_digest
                current["updated_at"] = _timestamp(instant)
                _atomic_json(destination, current)
                continue
            created += 1
            _atomic_json(
                destination,
                {
                    "schema_version": SCHEMA_VERSION,
                    "job_id": job_id,
                    "document": document,
                    "translation": document.removesuffix(".md") + "-ko.md",
                    "status": "queued",
                    "attempts": 0,
                    "route_ids": route_ids,
                    "validation_commands": commands,
                    "document_blob": document_blob,
                    "route_digest": route_digest,
                    "created_at": _timestamp(instant),
                    "updated_at": _timestamp(instant),
                },
            )
    return created


def _append_ledger(paths: QueuePaths, record: dict[str, Any]) -> None:
    with paths.ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")


def _recover_stale(paths: QueuePaths, *, now: datetime) -> int:
    recovered = 0
    for path in sorted(paths.jobs.glob("*.json")):
        job = _read_job(path)
        if job["status"] != "running":
            continue
        expires_at = datetime.fromisoformat(str(job["lease_expires_at"]))
        if expires_at > now:
            continue
        previous_owner = str(job.pop("owner", "unknown"))
        job.pop("lease_expires_at", None)
        job["status"] = "queued"
        job["checkpoint"] = "recovered_stale_claim"
        job["updated_at"] = _timestamp(now)
        _atomic_json(path, job)
        _append_ledger(
            paths,
            {
                "action": "stale_claim_recovered",
                "job_id": job["job_id"],
                "owner": previous_owner,
                "ts": _timestamp(now),
            },
        )
        recovered += 1
    return recovered


def claim(
    paths: QueuePaths,
    *,
    owner: str,
    lease_seconds: int = 1800,
    eligible_statuses: frozenset[str] = frozenset({"queued", "failed"}),
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if not owner.strip():
        raise ValueError("owner must not be empty")
    if lease_seconds < 60:
        raise ValueError("lease_seconds must be at least 60")
    instant = now or _now()
    with _locked(paths):
        _recover_stale(paths, now=instant)
        candidates: list[dict[str, Any]] = []
        for path in sorted(paths.jobs.glob("*.json")):
            candidate = _read_job(path)
            if candidate["status"] in eligible_statuses:
                candidates.append(candidate)
        if not candidates:
            return None
        job = min(
            candidates,
            key=lambda value: (
                value.get("checkpoint") != "recovered_stale_claim",
                int(value["attempts"]),
                value["document"],
            ),
        )
        job["status"] = "running"
        job["owner"] = owner
        job["attempts"] = int(job["attempts"]) + 1
        job["checkpoint"] = "claimed"
        job["lease_expires_at"] = _timestamp(instant + timedelta(seconds=lease_seconds))
        job["updated_at"] = _timestamp(instant)
        _atomic_json(_job_path(paths, str(job["job_id"])), job)
        _append_ledger(
            paths,
            {
                "action": "claimed",
                "attempt": job["attempts"],
                "job_id": job["job_id"],
                "owner": owner,
                "ts": _timestamp(instant),
            },
        )
        return job


def heartbeat(
    paths: QueuePaths,
    *,
    job_id: str,
    owner: str,
    checkpoint: str,
    lease_seconds: int = 1800,
    details: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not checkpoint.strip():
        raise ValueError("checkpoint must not be empty")
    if lease_seconds < 60:
        raise ValueError("lease_seconds must be at least 60")
    instant = now or _now()
    with _locked(paths):
        path = _job_path(paths, job_id)
        job = _read_job(path)
        if job["status"] != "running" or job.get("owner") != owner:
            raise RuntimeError("roadmap verification job is not owned by this worker")
        job["checkpoint"] = checkpoint
        job["lease_expires_at"] = _timestamp(instant + timedelta(seconds=lease_seconds))
        job["updated_at"] = _timestamp(instant)
        if details:
            job["checkpoint_details"] = details
        _atomic_json(path, job)
        return job


def finish(
    paths: QueuePaths,
    *,
    job_id: str,
    owner: str,
    outcome: str,
    result: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    if outcome not in TERMINAL_STATUSES:
        raise ValueError(f"unsupported roadmap verification outcome: {outcome}")
    instant = now or _now()
    with _locked(paths):
        path = _job_path(paths, job_id)
        job = _read_job(path)
        if job["status"] != "running" or job.get("owner") != owner:
            raise RuntimeError("roadmap verification job is not owned by this worker")
        job.pop("owner", None)
        job.pop("lease_expires_at", None)
        job["status"] = outcome
        job["checkpoint"] = "finished"
        job["result"] = result
        if isinstance(result.get("document_blob"), str):
            job["document_blob"] = result["document_blob"]
        job["updated_at"] = _timestamp(instant)
        _atomic_json(path, job)
        if outcome in {"verified", "designed", "not_applicable"}:
            _atomic_json(
                paths.receipts / f"{job_id}.json",
                {
                    "schema_version": SCHEMA_VERSION,
                    "job_id": job_id,
                    "document": job["document"],
                    "verified_at": _timestamp(instant),
                    "result": result,
                },
            )
        _append_ledger(
            paths,
            {
                "action": "finished",
                "job_id": job_id,
                "outcome": outcome,
                "ts": _timestamp(instant),
            },
        )
        return job


def fail(
    paths: QueuePaths,
    *,
    job_id: str,
    owner: str,
    error_type: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    instant = now or _now()
    with _locked(paths):
        path = _job_path(paths, job_id)
        job = _read_job(path)
        if job["status"] != "running" or job.get("owner") != owner:
            raise RuntimeError("roadmap verification job is not owned by this worker")
        job.pop("owner", None)
        job.pop("lease_expires_at", None)
        job["status"] = "failed"
        job["checkpoint"] = "worker_failed"
        job["error_type"] = error_type[:120]
        job["updated_at"] = _timestamp(instant)
        _atomic_json(path, job)
        _append_ledger(
            paths,
            {
                "action": "worker_failed",
                "error_type": error_type[:120],
                "job_id": job_id,
                "ts": _timestamp(instant),
            },
        )
        return job


def status(paths: QueuePaths) -> Counter[str]:
    _initialize(paths)
    counts = Counter(str(_read_job(path)["status"]) for path in sorted(paths.jobs.glob("*.json")))
    return counts
