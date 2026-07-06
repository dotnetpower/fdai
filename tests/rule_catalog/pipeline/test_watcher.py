"""Tests for :mod:`aiopspilot.rule_catalog.pipeline.watcher` +
:mod:`aiopspilot.rule_catalog.pipeline.watcher_cli`.

The truth table covers every :class:`Cadence` value plus the defensive
guard for an unrecognized cadence, and the CLI happy-path exercises the
LocalDirectoryFetcher end-to-end (no external network).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from aiopspilot.rule_catalog.pipeline.watcher import SourceWatcher, WatcherError
from aiopspilot.rule_catalog.pipeline.watcher_cli import main as watcher_main
from aiopspilot.rule_catalog.schema.source_manifest import (
    Cadence,
    SourceManifest,
    load_source_manifest_from_yaml,
)

_NOW = datetime(2026, 7, 6, 3, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_source_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "rule.yaml").write_text("id: sample\nseverity: low\n", encoding="utf-8")


def _write_manifest(
    path: Path,
    source_path: str,
    *,
    source_id: str = "watch-src",
    cadence: str = "daily",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "id": source_id,
                "name": "Watched source",
                "license": "Apache-2.0",
                "redistribution": "embeddable",
                "fetch": {"kind": "local", "path": source_path},
                "parser": "rule-yaml",
                "cadence": cadence,
            }
        ),
        encoding="utf-8",
    )


def _build_manifest(cadence: Cadence, *, source_id: str = "watch-src") -> SourceManifest:
    return SourceManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "id": source_id,
            "name": "Watched source",
            "license": "Apache-2.0",
            "redistribution": "embeddable",
            "fetch": {"kind": "local", "path": "seed"},
            "parser": "rule-yaml",
            "cadence": cadence.value,
        }
    )


def _seed_snapshot(
    snapshot_root: Path, source_id: str, *, revision: str, collected_at: datetime
) -> None:
    """Write a minimal SNAPSHOT.json under ``snapshot_root/<id>/<rev>/``."""
    snap_dir = snapshot_root / source_id / revision
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "SNAPSHOT.json").write_text(
        json.dumps({"collected_at": collected_at.isoformat()}) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# is_due truth table
# ---------------------------------------------------------------------------


def test_on_demand_is_never_due(tmp_path: Path) -> None:
    watcher = SourceWatcher(snapshot_root=tmp_path)
    manifest = _build_manifest(Cadence.ON_DEMAND)
    # Even with no prior snapshot the watcher stays off — on-demand is manual.
    assert watcher.is_due(manifest, now=_NOW) is False
    # And even after seeding an ancient snapshot, still not due.
    _seed_snapshot(
        tmp_path,
        manifest.id,
        revision="abc",
        collected_at=_NOW - timedelta(days=365),
    )
    assert watcher.is_due(manifest, now=_NOW) is False


def test_daily_due_when_no_prior_snapshot(tmp_path: Path) -> None:
    watcher = SourceWatcher(snapshot_root=tmp_path)
    manifest = _build_manifest(Cadence.DAILY)
    assert watcher.is_due(manifest, now=_NOW) is True


@pytest.mark.parametrize(
    ("cadence", "age", "expected"),
    [
        # daily: 24h boundary
        (Cadence.DAILY, timedelta(hours=23, minutes=59), False),
        (Cadence.DAILY, timedelta(hours=24), True),
        (Cadence.DAILY, timedelta(days=2), True),
        # weekly: 7-day boundary
        (Cadence.WEEKLY, timedelta(days=6, hours=23), False),
        (Cadence.WEEKLY, timedelta(days=7), True),
        (Cadence.WEEKLY, timedelta(days=14), True),
        # monthly: 28-day boundary (calendar-agnostic, cron-friendly)
        (Cadence.MONTHLY, timedelta(days=27), False),
        (Cadence.MONTHLY, timedelta(days=28), True),
        (Cadence.MONTHLY, timedelta(days=30), True),
    ],
)
def test_is_due_boundary(tmp_path: Path, cadence: Cadence, age: timedelta, expected: bool) -> None:
    watcher = SourceWatcher(snapshot_root=tmp_path)
    manifest = _build_manifest(cadence)
    _seed_snapshot(
        tmp_path,
        manifest.id,
        revision="rev1",
        collected_at=_NOW - age,
    )
    assert watcher.is_due(manifest, now=_NOW) is expected


def test_is_due_picks_newest_snapshot(tmp_path: Path) -> None:
    """Multiple revision dirs — the watcher compares against the newest."""
    watcher = SourceWatcher(snapshot_root=tmp_path)
    manifest = _build_manifest(Cadence.DAILY)
    _seed_snapshot(
        tmp_path,
        manifest.id,
        revision="old",
        collected_at=_NOW - timedelta(days=30),
    )
    _seed_snapshot(
        tmp_path,
        manifest.id,
        revision="recent",
        collected_at=_NOW - timedelta(hours=2),
    )
    # Newest snapshot is 2h old → not due for daily.
    assert watcher.is_due(manifest, now=_NOW) is False


def test_is_due_ignores_malformed_snapshot(tmp_path: Path) -> None:
    watcher = SourceWatcher(snapshot_root=tmp_path)
    manifest = _build_manifest(Cadence.DAILY)
    bad_dir = tmp_path / manifest.id / "broken"
    bad_dir.mkdir(parents=True)
    (bad_dir / "SNAPSHOT.json").write_text("{not valid json", encoding="utf-8")
    # No good snapshot found → treated as never-collected → due.
    assert watcher.is_due(manifest, now=_NOW) is True


def test_is_due_ignores_missing_or_wrong_type_collected_at(tmp_path: Path) -> None:
    watcher = SourceWatcher(snapshot_root=tmp_path)
    manifest = _build_manifest(Cadence.DAILY)
    src_dir = tmp_path / manifest.id / "rev"
    src_dir.mkdir(parents=True)
    (src_dir / "SNAPSHOT.json").write_text(
        json.dumps({"collected_at": 12345}),  # wrong type — int, not string
        encoding="utf-8",
    )
    assert watcher.is_due(manifest, now=_NOW) is True


def test_is_due_ignores_unparseable_timestamp(tmp_path: Path) -> None:
    watcher = SourceWatcher(snapshot_root=tmp_path)
    manifest = _build_manifest(Cadence.DAILY)
    src_dir = tmp_path / manifest.id / "rev"
    src_dir.mkdir(parents=True)
    (src_dir / "SNAPSHOT.json").write_text(
        json.dumps({"collected_at": "not-a-date"}),
        encoding="utf-8",
    )
    assert watcher.is_due(manifest, now=_NOW) is True


def test_is_due_skips_non_directory_entries(tmp_path: Path) -> None:
    watcher = SourceWatcher(snapshot_root=tmp_path)
    manifest = _build_manifest(Cadence.DAILY)
    src_dir = tmp_path / manifest.id
    src_dir.mkdir(parents=True)
    # A stray file at the revision level must not break iteration.
    (src_dir / "README.md").write_text("not a revision", encoding="utf-8")
    # A revision dir with no SNAPSHOT.json is also skipped.
    (src_dir / "half-written").mkdir()
    assert watcher.is_due(manifest, now=_NOW) is True


def test_is_due_normalizes_naive_collected_at(tmp_path: Path) -> None:
    """Legacy naive timestamps are treated as UTC, not rejected."""
    watcher = SourceWatcher(snapshot_root=tmp_path)
    manifest = _build_manifest(Cadence.DAILY)
    src_dir = tmp_path / manifest.id / "rev"
    src_dir.mkdir(parents=True)
    naive = (_NOW - timedelta(hours=2)).replace(tzinfo=None)
    (src_dir / "SNAPSHOT.json").write_text(
        json.dumps({"collected_at": naive.isoformat()}),
        encoding="utf-8",
    )
    assert watcher.is_due(manifest, now=_NOW) is False


def test_is_due_handles_non_utc_collected_at(tmp_path: Path) -> None:
    watcher = SourceWatcher(snapshot_root=tmp_path)
    manifest = _build_manifest(Cadence.DAILY)
    src_dir = tmp_path / manifest.id / "rev"
    src_dir.mkdir(parents=True)
    kst = timezone(timedelta(hours=9))
    ts = (_NOW - timedelta(hours=2)).astimezone(kst)
    (src_dir / "SNAPSHOT.json").write_text(
        json.dumps({"collected_at": ts.isoformat()}),
        encoding="utf-8",
    )
    # 2h ago regardless of timezone label → not due for daily.
    assert watcher.is_due(manifest, now=_NOW) is False


def test_unknown_cadence_rejected(tmp_path: Path) -> None:
    """A cadence not in the mapping raises :class:`WatcherError`.

    The Cadence enum currently covers every mapped value; this test is
    a defensive guard for future enum additions — the watcher must never
    silently return ``False`` for an unmapped cadence.
    """
    watcher = SourceWatcher(snapshot_root=tmp_path)
    fake_manifest: Any = SimpleNamespace(id="quarterly-src", cadence="quarterly")
    with pytest.raises(WatcherError, match="unknown cadence"):
        watcher.is_due(fake_manifest, now=_NOW)


# ---------------------------------------------------------------------------
# CLI — happy path via LocalDirectoryFetcher
# ---------------------------------------------------------------------------


def _build_repo_layout(
    tmp_path: Path,
    *,
    source_id: str = "watch-src",
    cadence: str = "daily",
) -> tuple[Path, Path, Path]:
    """Lay out a fake repo root with rule-catalog/sources/<id>/manifest.yaml."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "rule-catalog").mkdir()
    sources_root = repo_root / "rule-catalog" / "sources"
    source_dir = sources_root / source_id
    source_dir.mkdir(parents=True)
    payload = repo_root / "payload"
    _write_source_tree(payload)
    manifest_path = source_dir / "manifest.yaml"
    _write_manifest(
        manifest_path,
        str(payload),
        source_id=source_id,
        cadence=cadence,
    )
    return repo_root, sources_root, manifest_path


def test_cli_runs_collect_for_due_daily_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root, sources_root, _ = _build_repo_layout(tmp_path)

    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(sources_root),
            "--now",
            _NOW.isoformat(),
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["now"] == _NOW.isoformat()
    assert len(payload["entries"]) == 1
    entry = payload["entries"][0]
    assert entry["source_id"] == "watch-src"
    assert entry["cadence"] == "daily"
    assert entry["due"] is True
    assert entry["collect_exit_code"] == 0
    assert entry["collect"]["source_id"] == "watch-src"
    # Non-dry-run — snapshot should exist under output_root.
    snap_dir = sources_root / "watch-src"
    revisions = [d for d in snap_dir.iterdir() if d.is_dir()]
    assert revisions, "collector should have written a revision dir"
    assert (revisions[0] / "SNAPSHOT.json").is_file()


def test_cli_skips_on_demand_source(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo_root, sources_root, _ = _build_repo_layout(
        tmp_path, source_id="on-demand-src", cadence="on-demand"
    )
    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(sources_root),
            "--now",
            _NOW.isoformat(),
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    entry = payload["entries"][0]
    assert entry["due"] is False
    assert "collect_exit_code" not in entry


def test_cli_skips_recently_collected_daily_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root, sources_root, _ = _build_repo_layout(tmp_path)
    _seed_snapshot(
        sources_root,
        "watch-src",
        revision="fresh",
        collected_at=_NOW - timedelta(hours=1),
    )
    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(sources_root),
            "--now",
            _NOW.isoformat(),
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    entry = payload["entries"][0]
    assert entry["due"] is False


def test_cli_handles_multiple_manifests_mixed_cadence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    sources_root = repo_root / "rule-catalog" / "sources"
    sources_root.mkdir(parents=True)
    payload = repo_root / "payload"
    _write_source_tree(payload)

    for source_id, cadence in [
        ("alpha-daily", "daily"),
        ("beta-weekly", "weekly"),
        ("gamma-on-demand", "on-demand"),
    ]:
        d = sources_root / source_id
        d.mkdir()
        _write_manifest(
            d / "manifest.yaml",
            str(payload),
            source_id=source_id,
            cadence=cadence,
        )

    # Seed the weekly source with a fresh snapshot so only daily is due.
    _seed_snapshot(
        sources_root,
        "beta-weekly",
        revision="fresh",
        collected_at=_NOW - timedelta(days=1),
    )

    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(sources_root),
            "--now",
            _NOW.isoformat(),
        ]
    )
    assert exit_code == 0
    payload_out = json.loads(capsys.readouterr().out)
    by_id = {e["source_id"]: e for e in payload_out["entries"]}
    assert by_id["alpha-daily"]["due"] is True
    assert by_id["alpha-daily"]["collect_exit_code"] == 0
    assert by_id["beta-weekly"]["due"] is False
    assert by_id["gamma-on-demand"]["due"] is False


def test_cli_dry_run_and_verify_flags_forwarded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root, sources_root, _ = _build_repo_layout(tmp_path)
    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(sources_root),
            "--now",
            _NOW.isoformat(),
            "--dry-run",
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    entry = payload["entries"][0]
    assert entry["collect"]["dry_run"] is True
    # Dry-run must not have materialized a snapshot directory.
    snap_dir = sources_root / "watch-src"
    revisions = [d for d in snap_dir.iterdir() if d.is_dir()]
    assert revisions == []


# ---------------------------------------------------------------------------
# CLI — fail-fast paths
# ---------------------------------------------------------------------------


def test_cli_returns_2_when_collector_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Point at a manifest whose local source path does not exist —
    the collector CLI returns 2 and the watcher propagates that."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    sources_root = repo_root / "rule-catalog" / "sources"
    source_dir = sources_root / "broken-src"
    source_dir.mkdir(parents=True)
    manifest_path = source_dir / "manifest.yaml"
    _write_manifest(
        manifest_path,
        str(repo_root / "does-not-exist"),
        source_id="broken-src",
    )

    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(sources_root),
            "--now",
            _NOW.isoformat(),
        ]
    )
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    entry = payload["entries"][0]
    assert entry["due"] is True
    assert entry["collect_exit_code"] == 2


def test_cli_returns_2_on_manifest_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    sources_root = repo_root / "rule-catalog" / "sources"
    (sources_root / "bad").mkdir(parents=True)
    (sources_root / "bad" / "manifest.yaml").write_text("- not a mapping\n", encoding="utf-8")

    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(sources_root),
            "--now",
            _NOW.isoformat(),
        ]
    )
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    entry = payload["entries"][0]
    assert entry["due"] is False
    assert "error" in entry


def test_cli_returns_2_on_missing_sources_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope"
    exit_code = watcher_main(
        [
            "--sources-root",
            str(missing),
            "--repo-root",
            str(tmp_path),
            "--output-root",
            str(tmp_path),
            "--now",
            _NOW.isoformat(),
        ]
    )
    assert exit_code == 2
    assert "sources root not found" in capsys.readouterr().err


def test_cli_returns_2_on_bad_now_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, sources_root, _ = _build_repo_layout(tmp_path)
    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--now",
            "not-a-timestamp",
        ]
    )
    assert exit_code == 2
    assert "ISO-8601" in capsys.readouterr().err


def test_cli_returns_2_on_unknown_cadence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Poison the cadence interval table so ``is_due`` raises."""
    repo_root, sources_root, _ = _build_repo_layout(tmp_path)
    from aiopspilot.rule_catalog.pipeline import watcher as watcher_mod

    poisoned: dict[Cadence, timedelta | None] = {}
    monkeypatch.setattr(watcher_mod, "_CADENCE_INTERVALS", poisoned)

    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(sources_root),
            "--now",
            _NOW.isoformat(),
        ]
    )
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    entry = payload["entries"][0]
    assert entry["due"] is False
    assert "unknown cadence" in str(entry["error"])


def test_cli_defaults_now_to_current_utc(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When --now is omitted the CLI uses the current UTC time — smoke
    check that the emitted timestamp round-trips as UTC ISO-8601."""
    repo_root, sources_root, _ = _build_repo_layout(tmp_path, cadence="on-demand")
    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(sources_root),
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    parsed = datetime.fromisoformat(payload["now"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_cli_naive_now_flag_is_normalized_to_utc(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A naive ISO-8601 --now value MUST be treated as UTC."""
    repo_root, sources_root, _ = _build_repo_layout(tmp_path, cadence="on-demand")
    naive_now = _NOW.replace(tzinfo=None).isoformat()  # no timezone suffix
    exit_code = watcher_main(
        [
            "--sources-root",
            str(sources_root),
            "--repo-root",
            str(repo_root),
            "--output-root",
            str(sources_root),
            "--now",
            naive_now,
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    parsed = datetime.fromisoformat(payload["now"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_cli_repo_root_autodetected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting --repo-root falls back to the module's auto-detector."""
    # Use the shipped manifest — the shipped seed cadence is ``on-demand``
    # so this run should be a no-op (nothing due) and exit 0.
    real_repo_root = Path(__file__).resolve().parents[3]
    real_sources = real_repo_root / "rule-catalog" / "sources"
    exit_code = watcher_main(
        [
            "--sources-root",
            str(real_sources),
            "--output-root",
            str(tmp_path / "unused-out"),
            "--now",
            _NOW.isoformat(),
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    # Every shipped source has cadence=on-demand → nothing due.
    for entry in payload["entries"]:
        assert entry["due"] is False


# ---------------------------------------------------------------------------
# Loader → watcher integration smoke — the shipped manifest still parses.
# ---------------------------------------------------------------------------


def test_shipped_seed_manifest_loads_as_on_demand(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    manifest_path = repo_root / "rule-catalog" / "sources" / "aiopspilot-p1-seed" / "manifest.yaml"
    manifest = load_source_manifest_from_yaml(manifest_path)
    assert manifest.cadence is Cadence.ON_DEMAND
    watcher = SourceWatcher(snapshot_root=tmp_path)
    assert watcher.is_due(manifest, now=_NOW) is False
