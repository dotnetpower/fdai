from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import cli, console_update
from fdai_deployment_cli.contracts import canonical_digest

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
TENANT = "00000000-0000-0000-0000-000000000002"
CLIENT = "00000000-0000-0000-0000-000000000003"
API_CLIENT = "00000000-0000-0000-0000-000000000004"


def _private_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def _target() -> dict[str, str]:
    return {
        "schema_version": "fdai.console-update-target.v1",
        "environment": "dev",
        "subscription_id": SUBSCRIPTION,
        "tenant_id": TENANT,
        "console_static_web_app_id": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-example/providers/"
            "Microsoft.Web/staticSites/swa-example"
        ),
        "console_hostname": "calm-field-012345678.3.azurestaticapps.net",
        "operator_api_base_url": "https://operator.example.com",
        "ingestion_api_base_url": "https://ingestion.example.com",
        "entra_console_spa_client_id": CLIENT,
        "entra_console_api_scope": f"api://{API_CLIENT}/access",
    }


def test_prepare_console_update_plan_seals_target_candidate_and_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    candidate = tmp_path / "candidate.tar.gz"
    rollback = tmp_path / "rollback.tar.gz"
    candidate.write_bytes(b"candidate")
    rollback.write_bytes(b"rollback")
    head = "a" * 40
    candidate_manifest = tmp_path / "candidate.json"
    rollback_manifest = tmp_path / "rollback.json"
    _artifact_manifest(candidate_manifest, source_commit=head, archive=candidate)
    _artifact_manifest(rollback_manifest, source_commit="b" * 40, archive=rollback)
    target = tmp_path / "target.json"
    _private_json(target, _target())

    def run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        if command[:4] == ("git", "-C", str(source), "rev-parse"):
            return subprocess.CompletedProcess(command, 0, stdout=f"{head}\n", stderr="")
        if command[:4] == ("git", "-C", str(source), "status"):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ("az", "account", "show"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"subscription_id": SUBSCRIPTION, "tenant_id": TENANT}),
                stderr="",
            )
        if command[:3] == ("az", "rest", "--method"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"{_target()['console_hostname']}\n",
                stderr="",
            )
        raise AssertionError(command)

    monkeypatch.setattr(console_update.subprocess, "run", run)
    work = tmp_path / "work"
    plan = console_update.prepare_console_update_plan(
        source_root=source,
        candidate_archive=candidate,
        candidate_manifest=candidate_manifest,
        rollback_archive=rollback,
        rollback_manifest=rollback_manifest,
        target_file=target,
        work_dir=work,
    )

    assert plan["source_commit"] == head
    assert plan["mutation_performed"] is False
    assert plan["candidate_archive_sha256"] != plan["rollback_archive_sha256"]
    assert len(str(plan["plan_digest"])) == 64
    assert (work / "candidate.tar.gz").read_bytes() == b"candidate"
    assert (work / "rollback.tar.gz").read_bytes() == b"rollback"
    assert (work / "plan.json").stat().st_mode & 0o777 == 0o600


def test_prepare_console_update_plan_rejects_active_target_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    candidate = tmp_path / "candidate.tar.gz"
    rollback = tmp_path / "rollback.tar.gz"
    candidate.write_bytes(b"candidate")
    rollback.write_bytes(b"rollback")
    candidate_manifest = tmp_path / "candidate.json"
    rollback_manifest = tmp_path / "rollback.json"
    _artifact_manifest(candidate_manifest, source_commit="a" * 40, archive=candidate)
    _artifact_manifest(rollback_manifest, source_commit="b" * 40, archive=rollback)
    target = tmp_path / "target.json"
    _private_json(target, _target())

    def run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        if command[:4] == ("git", "-C", str(source), "rev-parse"):
            return subprocess.CompletedProcess(command, 0, stdout=f"{'a' * 40}\n", stderr="")
        if command[:4] == ("git", "-C", str(source), "status"):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"subscription_id": SUBSCRIPTION, "tenant_id": "f" * 36}),
            stderr="",
        )

    monkeypatch.setattr(console_update.subprocess, "run", run)
    with pytest.raises(ValueError, match="active Azure target"):
        console_update.prepare_console_update_plan(
            source_root=source,
            candidate_archive=candidate,
            candidate_manifest=candidate_manifest,
            rollback_archive=rollback,
            rollback_manifest=rollback_manifest,
            target_file=target,
            work_dir=tmp_path / "work",
        )


def test_apply_console_update_plan_writes_claim_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, work, plan = _prepared_plan(tmp_path, monkeypatch)
    calls: list[bool] = []

    def publish(**arguments: object) -> dict[str, object]:
        assert (work / "claim.json").is_file()
        calls.append(bool(arguments["verify_only"]))
        return _publication_receipt(verify_only=bool(arguments["verify_only"]))

    monkeypatch.setattr(console_update, "publish_verified_console", publish)
    receipt = console_update.apply_console_update_plan(
        source_root=source,
        work_dir=work,
        approved_plan_digest=str(plan["plan_digest"]),
        scripts=source / "scripts/deployment/azure",
    )

    assert calls == [False]
    assert receipt["state"] == "applied"
    assert receipt["artifact_readback_verified"] is True
    assert receipt["recovered_by_readback"] is False


def test_apply_console_update_plan_resumes_claim_by_readback_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, work, plan = _prepared_plan(tmp_path, monkeypatch)
    plan["expires_at"] = "2000-01-01T00:00:00+00:00"
    plan["plan_digest"] = canonical_digest(
        {key: value for key, value in plan.items() if key != "plan_digest"}
    )
    _private_json(work / "plan.json", plan)
    claim = {
        "schema_version": "fdai.console-update-claim.v1",
        "plan_digest": plan["plan_digest"],
        "approval_digest": "f" * 64,
        "idempotency_key": plan["idempotency_key"],
        "claimed_at": "2026-09-17T00:00:00+00:00",
    }
    claim["claim_digest"] = canonical_digest(claim)
    _private_json(work / "claim.json", claim)
    calls: list[bool] = []

    def publish(**arguments: object) -> dict[str, object]:
        calls.append(bool(arguments["verify_only"]))
        return _publication_receipt(verify_only=bool(arguments["verify_only"]))

    monkeypatch.setattr(console_update, "publish_verified_console", publish)
    receipt = console_update.apply_console_update_plan(
        source_root=source,
        work_dir=work,
        approved_plan_digest=str(plan["plan_digest"]),
        scripts=source / "scripts/deployment/azure",
    )

    assert calls == [True]
    assert receipt["recovered_by_readback"] is True
    assert receipt["mutation_performed"] is False


def test_apply_console_update_plan_rolls_back_failed_publication_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, work, plan = _prepared_plan(tmp_path, monkeypatch)
    calls: list[bool] = []

    def publish(**arguments: object) -> dict[str, object]:
        calls.append(bool(arguments["verify_only"]))
        if len(calls) == 1:
            raise ValueError("candidate failed")
        return _publication_receipt(verify_only=False)

    monkeypatch.setattr(console_update, "publish_verified_console", publish)
    arguments = {
        "source_root": source,
        "work_dir": work,
        "approved_plan_digest": str(plan["plan_digest"]),
        "scripts": source / "scripts/deployment/azure",
    }
    with pytest.raises(ValueError, match="rollback was restored"):
        console_update.apply_console_update_plan(**arguments)

    assert calls == [False, False]
    assert (work / "failure.json").is_file()
    with pytest.raises(ValueError, match="previously failed"):
        console_update.apply_console_update_plan(**arguments)
    assert calls == [False, False]


def test_claim_recovery_does_not_republish_an_existing_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, work, plan = _prepared_plan(tmp_path, monkeypatch)
    claim = {
        "schema_version": "fdai.console-update-claim.v1",
        "plan_digest": plan["plan_digest"],
        "approval_digest": "f" * 64,
        "idempotency_key": plan["idempotency_key"],
        "claimed_at": "2026-09-17T00:00:00+00:00",
    }
    claim["claim_digest"] = canonical_digest(claim)
    _private_json(work / "claim.json", claim)
    (work / "candidate-verify").mkdir()
    (work / "rollback-verify").mkdir()
    (work / "rollback-recovery").mkdir()
    calls: list[tuple[bool, bool]] = []

    def publish(**arguments: object) -> dict[str, object]:
        verify_only = bool(arguments["verify_only"])
        verify_service_contracts = bool(arguments["verify_service_contracts"])
        calls.append((verify_only, verify_service_contracts))
        if len(calls) == 1:
            raise ValueError("candidate differs")
        return _publication_receipt(
            verify_only=verify_only,
            verify_service_contracts=verify_service_contracts,
        )

    monkeypatch.setattr(console_update, "publish_verified_console", publish)
    with pytest.raises(ValueError, match="rollback was restored"):
        console_update.apply_console_update_plan(
            source_root=source,
            work_dir=work,
            approved_plan_digest=str(plan["plan_digest"]),
            scripts=source / "scripts/deployment/azure",
        )

    assert calls == [(True, True), (True, False)]
    failure = json.loads((work / "failure.json").read_text(encoding="utf-8"))
    assert failure["reason"] == "claimed_candidate_readback_failed_rollback_already_present"
    assert failure["mutation_performed"] is False
    assert failure["api_health_verified"] is False
    assert failure["authorization_preflight_verified"] is False
    assert failure["entra_redirect_verified"] is False
    with pytest.raises(ValueError, match="previously failed"):
        console_update.apply_console_update_plan(
            source_root=source,
            work_dir=work,
            approved_plan_digest=str(plan["plan_digest"]),
            scripts=source / "scripts/deployment/azure",
        )
    assert calls == [(True, True), (True, False)]


def test_shared_publisher_supports_readback_without_republication() -> None:
    root = Path(__file__).resolve().parents[3]
    publisher = (root / "scripts/deployment/azure/publish-console.sh").read_text(encoding="utf-8")

    assert 'verify_only="${FDAI_CONSOLE_VERIFY_ONLY:-0}"' in publisher
    assert 'if [[ "$verify_only" == 0 ]]; then' in publisher
    assert "verify-only Console readback requires CONSOLE_PREBUILT_DIRECTORY" in publisher
    assert 'verify_service_contracts="${FDAI_CONSOLE_VERIFY_SERVICE_CONTRACTS:-1}"' in publisher
    assert 'index.html fdai-config.js "${entry_asset#/}"' in publisher
    assert "index.html fdai-config.js staticwebapp.config.json" not in publisher


def test_cli_apply_keeps_internal_exact_plan_binding_without_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    plan_digest = "a" * 64
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        cli,
        "load_console_update_plan",
        lambda _path, **_kwargs: {
            "source_commit": "b" * 40,
            "target_binding": "c" * 64,
            "candidate_archive_sha256": "d" * 64,
            "rollback_archive_sha256": "e" * 64,
            "plan_digest": plan_digest,
        },
    )

    def apply(**arguments: object) -> dict[str, object]:
        captured.update(arguments)
        return {"receipt_digest": "f" * 64}

    monkeypatch.setattr(cli, "apply_console_update_plan", apply)
    result = cli._provision_console_update_apply(
        SimpleNamespace(source=source, work_dir=work, timeout_seconds=900, output="text")
    )

    assert result == 0
    assert captured["approved_plan_digest"] == plan_digest
    assert (
        captured["scripts"] == Path(cli.__file__).resolve().parents[4] / "scripts/deployment/azure"
    )


def _prepared_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, dict[str, object]]:
    source = tmp_path / "source"
    source.mkdir()
    candidate = tmp_path / "candidate.tar.gz"
    rollback = tmp_path / "rollback.tar.gz"
    candidate.write_bytes(b"candidate")
    rollback.write_bytes(b"rollback")
    head = "a" * 40
    candidate_manifest = tmp_path / "candidate.json"
    rollback_manifest = tmp_path / "rollback.json"
    _artifact_manifest(candidate_manifest, source_commit=head, archive=candidate)
    _artifact_manifest(rollback_manifest, source_commit="b" * 40, archive=rollback)
    target = tmp_path / "target.json"
    _private_json(target, _target())

    def run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
        if command[:4] == ("git", "-C", str(source), "rev-parse"):
            return subprocess.CompletedProcess(command, 0, stdout=f"{head}\n", stderr="")
        if command[:4] == ("git", "-C", str(source), "status"):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ("az", "account", "show"):
            query = command[command.index("--query") + 1]
            payload = {"subscription_id": SUBSCRIPTION, "tenant_id": TENANT}
            if "user_name" in query:
                payload.update({"user_name": "operator@example.com", "user_type": "user"})
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        if command[:3] == ("az", "rest", "--method"):
            return subprocess.CompletedProcess(
                command, 0, stdout=f"{_target()['console_hostname']}\n", stderr=""
            )
        raise AssertionError(command)

    monkeypatch.setattr(console_update.subprocess, "run", run)
    work = tmp_path / "work"
    plan = console_update.prepare_console_update_plan(
        source_root=source,
        candidate_archive=candidate,
        candidate_manifest=candidate_manifest,
        rollback_archive=rollback,
        rollback_manifest=rollback_manifest,
        target_file=target,
        work_dir=work,
    )
    return source, work, plan


def _publication_receipt(
    *, verify_only: bool, verify_service_contracts: bool = True
) -> dict[str, object]:
    return {
        "receipt_digest": "b" * 64,
        "api_health_verified": verify_service_contracts,
        "authorization_preflight_verified": verify_service_contracts,
        "entra_redirect_verified": verify_service_contracts,
        "mutation_performed": not verify_only,
    }


def _artifact_manifest(path: Path, *, source_commit: str, archive: Path) -> None:
    _private_json(
        path,
        {
            "schema_version": "fdai.console-update-artifact.v1",
            "source_commit": source_commit,
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        },
    )
