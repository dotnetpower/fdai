from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_RECORDER = _ROOT / "scripts" / "automation" / "record-azure-discovery-canary.py"


def _fake_az(tmp_path: Path) -> Path:
    calls = tmp_path / "calls"
    binary = tmp_path / "az"
    binary.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["FAKE_AZ_CALLS"], "a", encoding="ascii") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")

if sys.argv[1:3] == ["account", "show"]:
    print(json.dumps({
        "id": os.environ["FAKE_AZ_SUBSCRIPTION"],
        "tenantId": os.environ["FAKE_AZ_TENANT"],
        "state": "Enabled",
    }))
elif sys.argv[1] == "version":
    print(json.dumps({
        "azure-cli": os.environ.get("FAKE_AZ_CLI_VERSION", "2.87.0"),
        "extensions": {"resource-graph": "2.1.1"},
    }))
elif sys.argv[1:3] == ["graph", "query"]:
    query = sys.argv[sys.argv.index("--graph-query") + 1]
    if query.startswith("ResourceContainers"):
        print(json.dumps({
            "count": 1,
            "data": [{"discovered_count": 3}],
            "skip_token": None,
            "total_records": 1,
        }))
    else:
        total_records = int(os.environ.get("FAKE_ARG_TOTAL_RECORDS", "2"))
        print(json.dumps({
            "count": 2,
            "data": [
                {"type": "Example.Compute/widgets", "resource_count": 4},
                {"type": "Example.Network/links", "resource_count": 2},
            ],
            "skip_token": None,
            "total_records": total_records,
        }))
else:
    raise SystemExit(9)
""",
        encoding="ascii",
    )
    binary.chmod(0o755)
    return calls


def _run(
    tmp_path: Path,
    *,
    cli_version: str = "2.87.0",
    total_records: int = 2,
) -> tuple[subprocess.CompletedProcess[str], Path, str]:
    calls = _fake_az(tmp_path)
    output = tmp_path / "evidence.json"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "PYTHONPATH": (
            f"{_ROOT / 'services' / 'core-control-plane' / 'src'}:"
            f"{_ROOT / 'packages' / 'service-contracts' / 'src'}"
        ),
        "FAKE_AZ_CALLS": str(calls),
        "FAKE_AZ_SUBSCRIPTION": "subscription-example",
        "FAKE_AZ_TENANT": "tenant-example",
        "FAKE_AZ_CLI_VERSION": cli_version,
        "FAKE_ARG_TOTAL_RECORDS": str(total_records),
    }
    result = subprocess.run(  # noqa: S603 - controlled repository script and fake CLI
        [
            sys.executable,
            str(_RECORDER),
            "--subscription-id",
            "subscription-example",
            "--output",
            str(output),
        ],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, output, calls.read_text(encoding="ascii") if calls.exists() else ""


def test_recorder_retains_only_complete_sanitized_aggregate_evidence(tmp_path: Path) -> None:
    result, output, calls = _run(tmp_path)

    assert result.returncode == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["reconciliation"]["complete"] is True
    assert [item["discovered_count"] for item in payload["coverage_receipts"]] == [3, 6]
    assert [item["provider_type_count"] for item in payload["aggregate_proofs"]] == [1, 2]
    assert all(not item["observed_provider_types"] for item in payload["coverage_receipts"])
    assert calls.count("account show --output json") == 3
    assert "summarize discovered_count=count()" in calls
    assert "summarize resource_count=count() by type" in calls
    for forbidden in (
        "subscription-example",
        "tenant-example",
        "/subscriptions/subscription-example",
        "tenantId",
        "subscriptionId",
        "Example.Compute/widgets",
        "Example.Network/links",
        "project id",
        "project name",
        "tags",
    ):
        assert forbidden not in encoded


def test_recorder_rejects_version_drift_before_provider_queries(tmp_path: Path) -> None:
    result, output, calls = _run(tmp_path, cli_version="2.86.0")

    assert result.returncode == 1
    assert not output.exists()
    assert "version does not match the pin" in result.stderr
    assert "graph query" not in calls


def test_recorder_rejects_incomplete_arg_response(tmp_path: Path) -> None:
    result, output, _calls = _run(tmp_path, total_records=3)

    assert result.returncode == 1
    assert not output.exists()
    assert "response is incomplete or invalid" in result.stderr


def test_offline_validation_rejects_tampered_retained_evidence(tmp_path: Path) -> None:
    result, output, _calls = _run(tmp_path)
    assert result.returncode == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["reconciliation"]["complete"] = False
    output.write_text(json.dumps(payload), encoding="utf-8")

    validation = subprocess.run(  # noqa: S603 - controlled repository script
        [sys.executable, str(_RECORDER), "--validate", "--output", str(output)],
        cwd=_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": (
                f"{_ROOT / 'services' / 'core-control-plane' / 'src'}:"
                f"{_ROOT / 'packages' / 'service-contracts' / 'src'}"
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert validation.returncode == 1
    assert "digest does not match" in validation.stderr
