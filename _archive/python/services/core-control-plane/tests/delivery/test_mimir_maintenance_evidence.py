from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.delivery.mimir_maintenance_evidence import ImmutableMimirMaintenanceEvidence
from fdai.runtime.bootstrap_mimir_maintenance import build_mimir_maintenance_source


def _manifest() -> dict[str, object]:
    fingerprint = "a" * 64
    return {
        "schema_version": "1.0.0",
        "source_revision": "b" * 40,
        "review_ref": "review:approved:42",
        "promotions": [
            {
                "problem_fingerprint": fingerprint,
                "promotion_pr": "https://github.com/example/fdai/pull/42",
                "correlation_id": "promotion-42",
                "outcome": "promoted",
                "rule_id": "rule.reviewed",
                "promoted_at": "2026-10-13T00:00:00+00:00",
                "candidate_digest": "c" * 64,
                "package_digest": "d" * 64,
            }
        ],
        "regressions": [
            {
                "problem_fingerprint": fingerprint,
                "promotion_pr": "https://github.com/example/fdai/pull/42",
                "rule_id": "rule.reviewed",
                "passed": True,
                "started_at": "2026-10-13T01:00:00+00:00",
                "completed_at": "2026-10-14T02:00:00+00:00",
                "evidence_ref": "regression:reviewed:42",
            }
        ],
        "deprecations": [
            {
                "rule_id": "rule.retired",
                "reason": "reviewed-retirement",
                "evidence_ref": "deprecation:reviewed:7",
                "observed_at": "2026-10-14T03:00:00+00:00",
            }
        ],
    }


def _write(path: Path, payload: dict[str, object]) -> str:
    content = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


async def test_reviewed_snapshot_supplies_all_three_mimir_ports(tmp_path: Path) -> None:
    path = tmp_path / "mimir-maintenance.json"
    source = ImmutableMimirMaintenanceEvidence.load(
        path,
        expected_digest=_write(path, _manifest()),
    )
    now = datetime(2026, 10, 15, tzinfo=UTC)

    outcomes = await source.read_promotion_outcomes(limit=10, now=now)
    assert len(outcomes) == 1
    assert outcomes[0].review_ref == "review:approved:42"
    assert (await source.run_regression(outcomes[0], now=now)).passed is True
    deprecations = await source.stale_or_retired_rules(limit=10, now=now)
    assert [item.rule_id for item in deprecations] == ["rule.retired"]


@pytest.mark.parametrize("mutation", ["digest", "missing_regression", "extra_field"])
def test_reviewed_snapshot_rejects_unbound_or_changed_evidence(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = _manifest()
    if mutation == "missing_regression":
        payload["regressions"] = []
    elif mutation == "extra_field":
        payload["execution_authority"] = True
    path = tmp_path / "mimir-maintenance.json"
    digest = _write(path, payload)
    if mutation == "digest":
        digest = "f" * 64
    with pytest.raises(ValueError):
        ImmutableMimirMaintenanceEvidence.load(path, expected_digest=digest)


def test_bootstrap_requires_exact_runtime_revision(tmp_path: Path) -> None:
    path = tmp_path / "mimir-maintenance.json"
    digest = _write(path, _manifest())
    environment = {
        "FDAI_MIMIR_MAINTENANCE_EVIDENCE_PATH": str(path),
        "FDAI_MIMIR_MAINTENANCE_EVIDENCE_SHA256": digest,
        "FDAI_SOURCE_REVISION": "b" * 40,
    }
    assert build_mimir_maintenance_source(environment) is not None
    environment["FDAI_SOURCE_REVISION"] = "e" * 40
    with pytest.raises(RuntimeError, match="revision differs"):
        build_mimir_maintenance_source(environment)


async def test_empty_reviewed_snapshot_is_a_bound_noop(tmp_path: Path) -> None:
    payload = _manifest()
    payload["promotions"] = []
    payload["regressions"] = []
    payload["deprecations"] = []
    path = tmp_path / "mimir-maintenance.json"
    source = ImmutableMimirMaintenanceEvidence.load(
        path,
        expected_digest=_write(path, payload),
    )
    now = datetime(2026, 10, 15, tzinfo=UTC)
    assert await source.read_promotion_outcomes(limit=10, now=now) == ()
    assert await source.stale_or_retired_rules(limit=10, now=now) == ()


@pytest.mark.parametrize("missing", ["path", "digest"])
def test_partial_bootstrap_configuration_fails_closed(tmp_path: Path, missing: str) -> None:
    environment = {
        "FDAI_MIMIR_MAINTENANCE_EVIDENCE_PATH": str(tmp_path / "evidence.json"),
        "FDAI_MIMIR_MAINTENANCE_EVIDENCE_SHA256": "a" * 64,
    }
    environment.pop(
        "FDAI_MIMIR_MAINTENANCE_EVIDENCE_PATH"
        if missing == "path"
        else "FDAI_MIMIR_MAINTENANCE_EVIDENCE_SHA256"
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        build_mimir_maintenance_source(environment)
