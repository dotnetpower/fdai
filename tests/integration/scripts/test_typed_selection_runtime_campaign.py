"""Fake-mode runtime campaign: exact runtime path, no network, label oracle only."""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts/evaluation/typed_selection_runtime_campaign.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("typed_selection_runtime_campaign", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def test_fake_campaign_runs_the_runtime_shadow_path_without_changing_answers() -> None:
    campaign = _module()
    cases = campaign.load_cases()
    sample = (cases[0], cases[20], cases[24], cases[32])
    binding, http = campaign._fake_binding(sample)
    async with http:
        result = await campaign.run_campaign(
            binding=binding,
            cases=sample,
            repeats=1,
            probe_delay_seconds=0.0,
            progress=lambda _message: None,
        )
    rows = result["rows"]
    assert [row["case_id"] for row in rows] == [case.case_id for case in sample]
    assert all(row["unavailable_reason"] is None for row in rows)
    assert all(row["same_outcome"] for row in rows)
    assert all(set(row["gated_document_ids"]) == set(row["expected"]) for row in rows)
    assert all(row["terminal"]["answer_changed"] is False for row in rows)
    with pytest.raises(ValueError, match="every planned decision"):
        campaign.judge(rows, result["event_loop_lag_ms"])


def test_window_assets_and_protocol_agree_on_the_plan() -> None:
    campaign = _module()
    cases = campaign.load_cases()
    assert len(cases) == 64
    assert campaign.REPEATS == 4
    assert {case.language for case in cases} == {"en", "ko"}


def test_decision_evidence_is_private_and_digested_beyond_the_canonical_bound(
    tmp_path: Path,
) -> None:
    import hashlib

    campaign = _module()
    rows = [{"case_id": f"case-{index}", "padding": "x" * 512} for index in range(256)]
    path = tmp_path / "decisions.jsonl"
    digest = campaign.write_decisions(path, rows)
    data = path.read_bytes()
    assert len(data) > 65_536
    assert digest == "sha256:" + hashlib.sha256(data).hexdigest()
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        campaign.write_decisions(path, rows)
