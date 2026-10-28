"""Observer apply is approval-bound, dry-run-first, drift-checked, and reversible."""

import base64
import copy
import json
import subprocess
from datetime import timedelta

import pytest
from fdai.delivery.kubernetes_connector_apply import (
    AksRunCommandTransport,
    KubectlTransport,
    KubeResult,
    ObserverApplyApproval,
    activate_observer,
    apply_observer_installation,
    await_first_observation,
    deactivate_observer,
    rollback_observer_installation,
    target_lock,
)
from fdai.delivery.kubernetes_connector_installation import (
    ObserverInstallationInput,
    render_observer_installation,
)
from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment
from fdai_service_contracts.compatibility import canonical_digest

from .test_kubernetes_connector_installation import install_inputs, installation_material
from .test_kubernetes_connector_planning import context
from .test_kubernetes_connector_spool import NOW

UID = "cluster-uid-example"


def merge(base, overlay):
    """Server-side apply merges the applied fields into the live object."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def server_normalized(value):
    """Model the real API server, which omits empty collections and false host flags."""
    if isinstance(value, dict):
        return {
            key: server_normalized(item)
            for key, item in value.items()
            if item not in ([], {})
            and not (key in {"hostNetwork", "hostPID", "hostIPC"} and item is False)
        }
    if isinstance(value, list):
        return [server_normalized(item) for item in value]
    return value


class FakeCluster:
    """An in-memory server that records every request and models server-side defaults."""

    name = "fake"

    def __init__(self, *, uid=UID, namespaces=None, reject=None):
        self.uid, self.reject, self.calls = uid, reject, []
        self.objects = {("namespace", None, "kube-system"): {"metadata": {"uid": uid}}}
        for name, labels in (namespaces or {}).items():
            self.objects[("namespace", None, name)] = {"metadata": {"labels": labels}}

    def effects(self):
        return [
            call
            for call in self.calls
            if call[0][0] in {"apply", "patch", "delete"} and "--dry-run=server" not in call[0]
        ]

    def run(self, args, *, manifest, timeout):
        args = list(args)
        self.calls.append((args, manifest))
        verb = args[0]
        namespace = args[args.index("--namespace") + 1] if "--namespace" in args else None
        if verb == "get":
            live = self.objects.get((args[1], namespace, args[2]))
            return KubeResult(0, json.dumps(live) if live else "")
        if verb == "apply":
            items = json.loads(manifest)["items"]
            if self.reject and any(item["kind"] == self.reject for item in items):
                return KubeResult(1, "admission webhook denied the request")
            if "--dry-run=server" not in args:
                for item in items:
                    live = server_normalized(copy.deepcopy(item))
                    key = (
                        item["kind"].lower(),
                        item["metadata"].get("namespace"),
                        item["metadata"]["name"],
                    )
                    merged = merge(self.objects.get(key, {}), live)
                    merged["metadata"]["uid"] = "server-uid"
                    merged["status"] = {}
                    self.objects[key] = merged
            return KubeResult(0, "serverside-applied")
        if verb == "patch":
            self.objects[("cronjob", namespace, args[2])]["spec"]["suspend"] = json.loads(
                args[args.index("--patch") + 1]
            )["spec"]["suspend"]
            return KubeResult(0, "patched")
        if verb == "delete":
            self.objects.pop((args[1], namespace, args[2]), None)
            return KubeResult(0, "deleted")
        return KubeResult(2, "unsupported")


def build_installation(tmp_path, method):
    directory, digest, target = installation_material(tmp_path)
    inputs = install_inputs(target_ref=target, material_digest=digest, method=method)
    base = context()
    proposal = propose_observer_deployment(
        context(
            requested_method=method,
            target_ref=target,
            observed_at=NOW,
            expires_at=NOW.replace(minute=10),
            facts=tuple(
                fact.model_copy(
                    update={
                        "target_ref": target,
                        "observed_at": NOW,
                        "expires_at": NOW.replace(minute=5),
                    }
                )
                for fact in base.facts
            ),
        ),
        now=NOW,
    )
    rendered = render_observer_installation(inputs, proposal, now=NOW, material_directory=directory)
    return inputs, rendered, directory, tmp_path


@pytest.fixture
def installation(tmp_path):
    return build_installation(tmp_path, "existing_host")


@pytest.mark.parametrize("method", ["managed_host", "run_command"])
def test_every_cluster_method_uses_the_same_governed_flow(tmp_path, method) -> None:
    case = build_installation(tmp_path, method)
    inputs, rendered, *_ = case
    cluster = FakeCluster()
    result = run_apply(case, cluster, approval_for(inputs, rendered))
    assert result["state"] == "installed_suspended"


def test_gitops_method_has_no_cluster_apply_approval(tmp_path) -> None:
    inputs, rendered, *_ = build_installation(tmp_path, "gitops")
    with pytest.raises(ValueError):
        approval_for(inputs, rendered)


def approval_for(inputs, rendered, *, operation="apply", **changes):
    value = {
        "operation": operation,
        "approver_ref": "operator@example.invalid",
        "target_ref": inputs.target_ref,
        "cluster_uid": UID,
        "method": inputs.method,
        "namespace": inputs.namespace,
        "name": inputs.name,
        "inputs_digest": canonical_digest(inputs.model_dump(mode="json")),
        "proposal_digest": rendered["proposal_digest"],
        "manifest_digest": rendered["manifest_digest"],
        "approved_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
        **changes,
    }
    return ObserverApplyApproval.model_validate(value)


def run_apply(installation, cluster, approval, audit=None, **changes):
    inputs, rendered, directory, tmp_path = installation
    records = [] if audit is None else audit
    return apply_observer_installation(
        changes.pop("rendered", rendered),
        inputs,
        approval,
        transport=cluster,
        material_directory=directory,
        cluster_uid=UID,
        lock_directory=tmp_path / "locks",
        audit=records.append,
        now=lambda: NOW + timedelta(seconds=1),
        **changes,
    )


def test_apply_installs_suspended_observer_after_server_dry_run(installation) -> None:
    inputs, rendered, *_ = installation
    cluster, audit = FakeCluster(), []
    result = run_apply(installation, cluster, approval_for(inputs, rendered), audit)
    assert result["state"] == "installed_suspended"
    assert result["activation_required"] is True and result["operational_success"] is False
    assert [item["kind"] for item in result["resources"]] == [
        item["kind"] for item in rendered["documents"]
    ]
    verbs = [("dry" if "--dry-run=server" in call[0] else call[0][0]) for call in cluster.calls]
    assert verbs.index("dry") < verbs.index("apply")
    for call, _ in cluster.calls:
        assert "--force-conflicts" not in call
        if call[0] == "apply":
            assert "--server-side" in call and "--field-manager=fdai-observer-install" in call
    assert cluster.objects[("cronjob", inputs.namespace, inputs.name)]["spec"]["suspend"] is True
    secret = cluster.objects[("secret", inputs.namespace, inputs.material_secret)]
    assert set(secret["data"]) == {
        "config.json",
        "registrations.json",
        "ca.pem",
        "client.pem",
        "client.key",
    }
    assert [(item["phase"], item["step"]) for item in audit] == [
        ("intent", "dry-run"),
        ("result", "dry-run"),
        ("intent", "apply"),
        ("result", "apply"),
    ]
    dumped = json.dumps(audit) + json.dumps(result)
    assert base64.b64encode(b"synthetic").decode() not in dumped
    assert all(item["executor"] == "fake" for item in audit)


def test_without_approval_only_dry_run_runs_and_nothing_is_changed(installation) -> None:
    cluster = FakeCluster(
        namespaces={"fdai-observers": {"app.kubernetes.io/managed-by": "fdai-observer-install"}}
    )
    result = run_apply(installation, cluster, None)
    assert result["state"] == "dry_run_passed" and result["dry_run_scope"] == "complete"
    assert cluster.effects() == []


def test_missing_namespace_is_created_then_the_rest_is_dry_run_before_apply(installation) -> None:
    inputs, rendered, *_ = installation
    cluster = FakeCluster()
    assert run_apply(installation, cluster, None)["dry_run_scope"] == "namespace_only"
    cluster.calls.clear()
    run_apply(installation, cluster, approval_for(inputs, rendered))
    sequence = [
        ("dry" if "--dry-run=server" in call[0] else "live", len(json.loads(call[1])["items"]))
        for call in cluster.calls
        if call[0][0] == "apply"
    ]
    assert sequence == [
        ("dry", 1),
        ("live", 1),
        ("dry", 6),
        ("dry", 1),
        ("live", 1),
        ("live", 6),
    ]
    labels = cluster.objects[("namespace", None, inputs.namespace)]["metadata"]["labels"]
    assert labels["pod-security.kubernetes.io/enforce"] == "restricted"


@pytest.mark.parametrize(
    "change",
    [
        {"manifest_digest": "sha256:" + "0" * 64},
        {"proposal_digest": "sha256:" + "0" * 64},
        {"target_ref": "another-cluster"},
        {"namespace": "elsewhere"},
        {"inputs_digest": "sha256:" + "0" * 64},
        {"operation": "activate"},
        {"approved_at": NOW - timedelta(minutes=20), "expires_at": NOW - timedelta(minutes=10)},
    ],
)
def test_approval_must_bind_exact_plan_target_and_time(installation, change) -> None:
    inputs, rendered, *_ = installation
    cluster = FakeCluster()
    with pytest.raises(ValueError, match="approval"):
        run_apply(installation, cluster, approval_for(inputs, rendered, **change))
    assert cluster.calls == []


def test_approval_cannot_outlive_thirty_minutes_or_omit_the_manifest(installation) -> None:
    inputs, rendered, *_ = installation
    with pytest.raises(ValueError):
        approval_for(inputs, rendered, expires_at=NOW + timedelta(hours=2))
    with pytest.raises(ValueError):
        approval_for(inputs, rendered, manifest_digest=None)
    assert approval_for(
        inputs, rendered, operation="rollback", manifest_digest=None, proposal_digest=None
    )


@pytest.mark.parametrize(
    "case", ["digest", "extra", "privileged", "secret-read", "suspend", "draft", "namespace"]
)
def test_tampered_or_draft_manifest_is_refused_before_any_cluster_call(installation, case) -> None:
    inputs, rendered, *_ = installation
    value = copy.deepcopy(rendered)
    documents = {item["kind"]: item for item in value["documents"]}
    pod = documents["CronJob"]["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    if case == "extra":
        value["documents"].append(
            {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": inputs.name}}
        )
    elif case == "privileged":
        pod["containers"][0]["securityContext"]["privileged"] = True
    elif case == "secret-read":
        documents["ClusterRole"]["rules"][0]["resources"].append("secrets")
    elif case == "suspend":
        documents["CronJob"]["spec"]["suspend"] = False
    elif case == "draft":
        value["missing"] = ["admission"]
        value["recommended"] = False
    elif case == "namespace":
        documents["ServiceAccount"]["metadata"]["namespace"] = "kube-system"
    if case not in {"digest", "draft"}:
        value["manifest_digest"] = canonical_digest(value["documents"])
    if case == "digest":
        value["manifest_digest"] = "sha256:" + "0" * 64
    cluster = FakeCluster()
    with pytest.raises(ValueError):
        run_apply(installation, cluster, approval_for(inputs, rendered), rendered=value)
    assert cluster.calls == []


def test_wrong_cluster_identity_changes_nothing(installation) -> None:
    inputs, rendered, *_ = installation
    cluster = FakeCluster(uid="cluster-uid-other")
    with pytest.raises(ValueError, match="not the approved target"):
        run_apply(installation, cluster, approval_for(inputs, rendered))
    assert cluster.effects() == []


def test_foreign_namespace_is_never_adopted(installation) -> None:
    inputs, rendered, *_ = installation
    cluster = FakeCluster(namespaces={"fdai-observers": {"team": "other"}})
    with pytest.raises(ValueError, match="not owned"):
        run_apply(installation, cluster, approval_for(inputs, rendered))
    assert cluster.effects() == []


def test_rejected_dry_run_stops_before_any_effect(installation) -> None:
    inputs, rendered, *_ = installation
    cluster = FakeCluster(
        namespaces={"fdai-observers": {"app.kubernetes.io/managed-by": "fdai-observer-install"}},
        reject="CronJob",
    )
    with pytest.raises(ValueError, match="dry-run was rejected.*webhook denied"):
        run_apply(installation, cluster, approval_for(inputs, rendered))
    assert cluster.effects() == []


def test_secret_step_failure_never_echoes_cluster_output(installation) -> None:
    inputs, rendered, *_ = installation
    cluster = FakeCluster(
        namespaces={"fdai-observers": {"app.kubernetes.io/managed-by": "fdai-observer-install"}},
        reject="Secret",
    )
    with pytest.raises(ValueError) as caught:
        run_apply(installation, cluster, approval_for(inputs, rendered))
    assert "webhook" not in str(caught.value) and "exit 1" in str(caught.value)


def test_drift_after_apply_is_reported_as_unknown_outcome(installation) -> None:
    inputs, rendered, *_ = installation

    class Drifting(FakeCluster):
        def run(self, args, *, manifest, timeout):
            result = super().run(args, manifest=manifest, timeout=timeout)
            if (
                args[0] == "apply"
                and "--dry-run=server" not in args
                and manifest
                and b"CronJob" in manifest
            ):
                self.objects[("cronjob", inputs.namespace, inputs.name)]["spec"]["suspend"] = False
            return result

    audit = []
    with pytest.raises(ValueError, match="outcome is unknown"):
        run_apply(installation, Drifting(), approval_for(inputs, rendered), audit)
    assert audit[-1]["outcome"] == "unknown"


def test_audit_failure_before_effect_blocks_the_change(installation) -> None:
    inputs, rendered, directory, tmp_path = installation
    cluster = FakeCluster()

    def broken(record):
        raise OSError("audit store unavailable")

    with pytest.raises(OSError):
        apply_observer_installation(
            rendered,
            inputs,
            approval_for(inputs, rendered),
            transport=cluster,
            material_directory=directory,
            cluster_uid=UID,
            lock_directory=tmp_path / "locks",
            audit=broken,
            now=lambda: NOW,
        )
    assert cluster.effects() == []


def test_same_target_cannot_be_operated_concurrently(installation) -> None:
    inputs, rendered, _, tmp_path = installation
    with target_lock(tmp_path / "locks", f"{inputs.target_ref}/{inputs.namespace}/{inputs.name}"):
        with pytest.raises(ValueError, match="holds this target"):
            run_apply(installation, FakeCluster(), approval_for(inputs, rendered))


def test_activation_needs_its_own_approval_and_an_unchanged_installation(installation) -> None:
    inputs, rendered, _, tmp_path = installation
    cluster = FakeCluster()
    run_apply(installation, cluster, approval_for(inputs, rendered))
    kwargs = dict(
        transport=cluster, lock_directory=tmp_path / "locks", audit=lambda _: None, now=lambda: NOW
    )
    with pytest.raises(ValueError, match="approval"):
        activate_observer(rendered, inputs, approval_for(inputs, rendered), **kwargs)
    live = cluster.objects[("clusterrole", None, inputs.name)]
    live["rules"].append({"apiGroups": [""], "resources": ["secrets"], "verbs": ["get"]})
    with pytest.raises(ValueError, match="differs from the approved plan"):
        activate_observer(
            rendered, inputs, approval_for(inputs, rendered, operation="activate"), **kwargs
        )
    assert cluster.objects[("cronjob", inputs.namespace, inputs.name)]["spec"]["suspend"] is True
    live["rules"].pop()
    result = activate_observer(
        rendered, inputs, approval_for(inputs, rendered, operation="activate"), **kwargs
    )
    assert result["state"] == "activated_pending_observation"
    assert result["operational_success"] is False and result["observation_required"] is True
    assert cluster.objects[("cronjob", inputs.namespace, inputs.name)]["spec"]["suspend"] is False


def test_rollback_removes_only_owned_resources_and_keeps_the_namespace(installation) -> None:
    inputs, rendered, _, tmp_path = installation
    cluster = FakeCluster()
    run_apply(installation, cluster, approval_for(inputs, rendered))
    approval = approval_for(
        inputs, rendered, operation="rollback", manifest_digest=None, proposal_digest=None
    )
    kwargs = dict(
        transport=cluster, lock_directory=tmp_path / "locks", audit=lambda _: None, now=lambda: NOW
    )
    result = rollback_observer_installation(inputs, approval, **kwargs)
    assert result["removed"] == [
        "CronJob",
        "NetworkPolicy",
        "ClusterRoleBinding",
        "ClusterRole",
        "PersistentVolumeClaim",
        "ServiceAccount",
        "Secret",
    ]
    assert ("namespace", None, inputs.namespace) in cluster.objects
    assert not [key for key in cluster.objects if key[2] in {inputs.name, inputs.material_secret}]
    assert rollback_observer_installation(inputs, approval, **kwargs)["removed"] == []


def test_rollback_stops_at_a_resource_this_observer_does_not_own(installation) -> None:
    inputs, rendered, _, tmp_path = installation
    cluster = FakeCluster()
    run_apply(installation, cluster, approval_for(inputs, rendered))
    cluster.objects[("clusterrole", None, inputs.name)]["metadata"]["labels"] = {}
    approval = approval_for(
        inputs, rendered, operation="rollback", manifest_digest=None, proposal_digest=None
    )
    with pytest.raises(ValueError, match="not owned"):
        rollback_observer_installation(
            inputs,
            approval,
            transport=cluster,
            lock_directory=tmp_path / "locks",
            audit=lambda _: None,
            now=lambda: NOW,
        )
    assert ("clusterrole", None, inputs.name) in cluster.objects


def test_kubectl_transport_uses_stdin_without_a_shell(tmp_path, monkeypatch) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic")
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, b"ok", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = KubectlTransport(kubeconfig=kubeconfig, tools=tmp_path).run(
        ["apply", "--filename", "@manifest"], manifest=b"{}", timeout=5
    )
    assert result == KubeResult(0, "ok")
    assert seen["command"][-2:] == ["--filename", "-"] and seen["input"] == b"{}"
    assert "shell" not in seen and seen["env"]["PATH"].startswith(str(tmp_path))
    with pytest.raises(ValueError):
        KubectlTransport(kubeconfig=tmp_path / "missing")


def test_run_command_transport_ships_the_manifest_as_a_private_file(tmp_path) -> None:
    seen = {}

    def fake_run(vector, **kwargs):
        index = vector.index("--file")
        path = vector[index + 1]
        seen.update(
            vector=vector,
            mode=oct(__import__("os").stat(path).st_mode & 0o777),
            body=open(path, "rb").read(),
        )
        return subprocess.CompletedProcess(
            vector, 0, json.dumps({"exitCode": 0, "logs": "done"}), ""
        )

    transport = AksRunCommandTransport(
        subscription_id="00000000-0000-0000-0000-000000000000",
        resource_group="rg-example",
        cluster_name="aks-example",
        run=fake_run,
    )
    result = transport.run(["apply", "--filename", "@manifest"], manifest=b"{}", timeout=5)
    assert result == KubeResult(0, "done")
    assert seen["mode"] == "0o600" and seen["body"] == b"{}"
    assert (
        seen["vector"][seen["vector"].index("--command") + 1]
        == "kubectl apply --filename manifest.json"
    )


def test_run_command_transport_reports_unavailability_and_rejects_bad_identity() -> None:
    failing = AksRunCommandTransport(
        subscription_id="00000000-0000-0000-0000-000000000000",
        resource_group="rg-example",
        cluster_name="aks-example",
        run=lambda vector, **kwargs: subprocess.CompletedProcess(
            vector, 1, "", "command invoke disabled"
        ),
    )
    with pytest.raises(ValueError, match="Run Command is unavailable.*disabled"):
        failing.run(["get", "namespace", "kube-system"], manifest=None, timeout=5)
    for bad in ({"subscription_id": "x"}, {"resource_group": "--bad rg"}, {"cluster_name": "-x"}):
        with pytest.raises(ValueError):
            AksRunCommandTransport(
                **{
                    "subscription_id": "00000000-0000-0000-0000-000000000000",
                    "resource_group": "rg-example",
                    "cluster_name": "aks-example",
                    **bad,
                }
            )


async def test_first_observation_wait_is_bounded() -> None:
    clock = {"now": 0.0}
    attempts = []

    async def observing(target):
        attempts.append(target)
        return len(attempts) == 3

    async def sleep(seconds):
        clock["now"] += seconds

    assert await await_first_observation(
        observing,
        "cluster-example",
        timeout_s=60,
        interval_s=10,
        sleep=sleep,
        monotonic=lambda: clock["now"],
    )
    assert len(attempts) == 3

    async def never(_target):
        return False

    clock["now"] = 0.0
    assert not await await_first_observation(
        never,
        "cluster-example",
        timeout_s=25,
        interval_s=10,
        sleep=sleep,
        monotonic=lambda: clock["now"],
    )
    assert clock["now"] <= 25


def test_installation_input_model_is_unchanged_for_apply() -> None:
    assert ObserverInstallationInput.model_validate_json(install_inputs().model_dump_json())


def test_run_command_null_logs_are_empty_output_not_the_text_none() -> None:
    transport = AksRunCommandTransport(
        subscription_id="00000000-0000-0000-0000-000000000000",
        resource_group="rg-example",
        cluster_name="aks-example",
        run=lambda vector, **kwargs: subprocess.CompletedProcess(
            vector, 0, json.dumps({"exitCode": 0, "logs": None}), ""
        ),
    )
    assert transport.run(["get", "namespace", "x"], manifest=None, timeout=5) == KubeResult(0, "")


def test_server_omitted_defaults_do_not_count_as_drift_but_security_fields_still_do(
    installation,
) -> None:
    inputs, rendered, *_ = installation
    cluster = FakeCluster()
    run_apply(installation, cluster, approval_for(inputs, rendered))
    policy = cluster.objects[("networkpolicy", inputs.namespace, inputs.name)]["spec"]
    pod = cluster.objects[("cronjob", inputs.namespace, inputs.name)]["spec"]["jobTemplate"][
        "spec"
    ]["template"]["spec"]
    assert "ingress" not in policy and "hostNetwork" not in pod
    kwargs = {
        "transport": cluster,
        "lock_directory": installation[3] / "locks",
        "audit": lambda _: None,
        "now": lambda: NOW,
    }
    activation = approval_for(inputs, rendered, operation="activate")
    pod["hostNetwork"] = True
    with pytest.raises(ValueError, match="CronJob"):
        activate_observer(rendered, inputs, activation, **kwargs)
    del pod["hostNetwork"]
    pod["containers"][0]["securityContext"].pop("allowPrivilegeEscalation")
    with pytest.raises(ValueError, match="CronJob"):
        activate_observer(rendered, inputs, activation, **kwargs)


def test_activation_and_deactivation_use_a_state_manager_limited_to_the_suspend_field(
    installation,
) -> None:
    inputs, rendered, _, tmp_path = installation
    cluster = FakeCluster()
    run_apply(installation, cluster, approval_for(inputs, rendered))
    kwargs = {
        "transport": cluster,
        "lock_directory": tmp_path / "locks",
        "audit": lambda _: None,
        "now": lambda: NOW,
    }
    cluster.calls.clear()
    activate_observer(
        rendered, inputs, approval_for(inputs, rendered, operation="activate"), **kwargs
    )
    stop = approval_for(
        inputs, rendered, operation="deactivate", manifest_digest=None, proposal_digest=None
    )
    result = deactivate_observer(inputs, stop, **kwargs)
    assert result["state"] == "installed_suspended"
    assert not [call for call, _ in cluster.calls if call[0] == "patch"]
    toggles = [call for call, body in cluster.calls if call[0] == "apply"]
    assert len(toggles) == 2
    assert all(
        {"--field-manager=fdai-observer-state", "--force-conflicts", "--validate=false"}
        <= set(call)
        for call in toggles
    )
    assert [
        json.loads(body)["items"][0]["spec"] for call, body in cluster.calls if call[0] == "apply"
    ] == [{"suspend": False}, {"suspend": True}]
    assert cluster.objects[("cronjob", inputs.namespace, inputs.name)]["spec"]["suspend"] is True
    # A later full apply of the same plan converges without a field-ownership conflict.
    run_apply(installation, cluster, approval_for(inputs, rendered))


def test_deactivation_needs_its_own_target_bound_approval(installation) -> None:
    inputs, rendered, _, tmp_path = installation
    kwargs = {
        "transport": FakeCluster(),
        "lock_directory": tmp_path / "locks",
        "audit": lambda _: None,
        "now": lambda: NOW,
    }
    wrong = approval_for(
        inputs, rendered, operation="rollback", manifest_digest=None, proposal_digest=None
    )
    with pytest.raises(ValueError, match="approval"):
        deactivate_observer(inputs, wrong, **kwargs)


def test_failure_detail_shows_the_error_not_the_successful_lines() -> None:
    from fdai.delivery.kubernetes_connector_apply import _checked

    output = (
        "serviceaccount/a serverside-applied\n"
        "clusterrole/b serverside-applied\n"
        "Error: conflict on .spec.suspend"
    )
    with pytest.raises(ValueError, match="conflict on .spec.suspend") as caught:
        _checked(KubeResult(1, output), "apply failed")
    assert "serviceaccount" not in str(caught.value)


@pytest.mark.parametrize(("verb", "calls", "ok"), [("get", 2, True), ("apply", 1, False)])
def test_run_command_retries_an_unparseable_read_once_and_never_a_write(verb, calls, ok) -> None:
    seen = []

    def flaky(vector, **kwargs):
        seen.append(vector)
        if len(seen) == 1:
            return subprocess.CompletedProcess(vector, 1, "", "deserialization warning")
        return subprocess.CompletedProcess(vector, 0, json.dumps({"exitCode": 0, "logs": "x"}), "")

    transport = AksRunCommandTransport(
        subscription_id="00000000-0000-0000-0000-000000000000",
        resource_group="rg-example",
        cluster_name="aks-example",
        run=flaky,
    )
    if ok:
        assert transport.run([verb, "namespace", "x"], manifest=None, timeout=5).output == "x"
    else:
        with pytest.raises(ValueError, match="unavailable"):
            transport.run([verb, "--filename", "@manifest"], manifest=b"{}", timeout=5)
    assert len(seen) == calls


def test_run_command_does_not_retry_a_timeout() -> None:
    seen = []

    def slow(vector, **kwargs):
        seen.append(vector)
        raise subprocess.TimeoutExpired(vector, 5)

    transport = AksRunCommandTransport(
        subscription_id="00000000-0000-0000-0000-000000000000",
        resource_group="rg-example",
        cluster_name="aks-example",
        run=slow,
    )
    with pytest.raises(ValueError, match="outcome is unknown"):
        transport.run(["get", "namespace", "x"], manifest=None, timeout=5)
    assert len(seen) == 1


def test_applying_to_an_active_observer_says_to_deactivate_first(installation) -> None:
    inputs, rendered, _, tmp_path = installation
    cluster = FakeCluster()
    run_apply(installation, cluster, approval_for(inputs, rendered))
    kwargs = {
        "transport": cluster,
        "lock_directory": tmp_path / "locks",
        "audit": lambda _: None,
        "now": lambda: NOW,
    }
    activate_observer(
        rendered, inputs, approval_for(inputs, rendered, operation="activate"), **kwargs
    )
    cluster.calls.clear()
    with pytest.raises(ValueError, match="deactivate before applying"):
        run_apply(installation, cluster, approval_for(inputs, rendered))
    assert cluster.effects() == []
    stop = approval_for(
        inputs, rendered, operation="deactivate", manifest_digest=None, proposal_digest=None
    )
    deactivate_observer(inputs, stop, **kwargs)
    assert (
        run_apply(installation, cluster, approval_for(inputs, rendered))["state"]
        == "installed_suspended"
    )
