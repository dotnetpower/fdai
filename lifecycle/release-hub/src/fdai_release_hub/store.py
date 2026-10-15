"""Transactional, local development publication. Artifacts are never uploaded or built."""

from __future__ import annotations

import hashlib
import sqlite3
from base64 import b64encode
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.runtime_release import is_release_id, parse_runtime_release_manifest
from pydantic import BaseModel, ConfigDict, Field

from fdai_lifecycle_hub.signing import HubSigningKey

CHANNELS = ("DEV", "RELEASE_CANDIDATE", "RELEASE")


class CatalogError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    revision: int = Field(ge=0)
    confirmation: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=3, max_length=500)
    channel: str | None = None
    label: str = Field(default="", max_length=160)
    manifest: str | None = Field(default=None, max_length=1024 * 1024)


class ReleaseStore:
    def __init__(
        self, path: Path, key: HubSigningKey, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.path = path
        self.key = key
        self.clock = clock or (lambda: datetime.now(UTC))
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS releases (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL, manifest TEXT NOT NULL,
                    digest TEXT NOT NULL, signature TEXT, published_at TEXT, recalled_at TEXT
                );
                CREATE TABLE IF NOT EXISTS membership (
                    channel TEXT NOT NULL, release_id TEXT NOT NULL REFERENCES releases(id),
                    PRIMARY KEY(channel, release_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    revision INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,
                    release_id TEXT NOT NULL, channel TEXT, reason TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (created_at TEXT NOT NULL);
            """)
            if db.execute("SELECT COUNT(*) FROM metadata").fetchone()[0] == 0:
                db.execute("INSERT INTO metadata VALUES (?)", (self.clock().isoformat(),))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def change(self, action: str, release_id: str, change: Change) -> dict[str, Any]:
        if not is_release_id(release_id):
            raise CatalogError("Release id must be canonical SemVer.")
        if change.confirmation != release_id:
            raise CatalogError("Type the exact Release id to confirm.")
        if not change.reason.strip():
            raise CatalogError("A non-blank reason is required.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            revision = db.execute("SELECT COALESCE(MAX(revision),0) FROM events").fetchone()[0]
            if change.revision != revision:
                raise CatalogError(
                    "Catalog changed. Refresh and review before confirming again.", 409
                )
            now = self.clock().isoformat()
            row = db.execute("SELECT * FROM releases WHERE id = ?", (release_id,)).fetchone()
            if action == "register":
                if row:
                    raise CatalogError("Release ids are immutable and cannot be reused.", 409)
                if change.manifest is None:
                    raise CatalogError("A runtime Release v3 manifest is required.")
                release = parse_runtime_release_manifest(change.manifest.encode())
                if release.schema_version != "fdai.runtime-release.v3":
                    raise CatalogError("Only fdai.runtime-release.v3 manifests are supported.")
                db.execute(
                    "INSERT INTO releases(id,label,manifest,digest) VALUES (?,?,?,?)",
                    (release_id, change.label.strip(), change.manifest, release.digest),
                )
            else:
                if row is None:
                    raise CatalogError("Release not found.", 404)
                if row["recalled_at"]:
                    raise CatalogError("Recalled Releases cannot be changed or re-promoted.", 409)
                if action == "publish":
                    if row["signature"]:
                        raise CatalogError("Release is already published.", 409)
                    signature = b64encode(self.key.sign(row["manifest"].encode())).decode("ascii")
                    db.execute(
                        "UPDATE releases SET signature=?,published_at=? WHERE id=?",
                        (signature, now, release_id),
                    )
                    db.execute("INSERT INTO membership VALUES ('DEV', ?)", (release_id,))
                elif action == "contribute":
                    if not row["signature"]:
                        raise CatalogError(
                            "Publish the Release before adding it to a channel.", 409
                        )
                    if change.channel not in CHANNELS:
                        raise CatalogError("Choose a supported channel.")
                    exists = db.execute(
                        "SELECT 1 FROM membership WHERE channel=? AND release_id=?",
                        (change.channel, release_id),
                    ).fetchone()
                    if exists:
                        raise CatalogError("Release already belongs to this channel.", 409)
                    db.execute("INSERT INTO membership VALUES (?,?)", (change.channel, release_id))
                elif action == "recall":
                    if not row["signature"]:
                        raise CatalogError("Only published Releases can be recalled.", 409)
                    db.execute("UPDATE releases SET recalled_at=? WHERE id=?", (now, release_id))
                else:
                    raise CatalogError("Unsupported action.")
            db.execute(
                "INSERT INTO events(action,release_id,channel,reason,occurred_at) "
                "VALUES (?,?,?,?,?)",
                (action, release_id, change.channel, change.reason.strip(), now),
            )
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        from base64 import b64decode

        with self.connect() as db:
            db.execute("BEGIN")
            rows = db.execute("SELECT * FROM releases ORDER BY id DESC").fetchall()
            events = [
                dict(row) for row in db.execute("SELECT * FROM events ORDER BY revision DESC")
            ]
            memberships = list(db.execute("SELECT * FROM membership ORDER BY channel,release_id"))
            updated_at = (
                events[0]["occurred_at"]
                if events
                else db.execute("SELECT created_at FROM metadata").fetchone()[0]
            )
        releases = []
        for row in rows:
            record = dict(row)
            record["signed_payload_sha256"] = hashlib.sha256(
                record["manifest"].encode()
            ).hexdigest()
            if record["signature"]:
                try:
                    self.key.public_key.verify(
                        b64decode(record["signature"], validate=True), record["manifest"].encode()
                    )
                except (InvalidSignature, ValueError) as error:
                    raise CatalogError(
                        "Stored Release signature failed verification.", 503
                    ) from error
            record["channels"] = [m["channel"] for m in memberships if m["release_id"] == row["id"]]
            record["state"] = (
                "recalled" if row["recalled_at"] else "published" if row["signature"] else "draft"
            )
            record["signature_status"] = (
                "development-key-verified" if row["signature"] else "unsigned"
            )
            releases.append(record)
        return {
            "revision": events[0]["revision"] if events else 0,
            "updated_at": updated_at,
            "expires_at": (datetime.fromisoformat(updated_at) + timedelta(hours=24)).isoformat(),
            "expired": self.clock() >= datetime.fromisoformat(updated_at) + timedelta(hours=24),
            "mode": "local-development",
            "key_id": self.key.key_id,
            "releases": releases,
            "channels": {
                c: [m["release_id"] for m in memberships if m["channel"] == c] for c in CHANNELS
            },
            "events": events,
        }

    def export(self) -> tuple[bytes, str]:
        return self.export_snapshot(self.snapshot())

    @staticmethod
    def export_snapshot(snapshot: dict[str, Any]) -> tuple[bytes, str]:
        recalls = [
            {
                "scope": "release",
                "target": event["release_id"],
                "sequence": event["revision"],
                "notice_digest": hashlib.sha256(canonical_bytes(event)).hexdigest(),
                "action": "recall",
                "lifting_release_id": None,
            }
            for event in reversed(snapshot["events"])
            if event["action"] == "recall"
        ]
        body = canonical_bytes(
            {
                "revision": snapshot["revision"],
                "expires_at": snapshot["expires_at"],
                "releases": {
                    r["id"]: {"manifest": r["manifest"], "signature": r["signature"]}
                    for r in snapshot["releases"]
                    if r["signature"]
                },
                "channels": snapshot["channels"],
                "recalls": recalls,
            }
        )
        return body, hashlib.sha256(body).hexdigest()
