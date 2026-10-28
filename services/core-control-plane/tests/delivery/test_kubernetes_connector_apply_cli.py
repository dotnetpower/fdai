"""The apply command line binds approval to the printed digest and honors the pinned method."""

import argparse
import json
import stat
from datetime import timedelta

import pytest
from fdai.delivery import kubernetes_connector_apply_cli as cli
from fdai.delivery.kubernetes_connector_apply import AksRunCommandTransport, KubectlTransport

from .test_kubernetes_connector_apply import UID, FakeCluster, build_installation
from .test_kubernetes_connector_spool import NOW

LATER = NOW + timedelta(seconds=1)


def private(path, content):
    path.write_text(content)
    path.chmod(0o600)
    return path


def arguments(tmp_path, operation, case, **changes):
    inputs, rendered, directory, _ = case
    proposal = tmp_path / "proposal.json"
    values = {
        "operation": operation,
        "inputs": private(tmp_path / "inputs.json", inputs.model_dump_json()),
        "proposal": proposal,
        "material_directory": directory,
        "cluster_uid": UID,
        "approver": "operator@example.invalid",
        "approve_manifest_digest": None,
        "approve_target_ref": None,
        "audit_file": tmp_path / "audit.jsonl",
        "lock_directory": tmp_path / "locks",
        "output_directory": None,
        "kubeconfig": None,
        "tools_directory": None,
        "subscription_id": None,
        "resource_group": None,
        "cluster_name": None,
        "timeout_seconds": 1.0,
        **changes,
    }
    return argparse.Namespace(**values)


@pytest.fixture
def case(tmp_path, monkeypatch):
    built = build_installation(tmp_path, "existing_host")
    cluster = FakeCluster(
        namespaces={"fdai-observers": {"app.kubernetes.io/managed-by": "fdai-observer-install"}}
    )
    monkeypatch.setattr(cli, "_transport", lambda *_: cluster)
    return built, cluster


def write_proposal(tmp_path, tmp):
    from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment

    from .test_kubernetes_connector_planning import context

    inputs = tmp[0]
    base = context()
    proposal = propose_observer_deployment(
        context(
            requested_method=inputs.method,
            target_ref=inputs.target_ref,
            observed_at=NOW,
            expires_at=NOW.replace(minute=10),
            facts=tuple(
                fact.model_copy(
                    update={
                        "target_ref": inputs.target_ref,
                        "observed_at": NOW,
                        "expires_at": NOW.replace(minute=5),
                    }
                )
                for fact in base.facts
            ),
        ),
        now=NOW,
    )
    return private(tmp_path / "proposal.json", proposal.model_dump_json())


def test_first_run_is_a_dry_run_that_prints_the_digest_to_approve(tmp_path, case) -> None:
    built, cluster = case
    write_proposal(tmp_path, built)
    result = cli.run(arguments(tmp_path, "apply", built), now=LATER)
    assert result["state"] == "dry_run_passed"
    assert result["manifest_digest"] == built[1]["manifest_digest"]
    assert cluster.effects() == []
    audit = tmp_path / "audit.jsonl"
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600
    assert [json.loads(line)["phase"] for line in audit.read_text().splitlines()] == [
        "intent",
        "result",
    ]


def test_apply_then_activate_then_rollback_with_explicit_approvals(tmp_path, case) -> None:
    built, cluster = case
    write_proposal(tmp_path, built)
    digest = built[1]["manifest_digest"]
    with pytest.raises(ValueError, match="differs from the current"):
        cli.run(
            arguments(tmp_path, "apply", built, approve_manifest_digest="sha256:" + "0" * 64),
            now=LATER,
        )
    installed = cli.run(
        arguments(tmp_path, "apply", built, approve_manifest_digest=digest), now=LATER
    )
    assert installed["state"] == "installed_suspended"
    with pytest.raises(ValueError, match="requires --approve-manifest-digest"):
        cli.run(arguments(tmp_path, "activate", built), now=LATER)
    active = cli.run(
        arguments(tmp_path, "activate", built, approve_manifest_digest=digest), now=LATER
    )
    assert active["operational_success"] is False
    with pytest.raises(ValueError, match="approve-target-ref"):
        cli.run(arguments(tmp_path, "rollback", built), now=LATER)
    removed = cli.run(
        arguments(tmp_path, "rollback", built, approve_target_ref=built[0].target_ref), now=LATER
    )
    assert removed["state"] == "removed"
    records = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert {item["operation"] for item in records} == {"apply", "activate", "rollback"}
    assert all(item["executor"] == "fake" for item in records)


def test_transport_follows_the_pinned_method_and_never_falls_back(tmp_path) -> None:
    built = build_installation(tmp_path, "existing_host")
    inputs = built[0]
    kubeconfig = private(tmp_path / "kubeconfig", "synthetic")
    args = arguments(tmp_path, "apply", built)
    with pytest.raises(ValueError, match="--kubeconfig"):
        cli._transport(inputs, args)
    args.kubeconfig = kubeconfig
    assert isinstance(cli._transport(inputs, args), KubectlTransport)
    run_command = inputs.model_copy(update={"method": "run_command"})
    with pytest.raises(ValueError, match="--subscription-id"):
        cli._transport(run_command, args)
    args.subscription_id = "00000000-0000-0000-0000-000000000000"
    args.resource_group, args.cluster_name = "rg-example", "aks-example"
    assert isinstance(cli._transport(run_command, args), AksRunCommandTransport)
    with pytest.raises(ValueError, match="export"):
        cli._transport(inputs.model_copy(update={"method": "gitops"}), args)


def test_gitops_export_writes_reviewable_documents_without_credentials(tmp_path) -> None:
    built = build_installation(tmp_path, "gitops")
    write_proposal(tmp_path, built)
    output = tmp_path / "gitops"
    result = cli.run(arguments(tmp_path, "export", built, output_directory=output), now=LATER)
    assert result["secret_included"] is False and result["execution_authority"] is False
    names = sorted(path.name for path in output.iterdir())
    assert len(names) == 6 and names[0].startswith("01-")
    assert b"-----BEGIN" not in b"".join(path.read_bytes() for path in output.iterdir())
    with pytest.raises(FileExistsError):
        cli.run(arguments(tmp_path, "export", built, output_directory=output), now=LATER)


def test_export_refuses_a_cluster_method(tmp_path, case) -> None:
    built, _ = case
    write_proposal(tmp_path, built)
    with pytest.raises(ValueError, match="only for the gitops"):
        cli.run(arguments(tmp_path, "export", built, output_directory=tmp_path / "out"), now=LATER)


def test_main_reports_a_rejection_without_a_traceback(tmp_path, capsys) -> None:
    assert cli.main(["apply"]) == 1
    assert "is required for this operation" in capsys.readouterr().err
