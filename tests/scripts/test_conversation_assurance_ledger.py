from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/conversation-assurance-ledger.py"
    spec = importlib.util.spec_from_file_location("conversation_assurance_ledger", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _record(**overrides: object) -> dict[str, object]:
    return {
        "run_id": "run-2026-08-03",
        "qid": "Q113",
        "variant": "A",
        "mode": "positive",
        "expected_authority": "server_inventory_graph",
        "expected_status": "verified",
        "expected_reason": None,
        "actual_authority": "server_inventory_graph",
        "actual_status": "verified",
        "actual_reason": "inventory_snapshot_grounded",
        "checks_completed": 1,
        "checks_total": 1,
        "model_calls": 0,
        "commit": "abcdef123",
        "recorded_at": "2026-08-03T12:00:00Z",
        **overrides,
    }


def test_appends_private_bounded_jsonl_without_prompt(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "results.jsonl"
    result = module.CampaignResult.from_mapping(_record())

    module.append_result(path, result)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["unexpected_unverified"] is False
    assert "prompt" not in payload
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_marks_only_unexpected_unverified_results() -> None:
    module = _load_module()

    unexpected = module.CampaignResult.from_mapping(
        _record(actual_status="unverified", actual_reason="provider_unavailable")
    )
    expected = module.CampaignResult.from_mapping(
        _record(
            expected_authority="server_conversation_context",
            expected_status="unverified",
            expected_reason="prior_context_required",
            actual_authority="server_conversation_context",
            actual_status="unverified",
            actual_reason="prior_context_required",
            checks_completed=0,
        )
    )

    assert unexpected.to_dict()["unexpected_unverified"] is True
    assert expected.to_dict()["unexpected_unverified"] is False
    assert expected.to_dict()["passed"] is True


@pytest.mark.parametrize(
    "overrides",
    (
        {"qid": "113"},
        {"variant": "unknown"},
        {"checks_completed": 2, "checks_total": 1},
        {"commit": "not-a-commit"},
        {"recorded_at": "2026-08-03T12:00:00"},
        {"prompt": "must not be stored"},
    ),
)
def test_rejects_malformed_or_content_bearing_records(overrides: dict[str, object]) -> None:
    module = _load_module()

    with pytest.raises(ValueError):
        module.CampaignResult.from_mapping(_record(**overrides))


def test_rejects_symlink_output(tmp_path: Path) -> None:
    module = _load_module()
    target = tmp_path / "target.jsonl"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "results.jsonl"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        module.append_result(link, module.CampaignResult.from_mapping(_record()))
