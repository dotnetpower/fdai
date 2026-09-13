from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from fdai_deployment_cli import cli, standalone_application, standalone_host, standalone_review
from fdai_deployment_cli.contracts import canonical_digest


def _review(**overrides):
    value = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": "application",
        "plan_digest": "a" * 64,
        "target_binding": "b" * 64,
        "source_commit": "c" * 40,
        "summary": {"action_counts": {"create": 1, "update": 0, "delete": 1, "replace": 0}},
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "mutation_performed": False,
        "subscription_ready": False,
        **overrides,
    }
    value["review_digest"] = canonical_digest(value)
    return value


@pytest.mark.parametrize("prompt_number", [1, 2])
def test_approval_eof_never_grants_authority(tmp_path, monkeypatch, capsys, prompt_number) -> None:
    calls = []

    def read_input(_prompt):
        calls.append(True)
        if len(calls) == prompt_number:
            raise EOFError()
        return "application-apply"

    monkeypatch.setattr("builtins.input", read_input)
    monkeypatch.setattr(
        standalone_application,
        "_azure_actor_digest",
        lambda _binding: pytest.fail("EOF must not reach actor lookup"),
    )
    with pytest.raises(ValueError, match="approval input closed"):
        standalone_application._approve_plan(tmp_path, _review())
    assert not list(tmp_path.glob("*approval.json"))
    assert capsys.readouterr().out == ""


def test_identity_prompt_eof_has_stable_cli_exit(monkeypatch, capsys) -> None:
    def closed(**_kwargs):
        raise EOFError()

    monkeypatch.setattr(cli, "deploy_azure_foundation", closed)
    assert cli.main(["provision", "azure", "--online", "--progress", "plain"]) == 3
    output = capsys.readouterr()
    assert "approval input closed" in output.err
    assert "Traceback" not in output.err
    assert output.out == ""


@pytest.mark.parametrize(
    "overrides",
    [
        {"stage": "../outside"},
        {"stage": "unknown"},
        {"summary": {"action_counts": {"delete": -1, "replace": 1}}},
        {"summary": {"action_counts": {"delete": True}}},
        {"summary": {"action_counts": {"delete": "0"}}},
        {"summary": {"action_counts": {"delete": 5001}}},
        {"expires_at": "2000-01-01T00:00:00Z"},
        {"expires_at": "2000-01-01T00:00:00"},
        {"expires_at": "not-a-timestamp"},
        {"expires_at": None},
        {"plan_digest": "not-a-digest"},
        {"schema_version": "future"},
        {"mutation_performed": True},
        {"unexpected_secret_field": "do-not-render-this"},
    ],
)
def test_invalid_review_is_rejected_before_prompt_or_output(
    tmp_path, monkeypatch, capsys, overrides
) -> None:
    monkeypatch.setattr(
        "builtins.input", lambda _prompt: pytest.fail("invalid review reached input")
    )
    with pytest.raises(ValueError, match="plan review"):
        standalone_application._approve_plan(tmp_path, _review(**overrides))
    assert not list(tmp_path.iterdir())
    assert capsys.readouterr().out == ""


def test_changed_review_digest_is_rejected_before_prompt(tmp_path, monkeypatch) -> None:
    review = _review()
    review["summary"]["action_counts"]["delete"] = 0
    monkeypatch.setattr(
        "builtins.input", lambda _prompt: pytest.fail("tampered review reached input")
    )
    with pytest.raises(ValueError, match="plan review"):
        standalone_application._approve_plan(tmp_path, review)


@pytest.mark.parametrize(
    "summary",
    [
        {"action_counts": {"create": 1}, "credentials": "must-not-render"},
        {"action_counts": {"create": 1}, "resource_type_counts": {"\x1b[2J": 1}},
        {"action_counts": {"create": 1}, "resource_changes": {}},
        {"action_counts": {"create": 1}, "resource_changes": [{"unexpected": "must-not-render"}]},
        {
            "action_counts": {"create": 1},
            "resource_changes": [{"address": "a\r\nb", "actions": ["create"]}],
        },
        {
            "action_counts": {"create": 1},
            "resource_changes": [{"address": "a", "actions": ["unknown"]}],
        },
    ],
)
def test_review_display_has_no_raw_extension_fields(tmp_path, monkeypatch, capsys, summary) -> None:
    monkeypatch.setattr(
        "builtins.input", lambda _prompt: pytest.fail("invalid review reached input")
    )
    with pytest.raises(ValueError, match="plan review"):
        standalone_application._approve_plan(tmp_path, _review(summary=summary))
    output = capsys.readouterr()
    assert "must-not-render" not in output.err
    assert "\x1b" not in output.err
    assert output.out == ""


def test_review_expiring_during_approval_never_writes_approval(tmp_path, monkeypatch) -> None:
    now = datetime.now(UTC)
    clock = [now]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(standalone_review, "datetime", Clock)
    answers = iter(("application-apply", "application-apply-destructive"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    def actor(_binding):
        clock[0] = now + timedelta(hours=2)
        return "d" * 64

    monkeypatch.setattr(standalone_application, "_azure_actor_digest", actor)
    with pytest.raises(ValueError, match="plan review"):
        standalone_application._approve_plan(tmp_path, _review())
    assert not list(tmp_path.iterdir())


def test_exact_approval_still_passes_managed_host_validation(tmp_path, monkeypatch) -> None:
    review = _review(
        summary={
            "action_counts": {"create": 1, "delete": 1},
            "resource_type_counts": {"azurerm_resource_group": 2},
            "resource_changes": [
                {"address": "azurerm_resource_group.new", "actions": ["create"]},
                {"address": "azurerm_resource_group.old", "actions": ["delete"]},
            ],
        }
    )
    answers = iter(("application-apply", "application-apply-destructive"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(standalone_application, "_azure_actor_digest", lambda _binding: "d" * 64)
    path = standalone_application._approve_plan(tmp_path, review)
    assert path.stat().st_mode & 0o777 == 0o600
    approval = json.loads(path.read_text())
    standalone_host._validate_approval(review, approval, context=review)
