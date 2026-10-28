"""Smoke verification classifies delivery precisely; stream retirement preserves evidence."""

import json

import pytest
from fdai.delivery.kubernetes_connector_apply import KubeResult
from fdai.delivery.kubernetes_connector_lifecycle import (
    _RETIRE_SCRIPT,
    retire_observer_stream,
    verify_observer,
)

from .test_kubernetes_connector_apply import (
    UID,
    FakeCluster,
    approval_for,
    build_installation,
    run_apply,
)
from .test_kubernetes_connector_spool import NOW


class SmokeCluster(FakeCluster):
    """Add Job, Pod and log behavior on top of the in-memory server."""

    def __init__(self, *, job=None, pods=(), logs="", pod_phase="Succeeded", **kwargs):
        super().__init__(**kwargs)
        self.job, self.pods, self.logs = job, list(pods), logs
        self.pod_phase, self.created, self.deleted = pod_phase, [], []
        self.polls = 0

    def run(self, args, *, manifest, timeout):
        args = list(args)
        if args[0] == "create" and args[1] == "job":
            self.created.append(args[2])
            return KubeResult(0, f"job.batch/{args[2]} created")
        if args[0] == "create" and "--filename" in args:
            self.created.append(json.loads(manifest)["items"][0])
            name = self.created[-1]["metadata"]["name"]
            self.objects[("pod", self.created[-1]["metadata"]["namespace"], name)] = {
                "metadata": {"name": name},
                "status": {"phase": self.pod_phase},
            }
            return KubeResult(0, "pod created")
        if args[0] == "get" and args[1] == "job,pod":
            self.polls += 1
            items = ([{"kind": "Job", **self.job}] if self.job else []) + [
                {"kind": "Pod", **pod} for pod in self.pods
            ]
            return KubeResult(0, json.dumps({"items": items}))
        if args[0] == "get" and args[1] == "jobs":
            return KubeResult(0, json.dumps({"items": self.job_list}))
        if args[0] == "logs":
            return KubeResult(0, self.logs)
        if args[0] == "delete" and args[1] in {"job", "pod"}:
            self.deleted.append((args[1], args[2]))
            self.objects.pop((args[1], None, args[2]), None)
            return KubeResult(0, "deleted")
        return super().run(args, manifest=manifest, timeout=timeout)

    job_list: list = []


def kwargs_for(tmp_path, **extra):
    clock = {"now": 0.0}

    def sleep(seconds):
        clock["now"] += seconds

    return {
        "lock_directory": tmp_path / "locks",
        "audit": extra.pop("audit", lambda _: None),
        "now": lambda: NOW,
        "sleep": sleep,
        "monotonic": lambda: clock["now"],
        **extra,
    }


def installed(tmp_path, method="run_command"):
    case = build_installation(tmp_path, method)
    cluster = SmokeCluster()
    inputs, rendered, *_ = case
    run_apply(case, cluster, approval_for(inputs, rendered))
    return case, cluster


def pull_failure(reason):
    return {
        "status": {
            "initContainerStatuses": [{"state": {"waiting": {"reason": reason}}}],
        }
    }


@pytest.mark.parametrize(
    ("job", "pods", "logs", "state"),
    [
        (
            {"status": {"succeeded": 1}},
            [],
            '{"staged": 1}\n{"status": "accepted", "sequence": 3}',
            "delivered",
        ),
        ({"status": {"succeeded": 1}}, [], '{"status": "duplicate"}', "delivered"),
        ({"status": {"succeeded": 1}}, [], "nothing useful", "completed_without_delivery"),
        (
            {"status": {"failed": 1}},
            [],
            '{"status": "unavailable", "error_type": "ConnectorSpoolError"}',
            "job_failed",
        ),
        ({"status": {}}, [pull_failure("ImagePullBackOff")], "", "image_pull_failed"),
        ({"status": {}}, [pull_failure("ErrImagePull")], "", "image_pull_failed"),
    ],
)
def test_smoke_job_is_classified_and_always_removed(tmp_path, job, pods, logs, state) -> None:
    case, base = installed(tmp_path)
    inputs, rendered, _, directory = case
    cluster = SmokeCluster(job=job, pods=pods, logs=logs)
    cluster.objects.update(base.objects)
    audit = []
    result = verify_observer(
        rendered,
        inputs,
        approval_for(inputs, rendered, operation="verify"),
        transport=cluster,
        **kwargs_for(directory, audit=audit.append),
    )
    assert result["state"] == state
    assert result["operational_success"] is False and result["observation_required"] is True
    assert cluster.created[0].startswith(inputs.name + "-verify-")
    assert ("job", cluster.created[0]) in cluster.deleted
    assert [(item["phase"], item["step"]) for item in audit] == [
        ("intent", "smoke"),
        ("result", "smoke"),
    ]
    assert audit[-1]["outcome"] == state


def test_smoke_reports_error_type_only_not_log_content(tmp_path) -> None:
    case, base = installed(tmp_path)
    inputs, rendered, _, directory = case
    cluster = SmokeCluster(
        job={"status": {"failed": 1}},
        logs='{"status": "unavailable", "reason": "x", "error_type": "ConnectorSpoolError"}\n',
    )
    cluster.objects.update(base.objects)
    result = verify_observer(
        rendered,
        inputs,
        approval_for(inputs, rendered, operation="verify"),
        transport=cluster,
        **kwargs_for(directory),
    )
    assert result["detail"] == {
        "report": {"status": "unavailable", "reason": "x", "error_type": "ConnectorSpoolError"}
    }


def test_smoke_that_never_finishes_is_not_finished_and_bounded(tmp_path) -> None:
    case, base = installed(tmp_path)
    inputs, rendered, _, directory = case
    cluster = SmokeCluster(job={"status": {"active": 1}})
    cluster.objects.update(base.objects)
    result = verify_observer(
        rendered,
        inputs,
        approval_for(inputs, rendered, operation="verify"),
        transport=cluster,
        timeout_seconds=30,
        interval_seconds=10,
        **kwargs_for(directory),
    )
    assert result["state"] == "not_finished"
    assert cluster.polls <= 4 and ("job", cluster.created[0]) in cluster.deleted


def test_smoke_needs_a_matching_approval_and_an_unchanged_installation(tmp_path) -> None:
    case, base = installed(tmp_path)
    inputs, rendered, _, directory = case
    cluster = SmokeCluster(job={"status": {"succeeded": 1}})
    cluster.objects.update(base.objects)
    with pytest.raises(ValueError, match="approval"):
        verify_observer(
            rendered,
            inputs,
            approval_for(inputs, rendered, operation="activate"),
            transport=cluster,
            **kwargs_for(directory),
        )
    cluster.objects[("clusterrole", None, inputs.name)]["rules"].append(
        {"apiGroups": [""], "resources": ["secrets"], "verbs": ["get"]}
    )
    with pytest.raises(ValueError, match="differs from the approved plan"):
        verify_observer(
            rendered,
            inputs,
            approval_for(inputs, rendered, operation="verify"),
            transport=cluster,
            **kwargs_for(directory),
        )
    assert cluster.created == []


def test_smoke_refuses_the_wrong_cluster(tmp_path) -> None:
    case, base = installed(tmp_path)
    inputs, rendered, _, directory = case
    cluster = SmokeCluster(uid="other-cluster")
    with pytest.raises(ValueError, match="not the approved target"):
        verify_observer(
            rendered,
            inputs,
            approval_for(inputs, rendered, operation="verify"),
            transport=cluster,
            **kwargs_for(directory),
        )
    assert cluster.created == []


def stop_approval(inputs, rendered):
    return approval_for(
        inputs, rendered, operation="recover", manifest_digest=None, proposal_digest=None
    )


def test_retire_suspends_removes_owned_jobs_and_sets_the_spool_aside(tmp_path) -> None:
    case, base = installed(tmp_path)
    inputs, rendered, _, directory = case
    cluster = SmokeCluster(pod_phase="Succeeded", logs="retired 1")
    cluster.objects.update(base.objects)
    cluster.job_list = [
        {
            "metadata": {
                "name": "mine-1",
                "ownerReferences": [{"kind": "CronJob", "name": inputs.name}],
            }
        },
        {
            "metadata": {
                "name": "foreign",
                "ownerReferences": [{"kind": "CronJob", "name": "someone-else"}],
            }
        },
        {"metadata": {"name": "bare"}},
    ]
    audit = []
    result = retire_observer_stream(
        inputs,
        stop_approval(inputs, rendered),
        transport=cluster,
        **kwargs_for(directory, audit=audit.append),
    )
    assert result["state"] == "stream_retired" and result["removed_jobs"] == 1
    assert [name for kind, name in cluster.deleted if kind == "job"] == ["mine-1"]
    assert cluster.objects[("cronjob", inputs.namespace, inputs.name)]["spec"]["suspend"] is True
    pod = next(item for item in cluster.created if isinstance(item, dict))
    spec = pod["spec"]
    container = spec["containers"][0]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["image"] == inputs.image and spec["automountServiceAccountToken"] is False
    assert spec["volumes"][0]["persistentVolumeClaim"]["claimName"] == inputs.name
    assert ("pod", pod["metadata"]["name"]) in cluster.deleted
    assert [(item["phase"], item["outcome"]) for item in audit if "outcome" in item] == [
        ("result", "retired")
    ]


def test_retire_script_renames_the_database_and_never_deletes_it(tmp_path) -> None:
    import subprocess
    import sys

    spool = tmp_path / "snapshots"
    spool.mkdir()
    for name in ("snapshots.sqlite3", "snapshots.sqlite3-journal", "other.txt"):
        (spool / name).write_bytes(b"synthetic")
    script = _RETIRE_SCRIPT.replace("/spool/snapshots", str(spool))
    subprocess.run([sys.executable, "-c", script], check=True)  # noqa: S603
    names = sorted(path.name for path in spool.iterdir())
    assert "snapshots.sqlite3" not in names and "other.txt" in names
    assert sum(".retired-" in name for name in names) == 2
    assert all((spool / name).read_bytes() == b"synthetic" for name in names)
    subprocess.run([sys.executable, "-c", script], check=True)  # noqa: S603
    assert sum(".retired-" in path.name for path in spool.iterdir()) == 2


def test_failed_retirement_keeps_the_observer_suspended_and_reports_unknown(tmp_path) -> None:
    case, base = installed(tmp_path)
    inputs, rendered, _, directory = case
    cluster = SmokeCluster(pod_phase="Failed", logs="Traceback permission denied")
    cluster.objects.update(base.objects)
    audit = []
    with pytest.raises(ValueError, match="spool retirement failed.*stays suspended"):
        retire_observer_stream(
            inputs,
            stop_approval(inputs, rendered),
            transport=cluster,
            **kwargs_for(directory, audit=audit.append),
        )
    assert cluster.objects[("cronjob", inputs.namespace, inputs.name)]["spec"]["suspend"] is True
    assert audit[-1]["outcome"] == "unknown"
    assert any(kind == "pod" for kind, _ in cluster.deleted)


def test_retirement_without_an_installation_or_approval_changes_nothing(tmp_path) -> None:
    case = build_installation(tmp_path, "run_command")
    inputs, rendered, _, directory = case
    cluster = SmokeCluster()
    with pytest.raises(ValueError, match="not installed"):
        retire_observer_stream(
            inputs, stop_approval(inputs, rendered), transport=cluster, **kwargs_for(directory)
        )
    wrong = approval_for(
        inputs, rendered, operation="deactivate", manifest_digest=None, proposal_digest=None
    )
    with pytest.raises(ValueError, match="approval"):
        retire_observer_stream(inputs, wrong, transport=cluster, **kwargs_for(directory))
    assert cluster.effects() == [] and UID


def test_pull_failure_while_retiring_is_reported_with_the_remedy(tmp_path) -> None:
    case, base = installed(tmp_path)
    inputs, rendered, _, directory = case

    class Pulling(SmokeCluster):
        def run(self, args, *, manifest, timeout):
            result = super().run(args, manifest=manifest, timeout=timeout)
            if args[0] == "get" and args[1] == "pod" and result.output:
                pod = json.loads(result.output)
                pod["status"] = {
                    "phase": "Pending",
                    "containerStatuses": [{"state": {"waiting": {"reason": "ImagePullBackOff"}}}],
                }
                return KubeResult(0, json.dumps(pod))
            return result

    cluster = Pulling()
    cluster.objects.update(base.objects)
    with pytest.raises(ValueError, match="grant registry access"):
        retire_observer_stream(
            inputs, stop_approval(inputs, rendered), transport=cluster, **kwargs_for(directory)
        )
