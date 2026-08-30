from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/automation/conversation_assurance_cli.py"
    spec = importlib.util.spec_from_file_location("conversation_assurance_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dry_run_previews_bounded_selection_without_operator_call(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()

    result = module.main(
        [
            "--project",
            str(tmp_path),
            "start",
            "--suite",
            "agent",
            "--agent",
            "Njord",
            "--questions",
            "4",
            "--dry-run",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["state"] == "preview"
    assert payload["questions"] == 4
    assert len(payload["census_digest"]) == 64
    assert not (tmp_path / ".fdai").exists()


def test_start_without_operator_binding_holds_without_retry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.delenv("FDAI_CONVERSATION_ASSURANCE_OPERATOR_URL", raising=False)

    result = module.main(
        ["--project", str(tmp_path), "start", "--suite", "agent", "--questions", "1"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload == {"reason": "operator_url_unavailable", "state": "held"}


def test_stop_and_status_are_private_and_do_not_start_campaign(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()

    module.main(["--project", str(tmp_path), "stop"])
    stop_payload = json.loads(capsys.readouterr().out)
    module.main(["--project", str(tmp_path), "status"])
    status_payload = json.loads(capsys.readouterr().out)

    stop = tmp_path / ".fdai/conversation-assurance/STOP"
    assert stop_payload["state"] == "stop_requested"
    assert status_payload["stop_requested"] is True
    assert status_payload["campaigns"] == 0
    assert stat.S_IMODE(stop.stat().st_mode) == 0o600


def test_private_token_file_rejects_group_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    token = tmp_path / "token"
    token.write_text("not-printed", encoding="utf-8")
    os.chmod(token, 0o640)
    monkeypatch.setenv("FDAI_CONVERSATION_ASSURANCE_TOKEN_FILE", str(token))

    with pytest.raises(module.CampaignHoldError, match="not_private"):
        module._token_from_private_file()


def test_private_token_file_reports_missing_path_as_hold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv(
        "FDAI_CONVERSATION_ASSURANCE_TOKEN_FILE",
        str(tmp_path / "missing-token"),
    )

    with pytest.raises(module.CampaignHoldError, match="unavailable"):
        module._token_from_private_file()


def test_private_token_file_rejects_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    target = tmp_path / "target"
    target.write_text("not-printed", encoding="utf-8")
    os.chmod(target, 0o600)
    link = tmp_path / "token"
    link.symlink_to(target)
    monkeypatch.setenv("FDAI_CONVERSATION_ASSURANCE_TOKEN_FILE", str(link))

    with pytest.raises(module.CampaignHoldError, match="not_private"):
        module._token_from_private_file()


def test_terminal_parser_requires_done_event() -> None:
    module = _load_module()

    with pytest.raises(module.CampaignHoldError, match="terminal_response_missing"):
        module._terminal_payload('event: progress\ndata: {"status":"running"}\n\n')


def test_supervisor_dispatch_is_idle_until_an_explicit_start(tmp_path: Path) -> None:
    module = _load_module()

    status = module._dispatch(tmp_path, {"operation": "status"})
    rejected = module._dispatch(tmp_path, {"operation": "unknown"})

    assert status["campaigns"] == 0
    assert status["evaluations"] == 0
    assert rejected == {"state": "rejected", "reason": "unsupported_operation"}
    assert not (tmp_path / ".fdai/conversation-assurance/campaigns.jsonl").exists()


def test_report_renders_latest_evaluations_without_starting_campaign(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()

    result = module.main(["--project", str(tmp_path), "report", "--top", "20"])
    output = capsys.readouterr().out

    assert result == 0
    assert "# Conversation Assurance Report" in output
    assert "| Case | Agent | Locale | Score | Verdict |" in output
    assert "not measured" in output
    assert not (tmp_path / ".fdai/conversation-assurance/campaigns.jsonl").exists()


def test_qualification_replay_failure_is_retained_as_a_hold(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / ".fdai/conversation-assurance"
    campaigns = module.PrivateJsonlLedger(root / "campaigns.jsonl")
    for child in range(12):
        campaign_id = f"campaign-{child}"
        questions = 20 if child < 11 else 10
        campaigns.append(
            {
                "event": "campaign_started",
                "campaign_id": campaign_id,
                "parent_series_id": "series-one",
            }
        )
        campaigns.append(
            {
                "event": "campaign_completed",
                "campaign_id": campaign_id,
                "parent_series_id": "series-one",
                "state": "completed",
                "evaluated": questions,
                "requested": questions,
            }
        )
    module.PrivateJsonlLedger(root / "evaluations.jsonl").append(
        {
            "schema_version": "1.0.0",
            "campaign_id": "campaign-0",
            "parent_series_id": "series-one",
            "trace_receipt_digest": "a" * 64,
        }
    )

    with pytest.raises(module.CampaignHoldError, match="evidence_invalid"):
        module._record_qualification(
            tmp_path,
            "series-one",
            module.build_pantheon_census(module.PANTHEON_SPECS),
        )

    status = module._status(tmp_path)
    assert status["latest_qualification"] == {
        "schema_version": "1.0.0",
        "event": "qualification_held",
        "parent_series_id": "series-one",
        "state": "held",
        "reason": "qualification_evidence_invalid",
        "qualification_authority": False,
        "execution_authority": False,
    }
