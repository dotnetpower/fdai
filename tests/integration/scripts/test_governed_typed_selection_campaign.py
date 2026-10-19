"""Governed answer-path campaign mechanics use the actual prepare and consume boundary."""

import importlib.util
import sys
from pathlib import Path


def _module():
    script = (
        Path(__file__).resolve().parents[3]
        / "scripts/evaluation/governed_typed_selection_campaign.py"
    )
    spec = importlib.util.spec_from_file_location("governed_typed_selection_campaign", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def test_fake_campaign_runs_actual_governed_prepare_and_consume_path() -> None:
    campaign = _module()
    cases = campaign.load_cases()
    sample = (cases[0], cases[16], cases[24], cases[28])
    harness = await campaign._build_runtime(None, governed_read=True)
    await campaign._prepare(harness.runtime, harness.state)
    reader, http = await campaign._reader(
        runtime_env=None,
        cases=sample,
        harness=harness,
        source_revision="0" * 40,
    )
    activation = await campaign._activate_evaluation_pointer(
        reader,
        source_revision="0" * 40,
    )
    failures = campaign.AdapterFailureLog()
    async with http:
        result = await campaign.run_campaign(
            reader=reader,
            harness=harness,
            cases=sample,
            live=False,
            failures=failures,
        )
    rows = result["rows"]
    assert len(rows) == 16
    assert all(row["selected"] == row["expected"] for row in rows)
    assert {row["outcome"] for row in rows} == {"held", "returned"}
    assert not failures.counts
    assert activation["binding_digest"].startswith("sha256:")
