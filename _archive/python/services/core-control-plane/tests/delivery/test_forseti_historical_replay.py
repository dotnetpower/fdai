from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fdai.runtime.bootstrap_forseti_replay import build_forseti_historical_replay_source


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "source_revision": "a" * 40,
        "archive_ref": "forseti-history:reviewed:1",
        "review_ref": "review:forseti-history:1",
        "history_complete": True,
        "window_started_at": "2026-10-01T00:00:00+00:00",
        "window_ended_at": "2026-10-02T00:00:00+00:00",
        "evidence_refs": ["audit:historical-1"],
        "records": [
            {
                "key": "historical-1",
                "event_type": "unknown_signal",
                "action_type": "",
                "risk_verdict": "hil",
                "judgment_table_digest": "sha256:" + "b" * 64,
                "tier": "T0",
                "observed_at": "2026-10-01T01:00:00+00:00",
                "evidence_refs": ["audit:historical-1"],
            }
        ],
    }


def _write(path: Path, payload: dict[str, object]) -> str:
    content = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


async def test_reviewed_archive_supplies_exact_historical_replay(tmp_path: Path) -> None:
    path = tmp_path / "forseti-history.json"
    digest = _write(path, _manifest())
    source = build_forseti_historical_replay_source(
        {
            "FDAI_FORSETI_REPLAY_EVIDENCE_PATH": str(path),
            "FDAI_FORSETI_REPLAY_EVIDENCE_SHA256": digest,
            "FDAI_SOURCE_REVISION": "a" * 40,
        }
    )

    assert source is not None
    assert await source.read_replay("other") is None
    replay = await source.read_replay("forseti-history:reviewed:1")
    assert replay is not None
    assert replay.content_digest == digest
    assert replay.samples[0].evidence_refs == ("audit:historical-1",)


@pytest.mark.parametrize("mutation", ["digest", "revision", "complete", "unknown_field"])
def test_reviewed_archive_rejects_unbound_or_changed_evidence(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = _manifest()
    if mutation == "complete":
        payload["history_complete"] = False
    elif mutation == "unknown_field":
        payload["execution_authority"] = True
    path = tmp_path / "forseti-history.json"
    digest = _write(path, payload)
    environment = {
        "FDAI_FORSETI_REPLAY_EVIDENCE_PATH": str(path),
        "FDAI_FORSETI_REPLAY_EVIDENCE_SHA256": "f" * 64 if mutation == "digest" else digest,
        "FDAI_SOURCE_REVISION": "c" * 40 if mutation == "revision" else "a" * 40,
    }
    with pytest.raises(RuntimeError, match="invalid"):
        build_forseti_historical_replay_source(environment)


@pytest.mark.parametrize("missing", ["path", "digest"])
def test_partial_replay_configuration_fails_closed(tmp_path: Path, missing: str) -> None:
    environment = {
        "FDAI_FORSETI_REPLAY_EVIDENCE_PATH": str(tmp_path / "forseti-history.json"),
        "FDAI_FORSETI_REPLAY_EVIDENCE_SHA256": "a" * 64,
    }
    environment.pop(
        "FDAI_FORSETI_REPLAY_EVIDENCE_PATH"
        if missing == "path"
        else "FDAI_FORSETI_REPLAY_EVIDENCE_SHA256"
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        build_forseti_historical_replay_source(environment)
