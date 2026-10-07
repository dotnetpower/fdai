"""File-backed remediation-pack registry for the operator CLI and single-host installations.

Each exported pack is one JSON record named by its pack id inside an owner-only directory.
Writes are atomic (temporary file plus rename), so a crash never leaves a partial record. The
registry, not the pack, is the authority for pack id, manifest digest, issue membership,
expiry, and revocation when a result is imported.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai.core.security.code_findings.result_import import PackRecord
from fdai.shared.providers.remediation_pack import PackRegistryError

_PACK_ID = re.compile(r"^[0-9a-f]{12}$")


class FileRemediationPackRegistry:
    """Store :class:`PackRecord` values as JSON files under ``root``."""

    def __init__(self, root: Path, clock: Callable[[], datetime] | None = None) -> None:
        self._root = root
        self._clock = clock or (lambda: datetime.now(UTC))

    def _path(self, pack_id: str) -> Path:
        if _PACK_ID.fullmatch(pack_id) is None:
            raise PackRegistryError("pack id must be 12 lowercase hex characters")
        return self._root / f"{pack_id}.json"

    def _write(self, path: Path, document: dict[str, Any]) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_suffix(".tmp")
        descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)

    def _read(self, path: Path) -> dict[str, Any] | None:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise PackRegistryError(f"pack record {path.name} is unreadable") from exc
        if not isinstance(document, dict):
            raise PackRegistryError(f"pack record {path.name} is malformed")
        return document

    @staticmethod
    def _record(document: dict[str, Any]) -> PackRecord:
        try:
            return PackRecord(
                pack_id=str(document["pack_id"]),
                manifest_sha256=str(document["manifest_sha256"]),
                base_commit=str(document["base_commit"]),
                issue_ids=frozenset(str(i) for i in document["issue_ids"]),
                expires_at=datetime.fromisoformat(str(document["expires_at"])),
                revoked=bool(document.get("revoked", False)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PackRegistryError("pack record is missing required fields") from exc

    async def record(self, pack: PackRecord) -> None:
        path = self._path(pack.pack_id)
        if path.exists():
            raise PackRegistryError(f"pack {pack.pack_id} is already recorded")
        self._write(
            path,
            {
                "pack_id": pack.pack_id,
                "manifest_sha256": pack.manifest_sha256,
                "base_commit": pack.base_commit,
                "issue_ids": sorted(pack.issue_ids),
                "expires_at": pack.expires_at.isoformat(),
                "revoked": pack.revoked,
                "recorded_at": self._clock().isoformat(),
            },
        )

    async def get(self, pack_id: str) -> PackRecord | None:
        document = self._read(self._path(pack_id))
        return None if document is None else self._record(document)

    async def revoke(self, pack_id: str, reason: str) -> PackRecord:
        path = self._path(pack_id)
        document = self._read(path)
        if document is None:
            raise PackRegistryError(f"pack {pack_id} is not recorded")
        document.update(
            revoked=True,
            revoked_at=self._clock().isoformat(),
            revocation_reason=reason[:500],
        )
        self._write(path, document)
        return self._record(document)

    async def list_active(self) -> Sequence[PackRecord]:
        now = self._clock()
        records = []
        paths = sorted(self._root.glob("*.json")) if self._root.exists() else []
        for path in (p for p in paths if p.name.count(".") == 1):
            document = self._read(path)
            if document is None:
                continue
            record = self._record(document)
            if not record.revoked and now <= record.expires_at:
                records.append(record)
        return records

    async def record_baseline(self, pack_id: str, document: Mapping[str, Any]) -> None:
        path = self._path(pack_id).with_suffix(".baseline.json")
        if path.exists():
            raise PackRegistryError(f"pack {pack_id} already has a baseline")
        self._write(path, dict(document))

    async def get_baseline(self, pack_id: str) -> Mapping[str, Any] | None:
        return self._read(self._path(pack_id).with_suffix(".baseline.json"))

    async def append_review(self, pack_id: str, document: Mapping[str, Any]) -> None:
        if await self.get(pack_id) is None:
            raise PackRegistryError(f"pack {pack_id} is not recorded")
        path = self._path(pack_id).with_suffix(".reviews.jsonl")
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        line = json.dumps({**document, "recorded_at": self._clock().isoformat()}, sort_keys=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    async def list_reviews(self, pack_id: str) -> Sequence[Mapping[str, Any]]:
        path = self._path(pack_id).with_suffix(".reviews.jsonl")
        if not path.exists():
            return []
        try:
            return [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
            ]
        except (OSError, json.JSONDecodeError) as exc:
            raise PackRegistryError(f"review log for {pack_id} is unreadable") from exc


__all__ = ["FileRemediationPackRegistry"]
