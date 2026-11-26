from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


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


def test_retries_short_append_without_corrupting_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    path = tmp_path / "results.jsonl"
    real_write = os.write
    calls = 0

    def short_write(descriptor: int, payload: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, payload[: len(payload) // 2])
        return real_write(descriptor, payload)

    monkeypatch.setattr(module.os, "write", short_write)
    module.append_result(path, module.CampaignResult.from_mapping(_record()))

    assert json.loads(path.read_text(encoding="utf-8"))["qid"] == "Q113"
    assert calls == 2


def test_rolls_back_partial_append_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    path = tmp_path / "results.jsonl"
    path.write_text('{"existing":true}\n', encoding="utf-8")
    original = path.read_bytes()
    real_write = os.write
    calls = 0

    def failing_write(descriptor: int, payload: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, payload[: len(payload) // 2])
        raise OSError("simulated disk failure")

    monkeypatch.setattr(module.os, "write", failing_write)

    with pytest.raises(OSError, match="simulated disk failure"):
        module.append_result(path, module.CampaignResult.from_mapping(_record()))

    assert path.read_bytes() == original


def test_concurrent_appends_remain_complete_json_lines(tmp_path: Path) -> None:
    module = _load_module()
    path = tmp_path / "results.jsonl"

    def append(index: int) -> None:
        module.append_result(
            path,
            module.CampaignResult.from_mapping(_record(run_id=f"run-{index}", variant="cohort")),
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        tuple(pool.map(append, range(32)))

    payloads = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(payloads) == 32
    assert {payload["run_id"] for payload in payloads} == {f"run-{index}" for index in range(32)}


def test_rejects_oversized_stdin_record_before_json_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    stream = io.TextIOWrapper(io.BytesIO(b" " * (module._MAX_INPUT_BYTES + 1)))
    monkeypatch.setattr(module.sys, "stdin", stream)

    with pytest.raises(ValueError, match="input line exceeds"):
        module.main([])
