#!/usr/bin/env python3
"""Enroll and attest the exact Foundation runner over Azure Bastion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.profile import load_profile
from fdai_deployment_cli.target import compute_target_binding
from genesis_bastion import (
    BastionTunnel,
    create_known_hosts,
    validate_known_hosts,
    validate_ssh_private_key,
)
from genesis_checks import CheckError, GenesisChecks
from genesis_subprocess import run_with_heartbeat

CLAIM_NAME = "runner-enrollment-claim.json"
RECEIPT_NAME = "runner-enrollment-receipt.json"
KNOWN_HOSTS_NAME = "runner-known-hosts"
FOUNDATION_RECEIPT_NAME = "foundation-apply-receipt.json"
HANDOFF_NAME = "foundation-private-handoff.json"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_RUNNER_NAME = re.compile(r"vm-runner-[a-z0-9][a-z0-9-]{0,62}")
_TOKEN = re.compile(r"[^\s]{20,4096}")
_REQUIRED_LABELS = frozenset({"self-hosted", "fdai-deploy", "fdai-deploy-candidate"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foundation-plan-directory", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ssh-private-key", type=Path, required=True)
    parser.add_argument("--expected-foundation-receipt-digest", required=True)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--resume-verification", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser


def _execute(args: argparse.Namespace) -> dict[str, object]:
    if args.approve == args.resume_verification:
        raise ValueError("runner enrollment requires exactly one approval or verification resume")
    if _DIGEST.fullmatch(args.expected_foundation_receipt_digest) is None:
        raise ValueError("expected Foundation receipt digest is invalid")
    if not 300 <= args.timeout_seconds <= 3600:
        raise ValueError("runner enrollment timeout must be from 300 through 3600 seconds")

    root = _repository_root()
    directory = _absolute(args.foundation_plan_directory)
    profile = load_profile(_absolute(args.profile))
    if profile.access_method != "bastion":
        raise ValueError("runner enrollment requires the reviewed Bastion access profile")
    foundation = _load_foundation_receipt(
        directory / FOUNDATION_RECEIPT_NAME,
        expected_digest=args.expected_foundation_receipt_digest,
    )
    handoff = _load_handoff(directory / HANDOFF_NAME, foundation=foundation)
    runner = _object(handoff["runner"], "Foundation runner handoff")
    access = _object(handoff["access"], "Foundation access handoff")
    ops = _object(handoff["ops"], "Foundation operations handoff")
    _validate_context(profile.target_binding, handoff, foundation)
    manual = runner.get("execution_transport", "github-actions") == "manual"
    if not manual and _REPOSITORY.fullmatch(args.repository) is None:
        raise ValueError("runner enrollment repository is invalid")
    connection = _connection_values(runner, access, ops)
    private_key = _absolute(args.ssh_private_key)
    if validate_ssh_private_key(private_key) != runner["ssh_key_digest"]:
        raise ValueError("runner SSH private key does not match the reviewed Foundation key")

    checks = GenesisChecks(root)
    checks.verify_target(
        subscription_id=str(handoff["subscription_id"]),
        tenant_id=str(handoff["tenant_id"]),
        region=str(handoff["region"]),
    )
    checks.verify_source(
        source_commit=str(handoff["source_commit"]), repository=args.repository, apply=True
    )

    parallelism = runner["parallelism"]
    if type(parallelism) is not int:
        raise ValueError("Foundation runner parallelism is invalid")
    expected_names = _runner_names(str(runner["vm_name"]), parallelism)
    repository_digest = hashlib.sha256(
        (f"manual:{profile.target_binding}" if manual else args.repository.casefold()).encode()
    ).hexdigest()
    claim_path = directory / CLAIM_NAME
    receipt_path = directory / RECEIPT_NAME
    known_hosts = directory / KNOWN_HOSTS_NAME
    claim = _load_optional_claim(claim_path)
    vm_digest = hashlib.sha256(connection["vm_id"].casefold().encode()).hexdigest()
    host_alias = "fdai-genesis-" + vm_digest[:16]
    if receipt_path.exists():
        if claim is None:
            raise ValueError("runner enrollment receipt is missing its immutable claim")
        existing_receipt = _load_receipt(receipt_path)
        _validate_claim_context(claim, foundation, repository_digest, expected_names)
        validate_known_hosts(known_hosts)
        host_key_digest = _file_digest(known_hosts)
        if claim.get("host_key_digest") != host_key_digest:
            raise ValueError("runner enrollment host-key evidence changed after claim")
        _validate_receipt_context(
            existing_receipt,
            foundation,
            repository_digest,
            expected_names,
            claim=claim,
            host_key_digest=host_key_digest,
            toolchain_digest=str(runner["toolchain_digest"]),
            manual=manual,
        )
        with BastionTunnel(
            subscription_id=str(handoff["subscription_id"]),
            resource_group=connection["resource_group"],
            bastion_name=connection["bastion_name"],
            vm_id=connection["vm_id"],
            username=connection["username"],
            private_key=private_key,
            known_hosts=known_hosts,
            host_key_alias=host_alias,
            cwd=directory,
            timeout=args.timeout_seconds,
            trust_new_host_key=False,
        ) as tunnel:
            _attest_runner(
                tunnel,
                handoff=handoff,
                runner=runner,
                timeout=args.timeout_seconds,
                transport=profile.transport,
            )
        observed = (
            _manual_host_set(expected_names)
            if manual
            else _wait_for_runners(args.repository, expected_names, timeout=60)
        )
        if _runner_set_digest(observed) != existing_receipt["runner_set_digest"]:
            raise ValueError("registered runner readback changed after receipt")
        return existing_receipt

    if args.resume_verification:
        if claim is None:
            raise ValueError("runner enrollment verification resume requires an existing claim")
        _validate_claim_context(claim, foundation, repository_digest, expected_names)
        validate_known_hosts(known_hosts)
    elif claim is not None:
        raise ValueError("runner enrollment claim exists; only verification may resume")
    else:
        conflicts = (
            set()
            if manual
            else {item["name"] for item in _list_runners(args.repository)} & set(expected_names)
        )
        if conflicts:
            raise ValueError(
                "runner enrollment names already exist and cannot be adopted implicitly"
            )

    _prepare_known_hosts(known_hosts, claim_exists=claim is not None)
    if claim is not None and claim.get("host_key_digest") != _file_digest(known_hosts):
        raise ValueError("runner enrollment host-key evidence changed after claim")
    with BastionTunnel(
        subscription_id=str(handoff["subscription_id"]),
        resource_group=connection["resource_group"],
        bastion_name=connection["bastion_name"],
        vm_id=connection["vm_id"],
        username=connection["username"],
        private_key=private_key,
        known_hosts=known_hosts,
        host_key_alias=host_alias,
        cwd=directory,
        timeout=args.timeout_seconds,
        trust_new_host_key=claim is None,
    ) as tunnel:
        if claim is None:
            preflight_command = (
                ("/usr/bin/test", "-x", "/usr/local/sbin/fdai-attest-runner")
                if manual
                else (
                    "/usr/bin/test",
                    "-x",
                    "/usr/local/sbin/fdai-enroll-runner",
                    "-a",
                    "-x",
                    "/usr/local/sbin/fdai-attest-runner",
                )
            )
            preflight = tunnel.ssh(preflight_command, timeout=60)
            if preflight.returncode != 0:
                raise ValueError("runner enrollment helpers are unavailable on the exact VM")
            validate_known_hosts(known_hosts)
            claim = _create_claim(
                foundation=foundation,
                repository_digest=repository_digest,
                expected_names=expected_names,
                actor_digest=(
                    _azure_actor_digest(profile.target_binding)
                    if manual
                    else _github_actor_digest(args.repository)
                ),
                host_key_digest=_file_digest(known_hosts),
            )
            write_private_output(
                claim_path, json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n"
            )
            if not manual:
                token = _registration_token(args.repository)
                try:
                    for slot, runner_name in enumerate(expected_names, start=1):
                        completed = tunnel.ssh(
                            (
                                "/usr/local/sbin/fdai-enroll-runner",
                                "--repository-url",
                                f"https://github.com/{args.repository}",
                                "--slot",
                                str(slot),
                                "--runner-name",
                                runner_name,
                            ),
                            timeout=min(300, args.timeout_seconds),
                            input_text=token + "\n",
                        )
                        marker = f"enrollment_complete slot={slot} runner_name={runner_name}"
                        if (
                            completed.returncode != 0
                            or marker not in completed.stdout.splitlines()
                            or token in completed.stdout
                            or token in completed.stderr
                        ):
                            raise ValueError(
                                "runner enrollment did not return its sanitized completion marker"
                            )
                finally:
                    token = ""

        _attest_runner(
            tunnel,
            handoff=handoff,
            runner=runner,
            timeout=args.timeout_seconds,
            transport=profile.transport,
        )

    observed = (
        _manual_host_set(expected_names)
        if manual
        else _wait_for_runners(args.repository, expected_names, timeout=180)
    )
    completed_at = _utc_now().replace(microsecond=0).isoformat()
    if claim is None:
        raise ValueError("runner enrollment claim was not persisted before verification")
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-runner-enrollment-receipt.v1",
        "state": "attested",
        "foundation_receipt_digest": foundation["receipt_digest"],
        "handoff_digest": foundation["handoff_digest"],
        "target_binding": foundation["target_binding"],
        "source_commit": foundation["source_commit"],
        "repository_digest": repository_digest,
        "runner_names": expected_names,
        "runner_count": len(expected_names),
        "runner_set_digest": _runner_set_digest(observed),
        "claim_digest": canonical_digest(claim),
        "actor_digest": claim["actor_digest"],
        "host_key_digest": claim["host_key_digest"],
        "toolchain_digest": runner["toolchain_digest"],
        "identity_attested": True,
        "services_attested": True,
        "github_readback_verified": not manual,
        "manual_host_readback_verified": manual,
        "effect_verified": True,
        "mutation_performed": not manual,
        "subscription_ready": False,
        "completed_at": completed_at,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    write_private_output(
        receipt_path, json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return receipt


def _load_foundation_receipt(path: Path, *, expected_digest: str) -> dict[str, object]:
    receipt = _private_json(path, label="Foundation apply receipt")
    digest = receipt.pop("receipt_digest", None)
    if (
        digest != expected_digest
        or canonical_digest(receipt) != expected_digest
        or receipt.get("schema_version") != "fdai.genesis-foundation-apply-receipt.v1"
        or receipt.get("state") != "applied"
        or receipt.get("control_plane_readback_verified") is not True
        or receipt.get("zero_change_verified") is not True
        or receipt.get("remote_backend_authority_verified") is not False
        or receipt.get("runner_attested") is not False
    ):
        raise ValueError("Foundation apply receipt is invalid for runner enrollment")
    receipt["receipt_digest"] = digest
    return receipt


def _load_handoff(path: Path, *, foundation: Mapping[str, object]) -> dict[str, object]:
    handoff = _private_json(path, label="Foundation private handoff")
    if canonical_digest(handoff) != foundation.get("handoff_digest"):
        raise ValueError("Foundation private handoff does not match the apply receipt")
    return handoff


def _validate_context(
    target_binding: str, handoff: Mapping[str, object], foundation: Mapping[str, object]
) -> None:
    tenant = handoff.get("tenant_id")
    subscription = handoff.get("subscription_id")
    if (
        not isinstance(tenant, str)
        or _GUID.fullmatch(tenant) is None
        or not isinstance(subscription, str)
        or _GUID.fullmatch(subscription) is None
        or compute_target_binding(tenant_id=tenant, subscription_id=subscription) != target_binding
        or foundation.get("target_binding") != target_binding
        or handoff.get("source_commit") != foundation.get("source_commit")
    ):
        raise ValueError("runner enrollment target or source context is invalid")


def _connection_values(
    runner: Mapping[str, object], access: Mapping[str, object], ops: Mapping[str, object]
) -> dict[str, str]:
    values = {
        "resource_group": ops.get("resource_group_name"),
        "bastion_name": access.get("bastion_name"),
        "bastion_id": access.get("bastion_id"),
        "vm_id": runner.get("vm_id"),
        "username": runner.get("admin_username"),
    }
    if access.get("method") != "bastion" or any(
        not isinstance(value, str) or not value for value in values.values()
    ):
        raise ValueError("Foundation Bastion access handoff is incomplete")
    parallelism = runner.get("parallelism")
    if type(parallelism) is not int or not 1 <= parallelism <= 5:
        raise ValueError("Foundation runner parallelism is invalid")
    for key in ("client_id", "principal_id"):
        if not isinstance(runner.get(key), str) or _GUID.fullmatch(str(runner[key])) is None:
            raise ValueError("Foundation runner identity handoff is invalid")
    for key in ("toolchain_digest", "ssh_key_digest"):
        if not isinstance(runner.get(key), str) or _DIGEST.fullmatch(str(runner[key])) is None:
            raise ValueError("Foundation runner provenance handoff is invalid")
    if (
        not isinstance(runner.get("vm_name"), str)
        or _RUNNER_NAME.fullmatch(str(runner["vm_name"])) is None
    ):
        raise ValueError("Foundation runner name is invalid")
    return {key: str(value) for key, value in values.items()}


def _runner_names(vm_name: str, parallelism: int) -> list[str]:
    return [vm_name if slot == 1 else f"{vm_name}-{slot}" for slot in range(1, parallelism + 1)]


def _registration_token(repository: str) -> str:
    token = _capture(
        (
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{repository}/actions/runners/registration-token",
            "--jq",
            ".token",
        ),
        timeout=60,
        reason="GitHub runner registration token request failed",
    ).strip()
    if _TOKEN.fullmatch(token) is None:
        raise ValueError("GitHub runner registration token response is invalid")
    return token


def _github_actor_digest(repository: str) -> str:
    login = _capture(
        ("gh", "api", "user", "--jq", ".login"),
        timeout=30,
        reason="GitHub enrollment actor is unavailable",
    ).strip()
    if re.fullmatch(r"[A-Za-z0-9-]{1,39}", login) is None:
        raise ValueError("GitHub enrollment actor is invalid")
    return hashlib.sha256(f"{repository.casefold()}:{login.casefold()}".encode()).hexdigest()


def _list_runners(repository: str) -> list[dict[str, object]]:
    raw = _capture(
        ("gh", "api", "-X", "GET", f"repos/{repository}/actions/runners?per_page=100"),
        timeout=60,
        reason="GitHub runner readback failed",
    )
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("runners"), list):
        raise ValueError("GitHub runner readback is invalid")
    total = value.get("total_count")
    if type(total) is not int or total != len(value["runners"]) or total > 100:
        raise ValueError("GitHub runner readback exceeds the bounded result set")
    result: list[dict[str, object]] = []
    for item in value["runners"]:
        runner = _object(item, "GitHub runner")
        name = runner.get("name")
        labels = runner.get("labels")
        if not isinstance(name, str) or not isinstance(labels, list):
            raise ValueError("GitHub runner readback contains an invalid record")
        label_names = {
            str(_object(label, "GitHub runner label").get("name", "")).casefold()
            for label in labels
        }
        result.append(
            {
                "name": name,
                "status": runner.get("status"),
                "busy": runner.get("busy"),
                "labels": sorted(label_names),
            }
        )
    return result


def _wait_for_runners(
    repository: str, expected_names: list[str], *, timeout: int
) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    expected = set(expected_names)
    last_heartbeat = time.monotonic()
    while True:
        selected = [item for item in _list_runners(repository) if item["name"] in expected]
        by_name = {str(item["name"]): item for item in selected}
        if set(by_name) == expected and all(_runner_is_ready(item) for item in by_name.values()):
            return [by_name[name] for name in expected_names]
        now = time.monotonic()
        if now >= deadline:
            raise ValueError("GitHub runner readback did not reach the exact online label set")
        if now - last_heartbeat >= 10:
            print(".", end="", file=sys.stderr, flush=True)
            last_heartbeat = now
        time.sleep(min(2, deadline - now))


def _runner_is_ready(runner: Mapping[str, object]) -> bool:
    labels = runner.get("labels")
    return (
        runner.get("status") == "online"
        and isinstance(labels, list)
        and all(isinstance(label, str) for label in labels)
        and _REQUIRED_LABELS.issubset(set(labels))
    )


def _create_claim(
    *,
    foundation: Mapping[str, object],
    repository_digest: str,
    expected_names: list[str],
    actor_digest: str,
    host_key_digest: str,
) -> dict[str, object]:
    return {
        "schema_version": "fdai.genesis-runner-enrollment-claim.v1",
        "state": "enrolling",
        "foundation_receipt_digest": foundation["receipt_digest"],
        "handoff_digest": foundation["handoff_digest"],
        "target_binding": foundation["target_binding"],
        "source_commit": foundation["source_commit"],
        "repository_digest": repository_digest,
        "runner_names": expected_names,
        "actor_digest": actor_digest,
        "host_key_digest": host_key_digest,
        "idempotency_key": canonical_digest(
            {
                "foundation_receipt_digest": foundation["receipt_digest"],
                "repository_digest": repository_digest,
                "runner_names": expected_names,
            }
        ),
        "claimed_at": _utc_now().replace(microsecond=0).isoformat(),
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _load_optional_claim(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    claim = _private_json(path, label="runner enrollment claim")
    if claim.get("schema_version") != "fdai.genesis-runner-enrollment-claim.v1":
        raise ValueError("runner enrollment claim is invalid")
    return claim


def _validate_claim_context(
    claim: Mapping[str, object],
    foundation: Mapping[str, object],
    repository_digest: str,
    expected_names: list[str],
) -> None:
    if (
        claim.get("foundation_receipt_digest") != foundation["receipt_digest"]
        or claim.get("handoff_digest") != foundation["handoff_digest"]
        or claim.get("target_binding") != foundation["target_binding"]
        or claim.get("source_commit") != foundation["source_commit"]
        or claim.get("repository_digest") != repository_digest
        or claim.get("runner_names") != expected_names
        or not isinstance(claim.get("actor_digest"), str)
        or _DIGEST.fullmatch(str(claim["actor_digest"])) is None
        or not isinstance(claim.get("host_key_digest"), str)
        or _DIGEST.fullmatch(str(claim["host_key_digest"])) is None
        or claim.get("idempotency_key")
        != canonical_digest(
            {
                "foundation_receipt_digest": foundation["receipt_digest"],
                "repository_digest": repository_digest,
                "runner_names": expected_names,
            }
        )
        or claim.get("state") != "enrolling"
        or claim.get("mutation_performed") is not False
    ):
        raise ValueError("runner enrollment claim context is invalid")


def _load_receipt(path: Path) -> dict[str, object]:
    receipt = _private_json(path, label="runner enrollment receipt")
    digest = receipt.pop("receipt_digest", None)
    if (
        not isinstance(digest, str)
        or canonical_digest(receipt) != digest
        or receipt.get("schema_version") != "fdai.genesis-runner-enrollment-receipt.v1"
        or receipt.get("state") != "attested"
        or receipt.get("effect_verified") is not True
    ):
        raise ValueError("runner enrollment receipt is invalid")
    receipt["receipt_digest"] = digest
    return receipt


def _validate_receipt_context(
    receipt: Mapping[str, object],
    foundation: Mapping[str, object],
    repository_digest: str,
    expected_names: list[str],
    *,
    claim: Mapping[str, object],
    host_key_digest: str,
    toolchain_digest: str,
    manual: bool,
) -> None:
    if (
        receipt.get("foundation_receipt_digest") != foundation["receipt_digest"]
        or receipt.get("handoff_digest") != foundation["handoff_digest"]
        or receipt.get("target_binding") != foundation["target_binding"]
        or receipt.get("source_commit") != foundation["source_commit"]
        or receipt.get("repository_digest") != repository_digest
        or receipt.get("runner_names") != expected_names
        or receipt.get("runner_count") != len(expected_names)
        or receipt.get("claim_digest") != canonical_digest(dict(claim))
        or receipt.get("actor_digest") != claim.get("actor_digest")
        or receipt.get("host_key_digest") != host_key_digest
        or receipt.get("toolchain_digest") != toolchain_digest
        or not isinstance(receipt.get("runner_set_digest"), str)
        or _DIGEST.fullmatch(str(receipt["runner_set_digest"])) is None
        or receipt.get("identity_attested") is not True
        or receipt.get("services_attested") is not True
        or receipt.get("github_readback_verified") is not (not manual)
        or bool(receipt.get("manual_host_readback_verified", False)) is not manual
        or receipt.get("mutation_performed") is not (not manual)
        or receipt.get("subscription_ready") is not False
    ):
        raise ValueError("runner enrollment receipt context is invalid")


def _attest_runner(
    tunnel: BastionTunnel,
    *,
    handoff: Mapping[str, object],
    runner: Mapping[str, object],
    timeout: int,
    transport: str,
) -> None:
    """Re-observe the exact runner identity, tools, and services without mutation."""

    attestation = tunnel.ssh(
        (
            "/usr/local/sbin/fdai-attest-runner",
            "--subscription-id",
            str(handoff["subscription_id"]),
            "--tenant-id",
            str(handoff["tenant_id"]),
            "--client-id",
            str(runner["client_id"]),
            "--principal-id",
            str(runner["principal_id"]),
            "--source-commit",
            str(handoff["source_commit"]),
            "--toolchain-digest",
            str(runner["toolchain_digest"]),
            "--parallelism",
            str(runner["parallelism"]),
            "--transport",
            transport,
        ),
        timeout=min(300, timeout),
    )
    if attestation.returncode != 0 or not {
        f"attestation_complete transport={transport} slots={runner['parallelism']}",
        f"attestation_complete slots={runner['parallelism']}",
    }.intersection(attestation.stdout.splitlines()):
        raise ValueError("runner identity, toolchain, or service attestation failed")


def _runner_set_digest(runners: list[dict[str, object]]) -> str:
    stable = [{"name": runner["name"], "labels": runner["labels"]} for runner in runners]
    return canonical_digest({"runners": stable})


def _manual_host_set(expected_names: list[str]) -> list[dict[str, object]]:
    """Return the deterministic manual-host set after remote attestation succeeds."""

    return [
        {"name": name, "status": "attested", "busy": False, "labels": ["manual"]}
        for name in expected_names
    ]


def _azure_actor_digest(target_binding: str) -> str:
    """Bind the manual host claim to the current authenticated Azure human."""

    raw = _capture(
        ("az", "account", "show", "--query", "{type:user.type,name:user.name}", "-o", "json"),
        timeout=30,
        reason="Azure host-attestation actor is unavailable",
    )
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or value.get("type") != "user"
        or not isinstance(value.get("name"), str)
        or not value["name"]
    ):
        raise ValueError("manual host attestation requires an authenticated Azure human")
    return hashlib.sha256(f"{target_binding}:{value['name'].casefold()}".encode()).hexdigest()


def _prepare_known_hosts(path: Path, *, claim_exists: bool) -> None:
    if path.exists():
        if path.stat().st_size == 0 and not claim_exists:
            path.unlink()
            create_known_hosts(path)
        else:
            validate_known_hosts(path)
        return
    if claim_exists:
        raise ValueError("runner enrollment claim is missing host-key evidence")
    create_known_hosts(path)


def _private_json(path: Path, *, label: str) -> dict[str, object]:
    return load_json_object(read_private_bytes(path, max_bytes=1_048_576), label=label)


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {key: item for key, item in value.items()}


def _capture(command: Sequence[str], *, timeout: int, reason: str) -> str:
    completed = run_with_heartbeat(
        command,
        cwd=_repository_root(),
        timeout=timeout,
        capture_output=True,
        umask=0o077,
    )
    if completed.returncode != 0:
        raise ValueError(reason)
    return completed.stdout


def _file_digest(path: Path) -> str:
    return hashlib.sha256(read_private_bytes(path, max_bytes=65_536)).hexdigest()


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint


def _print(result: Mapping[str, object], output: str) -> None:
    safe = {
        "schema_version": result["schema_version"],
        "state": result["state"],
        "runner_count": result["runner_count"],
        "identity_attested": result["identity_attested"],
        "services_attested": result["services_attested"],
        "github_readback_verified": result["github_readback_verified"],
        "manual_host_readback_verified": result.get("manual_host_readback_verified", False),
        "effect_verified": result["effect_verified"],
        "subscription_ready": result["subscription_ready"],
        "receipt_digest": result["receipt_digest"],
    }
    if output == "json":
        print(json.dumps(safe, sort_keys=True, separators=(",", ":")))
    else:
        print("execution host attestation and independent readback completed")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one exact enrollment or verification-only resume with stable failures."""

    args = _parser().parse_args(argv)
    try:
        result = _execute(args)
        _print(result, args.output)
        return 0
    except (
        CheckError,
        OSError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        reason = exc.reason_code if isinstance(exc, CheckError) else str(exc)
        print(f"genesis-runner-enrollment: {reason}", file=sys.stderr)
        return exc.exit_code if isinstance(exc, CheckError) else 3


if __name__ == "__main__":
    raise SystemExit(main())
