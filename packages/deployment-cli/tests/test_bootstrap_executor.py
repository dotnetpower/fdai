from __future__ import annotations

import importlib
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from fdai_deployment_cli import bootstrap_channel as channel
from fdai_deployment_cli.bootstrap_approval import (
    approval_source,
    require_decision,
    selected_source,
)
from fdai_deployment_cli.bootstrap_executor import BootstrapBlocked, BootstrapExecutor
from fdai_deployment_cli.bootstrap_worker import run_request, serve
from fdai_deployment_cli.contracts import canonical_digest

ROOT = Path(__file__).resolve().parents[3]
SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
TENANT = "00000000-0000-0000-0000-000000000000"


def application_review():
    value = {
        "schema_version": "fdai.standalone-application-plan.v1",
        "stage": "application",
        "plan_digest": "a" * 64,
        "target_binding": "b" * 64,
        "source_commit": "c" * 40,
        "summary": {"action_counts": {"create": 1, "update": 0, "delete": 1, "replace": 0}},
        "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    value["review_digest"] = canonical_digest(value)
    return value


@pytest.fixture
def prompt(monkeypatch):
    scripts = ROOT / "scripts/deployment/azure"
    monkeypatch.syspath_prepend(str(scripts))
    module = importlib.import_module("genesis_approval_prompt")
    monkeypatch.setattr(module, "current_actor_digest", lambda _: "e" * 64)
    return module


def fake_az(command, **kwargs):
    assert kwargs["env"]["AZURE_CONFIG_DIR"].endswith("/azure")
    assert kwargs["capture_output"] is True
    if command[1:3] == ["account", "list"]:
        value = [
            {
                "id": SUBSCRIPTION,
                "tenantId": TENANT,
                "name": "Example subscription",
                "state": "Enabled",
            }
        ]
    elif command[1:3] == ["account", "show"]:
        value = {"id": SUBSCRIPTION, "tenantId": TENANT, "user": {"type": "user"}}
    elif command[1] == "login":
        return SimpleNamespace(returncode=0, stdout="sensitive raw login output", stderr="")
    else:
        value = None
    return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")


def test_synthetic_customer_flow_uses_actual_genesis_entra_and_application_callbacks(
    tmp_path,
    monkeypatch,
    prompt,
):
    from fdai_deployment_cli import source_input, standalone_application

    monkeypatch.setattr(
        source_input, "inspect_source", lambda *_, **__: SimpleNamespace(commit="c" * 40)
    )
    monkeypatch.setattr(standalone_application, "_azure_actor_digest", lambda *_, **__: "e" * 64)
    seen = []

    def planner(**kwargs):
        assert "report_hub_request" not in kwargs
        assert kwargs["runtime_profile"].runtime_platform.value == "aks"
        assert kwargs["runtime_profile"].console_selected is True
        assert kwargs["timeout_seconds"] == 14400
        approval_dir = tmp_path / "approvals"
        approval_dir.mkdir(mode=0o700, exist_ok=True)
        for stage, evidence in [
            ("foundation-apply", {"review_digest": "a" * 64, "plan_digest": "b" * 64}),
            ("entra-config", {"plan_digest": "c" * 64}),
        ]:
            prompt.create_approval(
                stage=stage,
                evidence=evidence,
                run_binding="d" * 64,
                source_commit="c" * 40,
                actor_digest="e" * 64,
                output=approval_dir / f"{stage}.json",
            )
        standalone_application._approve_plan(approval_dir, application_review())
        return {"deployment_ready": True, "console_url": "https://console.example.com"}

    def factory(area, decide):
        return BootstrapExecutor(area, decide, run=fake_az, planner=planner)

    channel.submit_request(tmp_path, "login", {})
    request = channel._read(tmp_path)["pending"]
    record = channel._read(tmp_path)
    record["pending"] = None
    channel._write(tmp_path, record)
    run_request(tmp_path, request, executor_factory=factory)
    assert channel.read_status(tmp_path)["accounts"][0]["id"] == SUBSCRIPTION
    assert channel.read_status(tmp_path)["request_id"] is None
    assert "sensitive" not in json.dumps(channel.read_status(tmp_path))
    channel.submit_request(
        tmp_path,
        "install",
        {
            "subscription_id": SUBSCRIPTION,
            "region": "eastus",
            "monthly_cost_ceiling": 500,
            "artifact_source": "source",
            "source_root": str(ROOT),
        },
    )
    request = channel._read(tmp_path)["pending"]
    record = channel._read(tmp_path)
    record["pending"] = None
    channel._write(tmp_path, record)
    thread = threading.Thread(
        target=run_request, args=(tmp_path, request), kwargs={"executor_factory": factory}
    )
    thread.start()
    deadline = time.monotonic() + 10
    while thread.is_alive() and time.monotonic() < deadline:
        status = channel.read_status(tmp_path)
        review = status["review"]
        if status["phase"] == "review" and review["id"] not in seen:
            with pytest.raises(ValueError, match="already"):
                channel.submit_request(tmp_path, "install", request["payload"])
            decision = {
                "request_id": status["request_id"],
                "review_id": review["id"],
                "digest": review["digest"],
                "approved": True,
                "confirmation": review["confirmation_required"],
            }
            with pytest.raises(ValueError):
                channel.submit_decision(tmp_path, {**decision, "digest": "f" * 64})
            channel.submit_decision(tmp_path, decision)
            seen.append(review["id"])
        time.sleep(0.01)
    thread.join(1)
    assert not thread.is_alive()
    assert len(seen) == 3
    status = channel.read_status(tmp_path)
    assert status["phase"] == "ready" and status["deployment_ready"] is True
    assert status["console_url"] == "https://console.example.com"
    assert selected_source() is None
    assert (tmp_path / "executor/configuration.json").stat().st_mode & 0o777 == 0o600


def test_denial_digest_substitution_and_expiry_never_write_approval(tmp_path, monkeypatch, prompt):
    from fdai_deployment_cli import standalone_application

    monkeypatch.setattr(standalone_application, "_azure_actor_digest", lambda *_, **__: "e" * 64)
    for reply in (
        lambda r: {
            "approved": False,
            "digest": r["digest"],
            "confirmation": r["confirmation_required"],
        },
        lambda r: {
            "approved": True,
            "digest": "f" * 64,
            "confirmation": r["confirmation_required"],
        },
        lambda r: {"approved": True, "digest": r["digest"], "confirmation": "yes"},
    ):
        with approval_source(reply), pytest.raises(ValueError, match="denied"):
            standalone_application._approve_plan(tmp_path, application_review())
    assert not (tmp_path / "application-approval.json").exists()
    expired = {
        "digest": "a" * 64,
        "confirmation_required": "approve",
        "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    }
    with (
        approval_source(lambda _: pytest.fail("Expired review reached callback")),
        pytest.raises(ValueError),
    ):
        require_decision(expired)


def test_actor_change_during_injected_review_denies_existing_verifier(tmp_path, monkeypatch):
    from fdai_deployment_cli import standalone_application

    actors = iter(("e" * 64, "f" * 64))
    monkeypatch.setattr(
        standalone_application, "_azure_actor_digest", lambda *_, **__: next(actors)
    )

    def approve(review):
        return {
            "approved": True,
            "digest": review["digest"],
            "confirmation": review["confirmation_required"],
        }

    with approval_source(approve), pytest.raises(ValueError, match="operator changed"):
        standalone_application._approve_plan(tmp_path, application_review())
    assert not list(tmp_path.glob("*approval.json"))


def test_resume_cannot_replace_target_and_inspect_never_claims_old_health(tmp_path):
    executor = BootstrapExecutor(tmp_path, lambda _: {}, run=fake_az)
    channel._write(
        tmp_path,
        {
            "subscription_id": str(UUID(int=1)),
            "tenant_id": TENANT,
        },
        "configuration.json",
    )
    with pytest.raises(BootstrapBlocked, match="changed"):
        executor.execute("resume", {})
    channel._write(
        tmp_path, {"subscription_id": SUBSCRIPTION, "tenant_id": TENANT}, "configuration.json"
    )
    channel._write(tmp_path, {"deployment_ready": True}, "acceptance.json")
    assert executor.execute("inspect", {}).get("deployment_ready") is not True


def test_worker_startup_interrupts_pending_work_without_replay(tmp_path):
    channel.submit_request(tmp_path, "login", {})
    serve(tmp_path, total_seconds=0)
    status = channel.read_status(tmp_path)
    assert status["phase"] == "interrupted"
    assert channel._read(tmp_path)["pending"] is None


def test_worker_publishes_idle_heartbeat_and_exits_with_deadline(tmp_path):
    serve(tmp_path, total_seconds=1)
    heartbeat = channel._read(tmp_path, "heartbeat.json")
    assert heartbeat["pid"] > 0
    assert channel.read_status(tmp_path)["phase"] == "idle"


def test_relogin_preserves_pinned_installation_and_does_not_unlock_new_install(tmp_path):
    area = tmp_path / "executor"
    executor = BootstrapExecutor(area, lambda _: {}, run=fake_az)
    config = {"subscription_id": SUBSCRIPTION, "tenant_id": TENANT, "source_commit": "c" * 40}
    channel._write(area, config, "configuration.json")
    channel.submit_request(tmp_path, "login", {})
    record = channel._read(tmp_path)
    request = record["pending"]
    record["pending"] = None
    channel._write(tmp_path, record)
    run_request(tmp_path, request, executor_factory=lambda *_: executor)
    assert channel._read(area, "configuration.json") == config
    status = channel.read_status(tmp_path)
    assert status["phase"] == "blocked" and status["request_id"] == request["id"]


def test_resume_reuses_pinned_configuration_and_native_handoff_stops_bootstrap(
    tmp_path,
    monkeypatch,
    prompt,
):
    from fdai_deployment_cli import source_input

    calls = []
    monkeypatch.setattr(
        source_input,
        "inspect_source",
        lambda source, **kwargs: (
            calls.append((source, kwargs["expected_commit"])) or SimpleNamespace(commit="c" * 40)
        ),
    )
    plans = []
    executor = BootstrapExecutor(
        tmp_path,
        lambda _: {},
        run=fake_az,
        planner=lambda **kwargs: plans.append(kwargs) or {"deployment_ready": False},
    )
    config = {
        "subscription_id": SUBSCRIPTION,
        "tenant_id": TENANT,
        "source_root": str(ROOT),
        "source_commit": "c" * 40,
        "region": "eastus",
        "monthly_cost_ceiling": 500,
        "artifact_source": "source",
    }
    channel._write(tmp_path, config, "configuration.json")
    assert executor.execute("resume", {})["deployment_ready"] is False
    assert calls == [(ROOT, "c" * 40)]
    assert plans[0]["region"] == "eastus" and plans[0]["monthly_cost_ceiling"] == 500
    channel._write(tmp_path, {"accepted": True}, "native-ownership.json")
    with pytest.raises(BootstrapBlocked, match="Native"):
        executor.execute("resume", {})
    assert len(plans) == 1


def test_legacy_support_cannot_silently_use_terminal_invocation_approval(
    tmp_path,
    monkeypatch,
    prompt,
):
    from fdai_deployment_cli import source_input

    monkeypatch.setattr(
        source_input, "inspect_source", lambda *_a, **_k: SimpleNamespace(commit="c" * 40)
    )
    monkeypatch.setattr(prompt, "BOOTSTRAP_APPROVAL_PROTOCOL", 0)
    executor = BootstrapExecutor(
        tmp_path,
        lambda _: pytest.fail("Legacy source reached callback"),
        run=fake_az,
        planner=lambda **_: pytest.fail("Legacy source reached mutation coordinator"),
    )
    with pytest.raises(BootstrapBlocked, match="lacks"):
        executor.execute(
            "install",
            {
                "subscription_id": SUBSCRIPTION,
                "region": "eastus",
                "monthly_cost_ceiling": 500,
                "artifact_source": "source",
                "source_root": str(ROOT),
            },
        )


def test_login_passes_optional_tenant_and_accounts_prioritize_default_real_subscription(tmp_path):
    seen_commands = []
    other_sub = str(UUID(int=2))
    tenant_placeholder = str(UUID(int=9))

    def multi_tenant_az(command, **kwargs):
        seen_commands.append(command)
        if command[1] == "login":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[1:3] == ["account", "list"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "id": tenant_placeholder,
                            "tenantId": tenant_placeholder,
                            "name": "N/A(tenant level account)",
                            "state": "Enabled",
                        },
                        {
                            "id": other_sub,
                            "tenantId": TENANT,
                            "name": "Secondary subscription",
                            "state": "Enabled",
                        },
                        {
                            "id": SUBSCRIPTION,
                            "tenantId": TENANT,
                            "name": "Primary default subscription",
                            "state": "Enabled",
                        },
                    ]
                ),
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="null", stderr="")

    executor = BootstrapExecutor(tmp_path, lambda _: {}, run=multi_tenant_az)
    (executor.azure / "azureProfile.json").write_text(
        json.dumps(
            {
                "subscriptions": [
                    {
                        "id": SUBSCRIPTION,
                        "tenantId": TENANT,
                        "state": "Enabled",
                        "isDefault": True,
                    }
                ]
            }
        )
    )
    result = executor.execute("login", {"tenant_id": TENANT})
    assert seen_commands[0][:4] == ["az", "login", "--tenant", TENANT]
    assert [item["id"] for item in result["accounts"]] == [SUBSCRIPTION, other_sub]
