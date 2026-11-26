"""Result acceptance trusts controller observations, not candidate reviews or artifact files."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fdai.core.security.code_findings.review_signal import ReviewSource
from fdai.delivery.code_security_acquire import AcquiredSource
from fdai.delivery.code_security_prepared_source import export_prepared_source
from fdai.delivery.code_security_result_acceptance import (
    ScanResultRejectedError,
    record_accepted_prepared_scan,
)
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox, ScannerRunResult
from fdai.delivery.code_security_scan_job import ScanJobConfig, run_scan_job
from fdai.delivery.persistence.state_store_code_security_review import (
    code_security_review_state_key,
)
from fdai.rule_catalog.code_security import load_code_security_catalog
from fdai.rule_catalog.code_security_scanners import ScannerCatalog, ScannerSpec
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_CATALOG = Path(__file__).resolve().parents[4] / "rule-catalog/code-security"
_REVISION = "a" * 40


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "review",
        "issues",
        "receipt",
        "identity",
        "completion",
        "stdout",
        "missing",
        "duplicate",
        "producer",
        "unbound",
        "source",
    ],
)
async def test_result_is_rebuilt_before_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    (original / "app.py").write_text("import os\nos.system(user_input)\n")
    prepared = export_prepared_source(
        AcquiredSource(original, _REVISION, "b" * 40),
        tmp_path / "prepared",
        repository_alias="example-app",
        source=ReviewSource(kind="git_repository", provider="git"),
    )
    spec = ScannerSpec.model_validate(
        {
            "producer": "Opengrep",
            "argv": ["scan", "{source}"],
            "success_exit_codes": [0],
            "timeout_seconds": 30,
            "max_output_bytes": 100_000,
        }
    )
    scanners = ScannerCatalog.model_validate(
        {
            "schema_version": 1,
            "catalog_id": "example.scanners",
            "version": "1.0.0",
            "scanners": {"opengrep": spec},
        }
    )
    sarif = json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "Opengrep", "version": "1"}},
                    "results": [
                        {
                            "ruleId": "test",
                            "message": {"text": "finding"},
                            "properties": {"tags": ["CWE-78"]},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "app.py"},
                                        "region": {"startLine": 2},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ).encode()
    observed = ScannerRunResult("opengrep", "Opengrep", sarif, 0, True, False, False, 1, "")

    async def scan(*args: object, **kwargs: object) -> ScannerRunResult:
        return observed

    monkeypatch.setattr(BubblewrapScannerSandbox, "run", scan)
    catalog = load_code_security_catalog(_CATALOG)
    config = ScanJobConfig(
        repository="",
        revision=_REVISION,
        repository_alias="example-app",
        work_root=tmp_path / "candidate",
        executables={"opengrep": Path("/unused")},
        rules_dir=_CATALOG / "rules",
        source=prepared.source,
    )
    candidate = await run_scan_job(
        config,
        catalog=catalog,
        scanners=scanners,
        acquirer=None,
        sandbox=BubblewrapScannerSandbox(),
        prepared_source=prepared,
    )
    observations = [observed]
    if mutation == "review":
        candidate = replace(candidate, package={**candidate.package, "coverage_complete": False})
    elif mutation == "issues":
        candidate = replace(candidate, issues=())
    elif mutation == "receipt":
        candidate = replace(candidate, receipt=replace(candidate.receipt, runs=()))
    elif mutation == "identity":
        candidate = replace(candidate, tree_id="c" * 40)
    elif mutation == "completion":
        observations = [replace(observed, exit_code=1)]
    elif mutation == "stdout":
        observations = [replace(observed, stdout=b'{"version":"2.1.0","runs":[]}')]
    elif mutation == "missing":
        observations = []
    elif mutation == "duplicate":
        observations = [observed, observed]
    elif mutation == "producer":
        observations = [replace(observed, producer="Other")]
    elif mutation == "unbound":
        config = replace(config, executables={})
    elif mutation == "source":
        path = prepared.acquired.path / "app.py"
        path.chmod(0o600)
        path.write_text("tampered\n")
    # Candidate artifacts are never read for acceptance.
    (candidate.artifact_dir / "review.json").write_text('{"fake":true}')
    store = InMemoryStateStore()
    parameters = dict(
        prepared=prepared,
        observations=observations,
        config=config,
        catalog=catalog,
        scanners=scanners,
        verifier_catalog=None,
        verification_work_root=tmp_path / "verification",
    )
    if mutation == "none":
        assert await record_accepted_prepared_scan(store, candidate, **parameters)
        assert not await record_accepted_prepared_scan(store, candidate, **parameters)
        recorded = await store.read_state(code_security_review_state_key("example-app", _REVISION))
        assert recorded is not None and recorded["package"] == candidate.package
    else:
        with pytest.raises((ValueError, RuntimeError)):
            await record_accepted_prepared_scan(store, candidate, **parameters)
        assert (
            await store.read_state(code_security_review_state_key("example-app", _REVISION)) is None
        )


def test_observation_completion_cannot_be_claimed_by_stdout() -> None:
    from fdai.delivery.code_security_result_acceptance import _ObservationReplay

    spec = ScannerSpec.model_validate(
        {
            "producer": "Opengrep",
            "argv": ["scan", "{source}"],
            "success_exit_codes": [0],
            "timeout_seconds": 30,
            "max_output_bytes": 1000,
        }
    )
    scanners = ScannerCatalog.model_validate(
        {
            "schema_version": 1,
            "catalog_id": "example.scanners",
            "version": "1.0.0",
            "scanners": {"opengrep": spec},
        }
    )
    for run in (
        ScannerRunResult("opengrep", "Opengrep", b"", 0, True, True, False, 1, ""),
        ScannerRunResult("opengrep", "Opengrep", b"x" * 1001, 0, True, False, False, 1, ""),
        ScannerRunResult("unknown", "Opengrep", b"", 0, True, False, False, 1, ""),
    ):
        with pytest.raises(ScanResultRejectedError):
            _ObservationReplay([run], scanners)
