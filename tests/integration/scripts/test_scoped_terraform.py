from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(_SCRIPTS))


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


receiver = _load("scoped_terraform_receiver")
coordinator = _load("scoped_terraform")

SCOPE = "aks-container-insights"
DCR, DCRA = receiver.SCOPES[SCOPE]["targets"]
GUID_A = "00000000-0000-0000-0000-000000000001"
GUID_B = "00000000-0000-0000-0000-000000000002"
GUID_C = "00000000-0000-0000-0000-000000000003"
BACKEND = {
    "storage_account_name": "stexample",
    "container_name": "tfstate",
    "key": "fdai-dev-aks-cluster.tfstate",
    "resource_group_name": "rg-example-ops",
}
WORKSPACE = (
    "/subscriptions/x/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/w"
)

FAKE_TERRAFORM = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
config = json.loads((Path(__file__).parent / "fake.json").read_text())
arguments = sys.argv[1:]
with (Path(__file__).parent / "calls.log").open("a") as log:
    log.write(" ".join(arguments[:1] + [a for a in arguments if a.startswith("-target")]) + "\n")
command = arguments[0]
if command == "init":
    backend = dict(a.split("=", 2)[1:] for a in arguments if a.startswith("-backend-config="))
    backend.update(config.get("backend_override", {}))
    data = Path(os.environ["TF_DATA_DIR"])
    data.mkdir(parents=True, exist_ok=True)
    state = {"backend": {"type": "azurerm", "config": backend}}
    (data / "terraform.tfstate").write_text(json.dumps(state))
elif command == "plan":
    if "-detailed-exitcode" in arguments:
        sys.exit(config.get("verify_exit", 0))
    out = next(a.split("=", 1)[1] for a in arguments if a.startswith("-out="))
    Path(out).write_text(json.dumps(config["plan"]))
elif command == "show":
    if len(arguments) > 2:
        print(Path(arguments[2]).read_text())
    else:
        print(json.dumps(config.get("state", {})))
elif command == "apply":
    sys.exit(config.get("apply_exit", 0))
"""


def _plan(*changes: tuple[str, list[str]]) -> dict[str, object]:
    return {
        "resource_changes": [
            {"address": address, "change": {"actions": actions}} for address, actions in changes
        ]
    }


def _state(*addresses: str) -> dict[str, object]:
    resources = [{"address": a, "values": {"id": f"/id/{a}"}} for a in addresses]
    return {"values": {"root_module": {"resources": resources}}}


class Host:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        terraform = self.bin / "terraform"
        terraform.write_text(
            FAKE_TERRAFORM.replace("#!/usr/bin/env python3", f"#!{sys.executable}")
        )
        terraform.chmod(0o755)
        self.base = tmp_path / "state"
        self.source = tmp_path / "source"
        self.source.mkdir()
        (self.source / "main.tf").write_text('variable "location" {}\n')
        self.configure(plan=_plan((DCRA, ["create"])), state=_state(DCR, DCRA))
        monkeypatch.setattr(receiver, "SEARCH_PATH", f"{self.bin}:/usr/bin:/bin")
        self.receiver_bytes = (_SCRIPTS / "scoped_terraform_receiver.py").read_bytes()
        self.variables = receiver.canonical({"location": "westus2"})

    def configure(self, **values: object) -> None:
        (self.bin / "fake.json").write_text(json.dumps(values))

    def binding(self, mode: str = "apply") -> dict[str, Any]:
        binding: dict[str, Any] = {
            "scope": SCOPE,
            "mode": mode,
            "source_commit": "a" * 40,
            "source_tree_digest": receiver.tree_digest(self.source),
            "receiver_digest": receiver.sha256(self.receiver_bytes),
            "vars_digest": receiver.sha256(self.variables),
            "backend": BACKEND,
            "executor": {"client_id": GUID_A, "tenant_id": GUID_B, "subscription_id": GUID_C},
            "vm_resource_id": "/subscriptions/c/resourceGroups/rg/providers/Microsoft.Compute/"
            "virtualMachines/vm",
        }
        binding["operation_id"] = receiver.operation_id(binding)
        return binding

    def approval(self, binding: dict[str, Any], plan_sha: str, **changes: object) -> dict:
        now = datetime.now(UTC).replace(microsecond=0)
        approval: dict[str, object] = {
            "operation_id": binding["operation_id"],
            "plan_sha256": plan_sha,
            "scope": SCOPE,
            "mode": binding["mode"],
            "actor_object_id": GUID_A,
            "approved_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        }
        approval.update(changes)
        approval["approval_digest"] = receiver.sha256(receiver.canonical(approval))
        return approval

    def call(self, operation: str, binding: dict[str, Any] | None = None, **extra: object) -> dict:
        binding = binding or self.binding()
        request = {"schema_version": receiver.REQUEST_SCHEMA, "operation": operation, **binding}
        request.update(extra)
        incoming = self.tmp / f"incoming-{len(list(self.tmp.glob('incoming-*')))}"
        incoming.mkdir()
        (incoming / "receiver.py").write_bytes(self.receiver_bytes)
        (incoming / "payload.tar.gz").write_bytes(
            coordinator.payload_archive(self.source, request, self.variables)
        )
        return receiver.run(incoming, base=self.base, identity=lambda _executor: None)

    def operation_dir(self, binding: dict[str, Any]) -> Path:
        return self.base / binding["operation_id"]


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    return Host(tmp_path, monkeypatch)


def test_plan_returns_bound_review_for_registered_targets(host: Host) -> None:
    result = host.call("plan")

    assert result["state"] == "planned"
    assert result["changes"] == [{"address": DCRA, "actions": ["create"]}]
    plan_bytes = (host.operation_dir(host.binding()) / "plan.tfplan").read_bytes()
    assert result["plan_sha256"] == hashlib.sha256(plan_bytes).hexdigest()
    calls = (host.bin / "calls.log").read_text()
    assert f"plan -target={DCR} -target={DCRA}" in calls


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        (((DCRA, ["create"]), ("azurerm_kubernetes_cluster.runtime", ["update"])), "scope"),
        (((DCR, ["delete"]),), "action"),
        (((DCR, ["delete", "create"]),), "action"),
        (((DCR, ["create", "delete"]),), "action"),
    ],
)
def test_plan_rejects_out_of_scope_or_destructive_changes(
    host: Host, changes: tuple[tuple[str, list[str]], ...], code: str
) -> None:
    host.configure(plan=_plan(*changes), state={})

    with pytest.raises(receiver.ReceiverError, match=code):
        host.call("plan")
    assert not (host.operation_dir(host.binding()) / "review.json").exists()


def test_destroy_mode_accepts_only_target_deletes(host: Host) -> None:
    host.configure(plan=_plan((DCRA, ["delete"])), state={})

    assert host.call("plan", host.binding("destroy"))["state"] == "planned"
    host.configure(plan=_plan((DCRA, ["create"])), state={})
    with pytest.raises(receiver.ReceiverError, match="action"):
        host.call("plan", host.binding("destroy"))


def test_zero_change_plan_is_converged_without_review(host: Host) -> None:
    host.configure(plan=_plan((DCR, ["no-op"]), (DCRA, ["no-op"])), state={})

    assert host.call("plan") == {"state": "converged", "changes": []}
    assert not (host.operation_dir(host.binding()) / "plan.tfplan").exists()


def test_apply_requires_exact_approved_plan_digest(host: Host) -> None:
    binding = host.binding()
    host.call("plan", binding)

    with pytest.raises(receiver.ReceiverError, match="apply_plan_digest_mismatch"):
        host.call("apply", binding, approval=host.approval(binding, "0" * 64))
    assert not (host.operation_dir(binding) / "claim.json").exists()


def test_apply_claims_once_then_verifies_without_repeat(host: Host) -> None:
    binding = host.binding()
    review = host.call("plan", binding)
    approval = host.approval(binding, review["plan_sha256"])

    result = host.call("apply", binding, approval=approval)

    assert result["apply_outcome"] == "applied"
    assert result["scope_zero_change"] is True
    assert result["resource_ids"] == {DCR: f"/id/{DCR}", DCRA: f"/id/{DCRA}"}
    claim = json.loads((host.operation_dir(binding) / "claim.json").read_text())
    assert claim["approval_digest"] == approval["approval_digest"]
    with pytest.raises(receiver.ReceiverError, match="apply_already_claimed"):
        host.call("apply", binding, approval=approval)
    assert host.call("plan", binding) == {"state": "already-applied", "apply_outcome": "applied"}
    assert (host.bin / "calls.log").read_text().count("apply") == 1


def test_failed_apply_keeps_receipt_and_requires_verification_only(host: Host) -> None:
    binding = host.binding()
    review = host.call("plan", binding)
    host.configure(plan=_plan((DCRA, ["create"])), state=_state(DCR), apply_exit=1, verify_exit=2)

    result = host.call("apply", binding, approval=host.approval(binding, review["plan_sha256"]))

    assert result["apply_outcome"] == "apply-failed"
    assert result["scope_zero_change"] is False
    receipt = json.loads((host.operation_dir(binding) / "receipt.json").read_text())
    assert receipt["outcome"] == "apply-failed"


def test_claim_without_receipt_blocks_new_plan(host: Host) -> None:
    binding = host.binding()
    host.call("plan", binding)
    receiver.write_once(host.operation_dir(binding) / "claim.json", {"interrupted": True})

    assert host.call("plan", binding) == {"state": "recovery-required"}
    verified = host.call("verify", binding)
    assert verified["claimed"] is True and verified["receipt"] is False


@pytest.mark.parametrize(
    "tamper",
    [
        {"operation_id": "0" * 24},
        {"vars_digest": "0" * 64},
        {"backend": {**BACKEND, "access_key": "x"}},
        {"mode": "replace"},
    ],
)
def test_request_binding_tampering_is_rejected(host: Host, tamper: dict[str, object]) -> None:
    with pytest.raises(receiver.ReceiverError):
        host.call("plan", host.binding(), **tamper)


def test_expired_or_rewritten_approval_is_rejected(host: Host) -> None:
    binding = host.binding()
    review = host.call("plan", binding)
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    expired = host.approval(binding, review["plan_sha256"], expires_at=past)
    rewritten = {**host.approval(binding, review["plan_sha256"]), "actor_object_id": GUID_B}

    with pytest.raises(receiver.ReceiverError, match="approval_expired"):
        host.call("apply", binding, approval=expired)
    with pytest.raises(receiver.ReceiverError, match="approval_digest_mismatch"):
        host.call("apply", binding, approval=rewritten)


def test_source_backend_block_and_backend_rebinding_are_rejected(host: Host) -> None:
    host.configure(plan=_plan(), backend_override={"key": "other.tfstate"})
    with pytest.raises(receiver.ReceiverError, match="backend_binding_mismatch"):
        host.call("plan")

    (host.source / "backend.tf").write_text('terraform {\n  backend "local" {}\n}\n')
    with pytest.raises(receiver.ReceiverError, match="source_backend_block_rejected"):
        host.call("plan")


def test_concurrent_operation_reports_busy(host: Host) -> None:
    import fcntl

    receiver.private_directory(host.base)
    descriptor = os.open(host.base / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        assert host.call("plan") == {"state": "busy"}
    finally:
        os.close(descriptor)


def test_result_line_stays_within_run_command_output_bound() -> None:
    line = receiver.emit({"state": "planned", "padding": "x" * 5000})

    assert len(line.encode()) <= receiver.MAX_RESULT_BYTES
    assert json.loads(line.removeprefix(receiver.RESULT_PREFIX))["code"] == "result_too_large"


def _private(tmp_path: Path, name: str, value: object, mode: int = 0o600) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(value))
    path.chmod(mode)
    return path


def _profile(**changes: object) -> dict[str, object]:
    profile: dict[str, object] = {
        "schema_version": coordinator.PROFILE_SCHEMA,
        "approval_profile": "dev-single-operator",
        "tenant_id": GUID_B,
        "subscription_id": GUID_C,
        "vm_resource_id": f"/subscriptions/{GUID_C}/resourceGroups/rg-ops/providers/"
        "Microsoft.Compute/virtualMachines/vm-runner",
        "executor_client_id": GUID_A,
        "backend": BACKEND,
    }
    profile.update(changes)
    return profile


@pytest.mark.parametrize(
    ("changes", "mode", "message"),
    [
        ({}, 0o644, "private regular file"),
        ({"backend": {**BACKEND, "sas_token": "x"}}, 0o600, "backend accepts only"),
        ({"approval_profile": "production"}, 0o600, "dev single-operator"),
        ({"vm_resource_id": "/subscriptions/other/vm"}, 0o600, "vm_resource_id"),
    ],
)
def test_profile_rejects_unsafe_or_unbound_inputs(
    tmp_path: Path, changes: dict[str, object], mode: int, message: str
) -> None:
    path = _private(tmp_path, "profile.json", _profile(**changes), mode)

    with pytest.raises(coordinator.CoordinatorError, match=message):
        coordinator.load_profile(path)


def test_variables_must_be_declared_and_secret_free(tmp_path: Path) -> None:
    declared = {"location", "tags"}
    good = _private(tmp_path, "good.json", {"location": "westus2"})
    assert json.loads(coordinator.load_variables(good, declared)) == {"location": "westus2"}

    undeclared = _private(tmp_path, "undeclared.json", {"client_secret": "x"})
    with pytest.raises(coordinator.CoordinatorError, match="undeclared"):
        coordinator.load_variables(undeclared, declared)
    secret = _private(
        tmp_path, "secret.json", {"tags": {"c": "DefaultEndpointsProtocol=https;AccountKey=x"}}
    )
    with pytest.raises(coordinator.CoordinatorError, match="secret-like"):
        coordinator.load_variables(secret, declared)


def test_script_embeds_digest_checked_receiver_and_payload() -> None:
    receiver_bytes, payload = b"print('receiver')\n", b"payload-bytes"
    script = coordinator.build_script(receiver_bytes, payload)

    blocks = re.findall(r"<<'(FDAI_\w+)'\n(.*?)\n\1\n", script, re.DOTALL)
    decoded = {name: base64.b64decode(body) for name, body in blocks}
    assert decoded == {"FDAI_RECEIVER": receiver_bytes, "FDAI_PAYLOAD": payload}
    assert hashlib.sha256(receiver_bytes).hexdigest() in script
    assert hashlib.sha256(payload).hexdigest() in script
    assert "sha256sum -c" in script and "python3 -I" in script
    with pytest.raises(coordinator.CoordinatorError, match="size bound"):
        coordinator.build_script(receiver_bytes, os.urandom(coordinator.MAX_SCRIPT_BYTES))


def test_parse_result_reads_last_stdout_marker_only() -> None:
    marker = receiver.RESULT_PREFIX
    message = (
        f'Enable succeeded: \n[stdout]\n{marker}{{"state":"old"}}\n{marker}'
        f'{{"state":"planned"}}\n\n[stderr]\n{marker}{{"state":"forged"}}\n'
    )
    output = json.dumps({"value": [{"message": message}]})

    assert coordinator.parse_result(output) == {"state": "planned"}
    empty = json.dumps({"value": [{"message": "[stdout]\n\n[stderr]\n"}]})
    with pytest.raises(coordinator.CoordinatorError, match="never apply"):
        coordinator.parse_result(empty)


def test_approval_requires_exact_token_and_is_host_verifiable(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = host.binding()
    review = {"plan_sha256": "ab" * 32, "changes": []}
    monkeypatch.setattr(coordinator.select, "select", lambda r, *_: (r, [], []))

    monkeypatch.setattr(coordinator.sys, "stdin", _Input("apply wrong\n"))
    with pytest.raises(coordinator.CoordinatorError, match="denied"):
        coordinator.approve(review, binding, GUID_A)

    monkeypatch.setattr(coordinator.sys, "stdin", _Input(f"apply {'ab' * 6}\n"))
    approval = coordinator.approve(review, binding, GUID_A)
    request = {
        "schema_version": receiver.REQUEST_SCHEMA,
        "operation": "apply",
        **binding,
        "approval": approval,
    }
    assert receiver.validate_request(request)["approval"]["plan_sha256"] == "ab" * 32


class _Input:
    def __init__(self, value: str) -> None:
        self.value = value

    def readline(self) -> str:
        return self.value


def test_container_insights_readback_checks_authoritative_properties() -> None:
    dcr_id = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Insights/dataCollectionRules/d"
    dcra_id = "/subscriptions/s/providers/Microsoft.Insights/dataCollectionRuleAssociations/a"
    documents = {
        dcr_id: {
            "properties": {
                "destinations": {"logAnalytics": [{"workspaceResourceId": WORKSPACE.upper()}]},
                "dataFlows": [{"streams": ["Microsoft-ContainerInsights-Group-Default"]}],
                "dataSources": {
                    "extensions": [
                        {
                            "extensionSettings": {
                                "dataCollectionSettings": {"enableContainerLogV2": True}
                            }
                        }
                    ]
                },
            }
        },
        dcra_id: {"properties": {"dataCollectionRuleId": dcr_id.lower()}},
    }

    def fake(command: tuple[str, ...], _timeout: int) -> str:
        url = command[command.index("--url") + 1]
        return json.dumps(documents[url.split("management.azure.com", 1)[1].split("?", 1)[0]])

    resources = {DCR: dcr_id, DCRA: dcra_id}
    variables = {"log_analytics_workspace_id": WORKSPACE}
    checks = coordinator.check_container_insights(fake, resources, variables, "apply")
    assert all(checks.values())

    documents[dcra_id] = {"properties": {"dataCollectionRuleId": "/other"}}
    assert (
        coordinator.check_container_insights(fake, resources, variables, "apply")[
            "association_bound"
        ]
        is False
    )
    with pytest.raises(coordinator.CoordinatorError, match="lacks"):
        coordinator.check_container_insights(fake, {DCR: dcr_id}, variables, "apply")


def test_unreceipted_claim_blocks_plans_from_every_source_revision(host: Host) -> None:
    first = host.binding()
    review = host.call("plan", first)
    host.configure(plan=_plan((DCRA, ["create"])), state=_state(DCR, DCRA))
    host.call("apply", first, approval=host.approval(first, review["plan_sha256"]))
    (host.operation_dir(first) / "receipt.json").unlink()

    later = {**host.binding(), "source_commit": "b" * 40}
    later.pop("operation_id")
    later["operation_id"] = receiver.operation_id(later)

    assert host.call("plan", later) == {
        "state": "recovery-required",
        "pending_operation_ids": [first["operation_id"]],
    }
    assert host.call("verify", first)["claimed"] is True


def test_failed_apply_is_reported_by_later_plans(host: Host) -> None:
    binding = host.binding()
    review = host.call("plan", binding)
    host.configure(plan=_plan((DCRA, ["create"])), state={}, apply_exit=1, verify_exit=2)
    host.call("apply", binding, approval=host.approval(binding, review["plan_sha256"]))

    assert host.call("plan", binding) == {
        "state": "already-applied",
        "apply_outcome": "apply-failed",
    }


@pytest.mark.parametrize(
    ("operation", "result", "expected"),
    [
        ("plan", {"state": "planned"}, True),
        ("plan", {"state": "already-applied", "apply_outcome": "apply-failed"}, False),
        ("verify", {"state": "verified", "scope_zero_change": False}, False),
        (
            "verify",
            {"state": "verified", "scope_zero_change": True, "independent_readback": {"a": True}},
            True,
        ),
        (
            "apply",
            {
                "state": "verified",
                "apply_outcome": "applied",
                "scope_zero_change": True,
                "independent_readback": {"readback_failed": False, "detail": "x"},
            },
            False,
        ),
        ("apply", {"state": "recovery-required"}, False),
    ],
)
def test_exit_status_requires_applied_converged_and_read_back(
    operation: str, result: dict[str, object], expected: bool
) -> None:
    assert coordinator.succeeded(operation, result) is expected
