from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fdai.delivery.persistence.postgres_browser_evidence import (
    PostgresBrowserEvidenceArtifactStore,
    PostgresBrowserEvidenceArtifactStoreConfig,
    _row_to_stored,
    _values,
)
from fdai.shared.providers.browser_evidence import (
    BrowserEvidenceArtifact,
    BrowserEvidencePayload,
    BrowserRedactionEntry,
    BrowserRuntimeIsolation,
    StoredBrowserEvidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_NOW = datetime(2026, 8, 14, 7, 0, tzinfo=UTC)
_ISOLATION = BrowserRuntimeIsolation(
    executor_identity_present=False,
    host_filesystem_mounted=False,
    environment_scrubbed=True,
    restricted_egress=True,
    ephemeral_profile=True,
)


def _dsn() -> str:
    value = os.environ.get("FDAI_DATABASE_URL")
    if not value:
        pytest.skip("FDAI_DATABASE_URL is unset")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def _upgrade() -> None:
    result = subprocess.run(  # noqa: S603 - controlled module invocation
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _stored(*, suffix: str = "", expires_at: datetime | None = None) -> StoredBrowserEvidence:
    visible_text = f"bounded browser evidence {suffix or 'one'}"
    text_hash = hashlib.sha256(visible_text.encode()).hexdigest()
    digest = hashlib.sha256(f"artifact:{suffix or 'one'}".encode()).hexdigest()
    resolved_expiry = expires_at or (_NOW + timedelta(days=7))
    captured_at = min(_NOW, resolved_expiry - timedelta(days=1))
    return StoredBrowserEvidence(
        artifact=BrowserEvidenceArtifact(
            artifact_id=f"sha256:{digest}",
            policy_id="browser-dashboard",
            policy_version=1,
            canonical_source_url="https://dashboard.example/evidence",
            canonical_final_url="https://dashboard.example/evidence",
            captured_at=captured_at,
            selectors=("main",),
            screenshot_hash=None,
            text_hash=text_hash,
            snapshot_hash=None,
            redaction_manifest=(
                BrowserRedactionEntry(
                    surface="visible_text",
                    rule="account-id",
                    replacements=1,
                ),
            ),
            browser_version="chromium-test",
            chain_of_custody_audit_ref=f"browser-custody:{suffix or 'one'}",
            content_digest=digest,
            prompt_injection_findings=("instruction_override",),
            isolation=_ISOLATION,
            expires_at=resolved_expiry,
        ),
        payload=BrowserEvidencePayload(
            screenshot=None,
            visible_text=visible_text,
            aria_snapshot=None,
        ),
    )


def test_browser_evidence_row_codec_round_trips_and_revalidates_hashes() -> None:
    stored = _stored()
    columns = (
        "artifact_id content_digest policy_id policy_version canonical_source_url "
        "canonical_final_url captured_at expires_at selectors screenshot visible_text "
        "aria_snapshot screenshot_hash text_hash snapshot_hash redaction_manifest "
        "browser_version chain_of_custody_audit_ref prompt_injection_findings isolation "
        "untrusted"
    ).split()
    values = tuple(value.obj if hasattr(value, "obj") else value for value in _values(stored))
    row = dict(zip(columns, values, strict=True))

    assert _row_to_stored(row) == stored
    row["visible_text"] = "tampered"
    with pytest.raises(ValueError, match="visible text hash"):
        _row_to_stored(row)


@pytest.mark.integration
async def test_postgres_browser_evidence_replay_hold_and_concurrent_cleanup() -> None:
    dsn = _dsn()
    _upgrade()
    store = PostgresBrowserEvidenceArtifactStore(
        config=PostgresBrowserEvidenceArtifactStoreConfig(dsn=dsn)
    )
    suffix = uuid4().hex
    current = _stored(suffix=f"current-{suffix}")
    held = _stored(suffix=f"held-{suffix}", expires_at=_NOW - timedelta(days=1))
    expired = tuple(
        _stored(suffix=f"expired-{index}-{suffix}", expires_at=_NOW - timedelta(days=1))
        for index in range(6)
    )

    assert await store.put(current) is True
    assert await store.put(current) is False
    assert await store.get(current.artifact.artifact_id) == current
    restarted = PostgresBrowserEvidenceArtifactStore(
        config=PostgresBrowserEvidenceArtifactStoreConfig(dsn=dsn)
    )
    assert await restarted.get(current.artifact.artifact_id) == current
    assert current.artifact in await restarted.list_artifacts(limit=500)

    conflicting_artifact = replace(
        current.artifact,
        text_hash=hashlib.sha256(b"different").hexdigest(),
    )
    with pytest.raises(ValueError, match="artifact id collision"):
        await store.put(
            StoredBrowserEvidence(
                artifact=conflicting_artifact,
                payload=replace(current.payload, visible_text="different"),
            )
        )

    assert await store.put(held) is True
    assert (
        await store.place_legal_hold(
            artifact_id=held.artifact.artifact_id,
            hold_ref="legal-case:example",
            held_at=_NOW,
        )
        is True
    )
    assert (
        await store.place_legal_hold(
            artifact_id=held.artifact.artifact_id,
            hold_ref="legal-case:example",
            held_at=_NOW,
        )
        is False
    )
    with pytest.raises(ValueError, match="different legal hold"):
        await store.place_legal_hold(
            artifact_id=held.artifact.artifact_id,
            hold_ref="legal-case:conflict",
            held_at=_NOW,
        )

    for record in expired:
        assert await store.put(record) is True
    first, second = await asyncio.gather(
        store.purge_expired(now=_NOW, limit=10),
        restarted.purge_expired(now=_NOW, limit=10),
    )
    assert set(first).isdisjoint(second)
    assert set((*first, *second)) == {record.artifact.artifact_id for record in expired}
    assert await store.get(held.artifact.artifact_id) == held
    assert await store.get(current.artifact.artifact_id) == current
