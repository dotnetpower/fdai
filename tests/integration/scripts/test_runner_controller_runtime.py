"""Lease, bootstrap and drain invariants for the PAT-only controller, without live providers."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import threading
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts.automation.runner_controller.broker import Broker
from scripts.automation.runner_controller.config import Settings, policies
from scripts.automation.runner_controller.controller import Controller
from scripts.automation.runner_controller.service import verify_webhook
from scripts.automation.runner_controller.state import BlobState, LeaseLostError, _assert_no_secrets
from scripts.automation.runner_controller.transport import HttpResponse, ProviderError
from scripts.automation.runner_controller.workers import Workers

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime.now(UTC)


class MemoryState:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {"schema_version": 1, "workers": {}, "low_demand": {}}
        self.lock = threading.RLock()

    def read(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.data)

    def transaction(self, change):
        with self.lock:
            updated = copy.deepcopy(self.data)
            result = change(updated)
            _assert_no_secrets(updated)
            self.data = updated
            return result


class FakeGitHub:
    def __init__(self) -> None:
        self.registrations: list[dict[str, Any]] = []
        self.jobs: list[dict[str, Any]] = []
        self.minted = 0
        self.removed: list[int] = []
        self.allow_remove = True
        self.fail_jit = False

    def repository_id(self):
        return 1

    def runners(self):
        return self.registrations

    def queued_jobs(self):
        return self.jobs

    def jit(self, name, labels):
        self.minted += 1
        if self.fail_jit:
            raise ProviderError("unavailable", 503)
        return 10, "synthetic-short-jit"

    def remove_idle(self, identity, name):
        if self.allow_remove:
            self.removed.append(identity)
        return self.allow_remove


class FakeWorkers:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        self.naturally_done = False
        self.cleaned: list[str] = []

    def check_ownership(self):
        return None

    def start(self, worker, ticket):
        self.started.append(copy.deepcopy(worker))
        return f"execution-{worker['id']}"

    def terminal(self, worker):
        return self.naturally_done

    def cleanup(self, worker):
        self.cleaned.append(worker["id"])

    def absent(self, worker):
        return True

    def recover_reference(self, worker):
        return "recovered-execution"


def _settings(apply: bool = True) -> Settings:
    return Settings.load(
        json.dumps(
            {
                "repository": "example/repository",
                "name_prefix": "fdai-ci",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "resource_group": "rg-example-ci",
                "jobs": {"control": "job-example-control", "general": "job-example-general"},
                "worker_image": "registry.example.com/runner@sha256:" + "a" * 64,
                "controller_url": "https://controller.example.com",
                "location": "example-region",
                "vm_subnet_id": "",
                "vm_image_id": "",
                "vm_size": "Standard_D4ds_v4",
                "ssh_public_key": "",
                "storage_url": "https://examplestate.blob.core.windows.net",
                "storage_container": "ci-state",
                "storage_blob": "state.json",
                "cpu_budgets": {"container_cpu": 260, "vm_cpu": 64},
            }
        ),
        apply=apply,
    )


def _worker(identity: str = "owned", pool: str = "general", state: str = "starting"):
    return {
        "id": identity,
        "pool": pool,
        "name": f"fdai-ci-{pool}-{identity}",
        "status": state,
        "created_at": NOW.isoformat(),
        "since": NOW.isoformat(),
        "ticket_hash": hashlib.sha256(b"synthetic-worker-ticket").hexdigest(),
        "bootstrap_state": "new",
        "registration_id": None,
        "provider_ref": "execution-owned",
        "job_started": False,
        "listener_exit_code": None,
    }


def test_state_owner_cannot_be_rebound_to_another_azure_scope() -> None:
    engine, state, github, workers = _controller()
    engine.verify_scope()
    changed = replace(engine.settings, resource_group="rg-other-ci")
    other = Controller(changed, engine.policies, engine.metadata, state, github, workers)
    with pytest.raises(ValueError, match="different repository or Azure scope"):
        other.verify_scope()
    assert not workers.started


def test_terraform_default_origin_and_maximum_name_stem_load_from_platform() -> None:
    config = asdict(_settings())
    config.update(controller_url="", name_prefix="a" * 17 + "-worker")
    settings = Settings.load(json.dumps(config), apply=False, hostname="controller.example.com")
    assert settings.controller_url == "https://controller.example.com"
    assert len(settings.name_prefix) == 24


def test_cpu_budget_cannot_be_bypassed_by_a_larger_vm_sku() -> None:
    config = asdict(_settings())
    config["vm_size"] = "Standard_D16s_v5"
    with pytest.raises(ValueError, match="four-vCPU"):
        Settings.load(json.dumps(config), apply=True)


@pytest.mark.parametrize(
    "suffix",
    [
        "images/managed-image",
        "galleries/gallery/images/definition/versions/latest",
        "galleries/gallery/images/definition/versions/1.2.3",
    ],
)
def test_trusted_launch_requires_exact_gallery_image_version(suffix: str) -> None:
    config = asdict(_settings())
    prefix = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-ci"
    config.update(
        vm_image_id=f"{prefix}/providers/Microsoft.Compute/{suffix}",
        vm_subnet_id=f"{prefix}/providers/Microsoft.Network/virtualNetworks/vnet/subnets/ci",
        ssh_public_key="ssh-ed25519 synthetic",
    )
    if suffix.endswith("1.2.3"):
        assert Settings.load(json.dumps(config), apply=False).vm_image_id == config["vm_image_id"]
    else:
        with pytest.raises(ValueError, match="gallery"):
            Settings.load(json.dumps(config), apply=False)


def test_unowned_workers_are_not_adopted_on_controller_start() -> None:
    engine, state, _, _ = _controller()
    state.data["workers"]["owned"] = _worker()
    with pytest.raises(ValueError, match="without an owner binding"):
        engine.verify_scope()


def test_ambiguous_start_is_recovered_by_reference_without_restarting_it() -> None:
    engine, state, _, workers = _controller()
    worker = _worker()
    worker["provider_ref"] = None
    state.data["workers"]["owned"] = worker
    engine.reconcile(NOW)
    assert state.data["workers"]["owned"]["provider_ref"] == "recovered-execution"
    assert all(item["id"] != "owned" for item in workers.started)


def test_exclusive_pool_label_alone_can_trigger_scale_out() -> None:
    engine, _, github, workers = _controller()
    github.jobs = [
        {"status": "queued", "labels": ["FDAI-CI-GENERAL"], "runner_id": None} for _ in range(12)
    ]
    engine.reconcile(NOW)
    assert sum(worker["pool"] == "general" for worker in workers.started) == 20


def test_aged_idle_workers_receive_ready_replacements_before_rotation() -> None:
    engine, state, github, workers = _controller()
    labels = [{"name": value} for value in engine.metadata["pools"]["general"]["labels"]]
    for index in range(8):
        worker = _worker(f"old-{index}", state="idle")
        worker["created_at"] = (NOW - timedelta(hours=2)).isoformat()
        state.data["workers"][worker["id"]] = worker
        github.registrations.append(
            {
                "id": index + 1,
                "name": worker["name"],
                "labels": labels,
                "status": "online",
                "busy": False,
            }
        )
    engine.reconcile(NOW)
    assert not github.removed
    replacements = [worker for worker in workers.started if worker["pool"] == "general"]
    assert len(replacements) == 8
    for index, worker in enumerate(replacements):
        github.registrations.append(
            {
                "id": index + 100,
                "name": worker["name"],
                "labels": labels,
                "status": "online",
                "busy": False,
            }
        )
    engine.reconcile(NOW + timedelta(seconds=15))
    assert len(github.removed) == 1
    assert not workers.cleaned


@pytest.mark.parametrize(
    "power, expected",
    [
        ("PowerState/stopped", True),
        ("PowerState/deallocated", True),
        ("PowerState/running", False),
        ("ProvisioningState/succeeded", False),
    ],
)
def test_vm_power_readback_can_recover_lost_listener_callback(power, expected) -> None:
    class Azure:
        def get_resource(self, path, **kwargs):
            assert path.endswith("/instanceView")
            return {"statuses": [{"code": power}]}

    assert Workers(_settings(), Azure()).terminal(_worker(pool="docker")) is expected


def test_missing_instance_view_is_not_treated_as_terminated() -> None:
    class Azure:
        def get_resource(self, path, **kwargs):
            raise ProviderError("not_found", 404)

    assert Workers(_settings(), Azure()).terminal(_worker(pool="docker")) is False


def test_retained_terminal_proof_allows_post_delete_nic_readback() -> None:
    worker = _worker(pool="docker")
    worker.update(cleanup_requested=True, terminal_observed_at=NOW.isoformat())
    assert Workers(_settings(), None).terminal(worker) is True


@pytest.mark.parametrize("lose_lease", [False, True])
def test_vm_creation_waits_for_nic_and_rechecks_lease_before_effects(
    monkeypatch: pytest.MonkeyPatch,
    lose_lease: bool,
) -> None:
    observations, writes, checkpoints = [], [], []

    class Azure:
        def put_resource(self, path, body, **kwargs):
            writes.append((path, body))
            if "/virtualMachines/" in path:
                assert observations == ["Updating", "Succeeded"]

        def get_resource(self, path, **kwargs):
            phase = "Updating" if not observations else "Succeeded"
            observations.append(phase)
            return {"tags": {"fdai:worker": "owned"}, "properties": {"provisioningState": phase}}

    def authority():
        checkpoints.append(True)
        if lose_lease and len(checkpoints) == 2:
            raise LeaseLostError("synthetic lease loss")

    monkeypatch.setattr("scripts.automation.runner_controller.workers.time.sleep", lambda _: None)
    settings = replace(
        _settings(),
        vm_image_id="/synthetic/versioned-image",
        vm_subnet_id="/synthetic/subnet",
        ssh_public_key="ssh-ed25519 synthetic",
    )
    worker = _worker(pool="docker")
    resources = Workers(settings, Azure(), authority)
    if lose_lease:
        with pytest.raises(LeaseLostError):
            resources.start(worker, "synthetic-ticket")
        assert len(writes) == 1
    else:
        resources.start(worker, "synthetic-ticket")
        assert len(writes) == 2
        vm = writes[-1][1]
        assert "identity" not in vm
        bootstrap = base64.b64decode(vm["properties"]["osProfile"]["customData"]).decode()
        command = json.loads(bootstrap.removeprefix("#cloud-config\n"))["runcmd"][0][-1]
        assert command.index("broker-entrypoint.py") < command.index("systemctl poweroff")
        assert len(checkpoints) == 2


def test_terminal_cleanup_cannot_be_revived_by_a_late_started_callback() -> None:
    engine, state, github, _ = _controller()
    worker = _worker()
    worker.update(bootstrap_state="acked", cleanup_requested=True)
    state.data["workers"]["owned"] = worker
    broker = Broker(state, github, engine.metadata["pools"])
    with pytest.raises(ValueError, match="terminal resource cleanup"):
        broker.lifecycle("started", {"worker_id": "owned", "ticket": "synthetic-worker-ticket"})
    assert not state.data["workers"]["owned"]["job_started"]


def test_drain_intent_is_committed_before_provider_and_busy_rejection_restores_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, state, github, workers = _controller()
    worker = _worker(state="idle")
    worker["registration_id"] = 10
    state.data["workers"]["owned"] = worker

    def remove(identity, name):
        assert state.read()["workers"]["owned"]["status"] == "draining"
        return False

    monkeypatch.setattr(github, "remove_idle", remove)
    engine._drain("owned")
    assert state.data["workers"]["owned"]["status"] == "idle"
    assert not workers.cleaned


def test_ambiguous_unregister_keeps_its_durable_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, state, github, _ = _controller()
    worker = _worker(state="idle")
    worker["registration_id"] = 10
    state.data["workers"]["owned"] = worker

    def unavailable(identity, name):
        raise ProviderError("unavailable", 503)

    monkeypatch.setattr(github, "remove_idle", unavailable)
    with pytest.raises(ProviderError):
        engine._drain("owned")
    assert state.data["workers"]["owned"]["status"] == "draining"


def test_generic_labels_do_not_amplify_one_job_into_three_pool_demands() -> None:
    engine, _, github, workers = _controller()
    github.jobs = [{"status": "queued", "labels": ["self-hosted"], "runner_id": None}]
    engine.reconcile(NOW)
    assert sum(worker["pool"] == "general" for worker in workers.started) == 8


@pytest.mark.parametrize("matches", [0, 1, 2])
def test_container_start_recovery_uses_nonsecret_identity_not_another_start(matches: int) -> None:
    class Azure:
        def container_executions(self, job):
            return [
                {
                    "name": f"execution-{index}",
                    "properties": {
                        "template": {
                            "containers": [
                                {
                                    "env": [{"name": "FDAI_RUNNER_ID", "value": "owned"}],
                                }
                            ]
                        }
                    },
                }
                for index in range(matches)
            ]

    workers = Workers(_settings(), Azure())
    if matches == 2:
        with pytest.raises(ValueError, match="multiple provider executions"):
            workers.recover_reference(_worker())
    else:
        assert workers.recover_reference(_worker()) == ("execution-0" if matches else None)


def test_vm_cleanup_readback_never_deletes_a_replaced_resource() -> None:
    class Azure:
        def get_resource(self, path, **kwargs):
            return {"tags": {"fdai:worker": "some-other-worker"}}

        def delete_resource(self, *args, **kwargs):
            pytest.fail("replacement resource must not be deleted")

    worker = _worker(pool="docker")
    worker["listener_exit_code"] = 0
    with pytest.raises(ValueError, match="reserved worker identity"):
        Workers(_settings(), Azure()).cleanup(worker)


def test_orphan_nic_is_not_deleted_before_vm_disappearance() -> None:
    class Azure:
        def get_resource(self, path, **kwargs):
            return {"tags": {"fdai:worker": "owned"}}

        def delete_resource(self, *args, **kwargs):
            pytest.fail("NIC must remain until the VM is absent")

    assert Workers(_settings(), Azure(), lambda: None).absent(_worker(pool="docker")) is False


def test_nic_cleanup_waits_for_readback_after_delete_request() -> None:
    deleted = []

    class Azure:
        def get_resource(self, path, **kwargs):
            if "/virtualMachines/" in path:
                raise ProviderError("not_found", 404)
            return {"tags": {"fdai:worker": "owned"}}

        def delete_resource(self, path, **kwargs):
            deleted.append(path)

    assert Workers(_settings(), Azure(), lambda: None).absent(_worker(pool="docker")) is False
    assert len(deleted) == 1 and "/networkInterfaces/" in deleted[0]


@pytest.mark.parametrize("low", [-1, 9, True, 1.5])
def test_invalid_low_reserve_is_rejected_at_runtime_boundary(tmp_path: Path, low: Any) -> None:
    raw = json.loads((ROOT / "config/ci-runner-pools.json").read_text())
    raw["pools"]["general"]["warm_idle_low"] = low
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="low-demand reserve"):
        policies(path)


def _controller(apply: bool = True):
    settings = _settings(apply)
    pool_policies, metadata = policies(ROOT / "config/ci-runner-pools.json")
    state, github, workers = MemoryState(), FakeGitHub(), FakeWorkers()
    return (
        Controller(settings, pool_policies, metadata, state, github, workers),
        state,
        github,
        workers,
    )


def test_observation_mode_never_starts_or_removes_resources() -> None:
    controller, state, github, workers = _controller(False)
    controller.verify_scope()
    receipt = controller.reconcile(NOW)
    assert receipt["mode"] == "observe"
    assert workers.started == [] and github.removed == []
    assert state.read()["workers"] == {}


def test_warm_reserves_are_reserved_before_provider_effects_and_count_in_flight() -> None:
    controller, state, github, workers = _controller()
    controller.reconcile(NOW)
    assert len(workers.started) == 10  # Docker is explicitly unavailable without its baked image.
    assert len(state.read()["workers"]) == 10
    controller.reconcile(NOW + timedelta(seconds=1))
    assert len(workers.started) == 10
    assert all("bootstrap_ticket" not in item for item in state.read()["workers"].values())


def test_bad_quota_budget_is_refused_before_any_start() -> None:
    controller, state, github, workers = _controller()
    object.__setattr__(controller.settings, "cpu_budgets", {"container_cpu": 10, "vm_cpu": 64})
    with pytest.raises(ValueError, match="budgets"):
        controller.verify_scope()
    assert workers.started == []


def test_one_use_ticket_is_claimed_before_jit_and_never_resends_the_secret() -> None:
    controller, state, github, workers = _controller()
    state.data["workers"]["owned"] = _worker()
    broker = Broker(state, github, controller.metadata["pools"])
    assert broker.bootstrap("owned", "synthetic-worker-ticket", NOW) == "synthetic-short-jit"
    assert github.minted == 1
    assert "synthetic-short-jit" not in json.dumps(state.read())
    with pytest.raises(ValueError, match="claimed"):
        broker.bootstrap("owned", "synthetic-worker-ticket", NOW)
    assert github.minted == 1


def test_concurrent_bootstrap_replay_cannot_mint_a_second_registration() -> None:
    controller, state, github, workers = _controller()
    state.data["workers"]["owned"] = _worker()
    broker = Broker(state, github, controller.metadata["pools"])
    entered, finish = threading.Event(), threading.Event()
    results = []

    def mint(name, labels):
        github.minted += 1
        entered.set()
        assert finish.wait(3)
        return 10, "synthetic-short-jit"

    github.jit = mint
    thread = threading.Thread(
        target=lambda: results.append(broker.bootstrap("owned", "synthetic-worker-ticket", NOW))
    )
    thread.start()
    assert entered.wait(3)
    try:
        with pytest.raises(ValueError, match="claimed"):
            broker.bootstrap("owned", "synthetic-worker-ticket", NOW)
        assert github.minted == 1
    finally:
        finish.set()
        thread.join(timeout=3)
    assert results == ["synthetic-short-jit"]


def test_offline_registrations_do_not_count_as_ready_warm_runners() -> None:
    controller, state, github, workers = _controller(False)
    item = _worker()
    state.data["workers"]["owned"] = item
    github.registrations = [
        {
            "id": 10,
            "name": item["name"],
            "status": "offline",
            "busy": False,
            "labels": [
                {"name": label.lower()}
                for label in controller.metadata["pools"]["general"]["labels"]
            ],
        }
    ]
    controller.reconcile(NOW)
    assert state.read()["workers"]["owned"]["status"] == "starting"


def test_jit_provider_failure_keeps_claim_and_does_not_blindly_retry() -> None:
    controller, state, github, workers = _controller()
    state.data["workers"]["owned"] = _worker()
    broker = Broker(state, github, controller.metadata["pools"])
    github.fail_jit = True
    with pytest.raises(ProviderError):
        broker.bootstrap("owned", "synthetic-worker-ticket", NOW)
    assert state.read()["workers"]["owned"]["bootstrap_state"] == "claimed"
    with pytest.raises(ValueError):
        broker.bootstrap("owned", "synthetic-worker-ticket", NOW)
    assert github.minted == 1


def test_expired_ticket_never_calls_registration_provider() -> None:
    controller, state, github, workers = _controller()
    state.data["workers"]["owned"] = _worker()
    broker = Broker(state, github, controller.metadata["pools"])
    with pytest.raises(ValueError, match="expired"):
        broker.bootstrap("owned", "synthetic-worker-ticket", NOW + timedelta(seconds=301))
    assert github.minted == 0


def test_started_lease_is_monotonic_and_vetoes_drain() -> None:
    controller, state, github, workers = _controller()
    item = _worker(state="idle")
    item.update(bootstrap_state="delivered", registration_id=10)
    state.data["workers"]["owned"] = item
    Broker(state, github, controller.metadata["pools"]).lifecycle(
        "started", {"worker_id": "owned", "ticket": "synthetic-worker-ticket"}
    )
    controller._drain("owned")
    assert github.removed == []
    assert state.read()["workers"]["owned"]["job_started"] is True


def test_busy_assignment_race_rejection_never_stops_a_resource() -> None:
    controller, state, github, workers = _controller()
    item = _worker(state="idle")
    item["registration_id"] = 10
    state.data["workers"]["owned"] = item
    github.allow_remove = False
    controller._drain("owned")
    assert state.read()["workers"]["owned"]["status"] == "idle"
    assert workers.cleaned == []


def test_successful_registration_removal_still_waits_for_natural_exit() -> None:
    controller, state, github, workers = _controller()
    item = _worker(state="idle")
    item["registration_id"] = 10
    state.data["workers"]["owned"] = item
    controller._drain("owned")
    assert state.read()["workers"]["owned"]["status"] == "draining"
    controller._retire_finished({}, set())
    assert workers.cleaned == []
    assert "owned" in state.read()["workers"]
    workers.naturally_done = True
    controller._retire_finished({}, {10})
    assert "owned" in state.read()["workers"]
    controller._retire_finished({}, set())
    assert "owned" not in state.read()["workers"]


@pytest.mark.parametrize(
    "secret_key", ["pat", "access_token", "encoded_jit_config", "bootstrap_ticket"]
)
def test_persistent_state_rejects_registration_secrets(secret_key: str) -> None:
    with pytest.raises(ValueError, match="secrets"):
        _assert_no_secrets({"workers": [{"nested": {secret_key: "not-persistable"}}]})


def test_webhook_signatures_are_required_and_bound_to_the_raw_body() -> None:
    import hmac

    body = b'{"workflow_job":{}}'
    signature = "sha256=" + hmac.new(b"webhook-key", body, hashlib.sha256).hexdigest()
    assert verify_webhook("webhook-key", signature, body)
    assert not verify_webhook("webhook-key", signature, body + b" ")
    assert not verify_webhook("", signature, body)


class BlobTransport:
    def __init__(self):
        self.value = None
        self.etag = '"one"'
        self.fail_write = False
        self.calls = []

    def request(self, method, url, *, body=None, headers=None, accepted=(200,)):
        self.calls.append((method, url, headers, body))
        if "?comp=lease" in url:
            return HttpResponse(201 if headers["x-ms-lease-action"] == "acquire" else 200, None, {})
        if method == "GET":
            return HttpResponse(200, copy.deepcopy(self.value), {"ETag": self.etag})
        if headers.get("If-None-Match") == "*":
            self.value = body
        elif self.fail_write:
            raise ProviderError("conditional_write", 412)
        else:
            assert headers["If-Match"] == self.etag
            assert headers["x-ms-lease-id"]
            self.value = body
            self.etag = '"two"'
        return HttpResponse(201, None, {"ETag": self.etag})


def test_conditional_state_failure_revokes_all_further_effect_authority() -> None:
    transport = BlobTransport()
    state = BlobState(
        "https://examplestate.blob.core.windows.net",
        "ci-state",
        "state.json",
        lambda: "synthetic-token",
        transport,
    )
    state.open()
    transport.fail_write = True
    with pytest.raises(LeaseLostError, match="stopping"):
        state.transaction(lambda data: data.update(new="value"))
    with pytest.raises(LeaseLostError):
        state.read()


def test_broker_worker_never_passes_jit_material_as_a_command_line() -> None:
    source = (ROOT / "infra/ci-runner-aca/broker-entrypoint.py").read_text(encoding="utf-8")
    assert '"ACTIONS_RUNNER_INPUT_JITCONFIG": credential' in source
    assert '"--jitconfig"' not in source
    assert "GITHUB_RUNNER_CREDENTIAL" not in source
    assert "environment.clear()" in source
