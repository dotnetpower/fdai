#!/usr/bin/env python3
"""Apply or reverify one exact signed-kit Foundation plan without a GitHub workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fdai_deployment_cli.__about__ import __version__
from fdai_deployment_cli.bundle import extract_bundle_archive, verify_bundle
from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.foundation_input import snapshot_foundation_input
from fdai_deployment_cli.foundation_plan import PLAN_NAME, REVIEW_NAME, verify_foundation_plan
from fdai_deployment_cli.offline_kit import materialize_verified_artifacts, verify_offline_kit
from fdai_deployment_cli.plan_input import read_plan_input
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.profile import load_profile
from genesis_checks import CheckError, GenesisChecks
from genesis_foundation_apply_contract import (
    load_apply_claim,
    load_apply_receipt,
    require_same_effect,
)
from genesis_subprocess import run_with_heartbeat
from genesis_vm_sku_preflight import recheck_foundation_vm

CLAIM_NAME = "foundation-apply-claim.json"
RECEIPT_NAME = "foundation-apply-receipt.json"
HANDOFF_NAME = "foundation-private-handoff.json"
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-directory", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--variables-file", type=Path, required=True)
    parser.add_argument("--offline-kit", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--bundle-public-key", type=Path, required=True)
    parser.add_argument("--expected-review-digest", required=True)
    parser.add_argument("--expected-plan-digest", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--resume-verification", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser


def _execute(args: argparse.Namespace) -> dict[str, object]:
    if args.approve == args.resume_verification:
        raise ValueError("Foundation apply requires exactly one approval or verification resume")
    if _DIGEST.fullmatch(args.expected_plan_digest) is None:
        raise ValueError("expected Foundation plan digest is invalid")
    if not 900 <= args.timeout_seconds <= 14_400:
        raise ValueError("Foundation apply timeout must be from 900 through 14400 seconds")
    repository_root = Path(__file__).resolve().parents[3]
    plan_directory = _absolute(args.plan_directory)
    profile_path = _absolute(args.profile)
    variables_path = _absolute(args.variables_file)
    profile = load_profile(profile_path)
    receipt_path = plan_directory / RECEIPT_NAME
    claim_path = plan_directory / CLAIM_NAME
    effect_started = claim_path.exists() or receipt_path.exists()
    integrity = verify_foundation_plan(
        directory=plan_directory,
        profile=profile,
        expected_review_digest=args.expected_review_digest,
        require_unexpired=not effect_started,
    )
    if integrity["plan_digest"] != args.expected_plan_digest:
        raise ValueError("expected Foundation plan digest does not match the review")
    review = _foundation_review(plan_directory)
    context = review["context"]
    if not isinstance(context, dict):
        raise ValueError("Foundation review context is invalid")
    checks = GenesisChecks(repository_root)
    subscription_id, tenant_id = _foundation_target(
        variables_path=variables_path,
        profile_path=profile_path,
        destination=plan_directory / ".foundation-apply-input.json",
        expected_context=context,
    )
    checks.verify_target(
        subscription_id=subscription_id,
        tenant_id=tenant_id,
        region=profile.region,
    )
    checks.verify_source(
        source_commit=str(context["source_commit"]),
        repository=args.repository,
        apply=True,
    )
    current_source = (
        str(context["source_commit"])
        if checks.source_evidence is not None
        else _capture(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            timeout=30,
            reason="Foundation source revision is unavailable",
        ).strip()
    )
    if current_source != context["source_commit"]:
        raise ValueError("Foundation review source does not match the active checkout")
    claim = load_apply_claim(claim_path, review=review, profile=profile)
    existing_receipt: dict[str, object] | None = None
    if receipt_path.exists():
        if claim is None:
            raise ValueError("Foundation apply receipt is missing its immutable claim")
        existing_receipt = load_apply_receipt(
            receipt_path,
            review=review,
            profile=profile,
        )
        if (plan_directory / "foundation-state-handoff-receipt.json").exists():
            _reobserve_completed_foundation(
                plan_directory=plan_directory,
                review=review,
                receipt=existing_receipt,
            )
            return existing_receipt
    if existing_receipt is None and args.resume_verification:
        if claim is None:
            raise ValueError("Foundation verification resume requires an existing apply claim")
    elif existing_receipt is None and claim is not None:
        raise ValueError("Foundation apply claim already exists; only verification may resume")
    snapshot = _prepare_verified_snapshot(
        plan_directory=plan_directory,
        offline_kit=_absolute(args.offline_kit),
        release_root=_absolute(args.release_root),
        bundle_public_key=_absolute(args.bundle_public_key),
        context=context,
    )
    try:
        environment = _terraform_environment(
            data_dir=snapshot.data_dir,
            cli_config=snapshot.cli_config,
            subscription_id=subscription_id,
            tenant_id=tenant_id,
        )
        _required(
            [
                str(snapshot.terraform),
                "init",
                "-backend=false",
                "-input=false",
                "-lockfile=readonly",
            ],
            cwd=snapshot.infra_root,
            env=environment,
            timeout=300,
            reason="Foundation apply provider initialization failed",
        )
        if existing_receipt is None and not args.resume_verification:
            recheck_foundation_vm(
                repository_root=repository_root,
                variables_file=plan_directory / ".foundation-apply-input.json",
                evidence_directory=plan_directory,
            )
            claim = _claim(review=review, target_binding=profile.target_binding)
            # SKU, image, quota and human-identity reads may outlive the plan. Revalidate
            # the exact bytes and time window after those reads, before any durable claim.
            verify_foundation_plan(
                directory=plan_directory,
                profile=profile,
                expected_review_digest=args.expected_review_digest,
                require_unexpired=True,
            )
            write_private_output(
                claim_path,
                json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
            )
            _required(
                [
                    str(snapshot.terraform),
                    "apply",
                    "-input=false",
                    "-no-color",
                    str(plan_directory / PLAN_NAME),
                ],
                cwd=snapshot.infra_root,
                env=environment,
                timeout=args.timeout_seconds,
                reason="Foundation exact apply failed; automatic retry is blocked",
            )
        observed_receipt = _verify_foundation_effect(
            snapshot=snapshot,
            environment=environment,
            plan_directory=plan_directory,
            review=review,
            normalized_variables=plan_directory / ".foundation-apply-input.json",
        )
        if existing_receipt is not None:
            require_same_effect(existing_receipt, observed_receipt)
            return existing_receipt
        write_private_output(
            receipt_path,
            json.dumps(observed_receipt, sort_keys=True, separators=(",", ":")) + "\n",
        )
        return observed_receipt
    finally:
        snapshot.cleanup()
        (plan_directory / ".foundation-apply-input.json").unlink(missing_ok=True)


class VerifiedSnapshot:
    """Authenticated execution files plus the persistent local-state root."""

    def __init__(
        self,
        *,
        temporary: TemporaryDirectory[str],
        terraform: Path,
        mirror: Path,
        infra_root: Path,
        cli_config: Path,
        data_dir: Path,
    ) -> None:
        self._temporary = temporary
        self.terraform = terraform
        self.mirror = mirror
        self.infra_root = infra_root
        self.cli_config = cli_config
        self.data_dir = data_dir

    def cleanup(self) -> None:
        """Remove only the fresh authenticated tool snapshot, retaining local state."""

        self._temporary.cleanup()


def _prepare_verified_snapshot(
    *,
    plan_directory: Path,
    offline_kit: Path,
    release_root: Path,
    bundle_public_key: Path,
    context: dict[str, object],
) -> VerifiedSnapshot:
    release_key = _read_regular(release_root, max_bytes=65_536)
    bundle_key = _read_regular(bundle_public_key, max_bytes=65_536)
    verification = verify_offline_kit(
        offline_kit,
        release_root_pem=release_key,
        cli_version=__version__,
        platform_tag=_platform_tag(),
    )
    if verification.manifest_digest != context["offline_manifest_digest"]:
        raise ValueError("Foundation apply offline kit does not match the plan")
    temporary = TemporaryDirectory(prefix="foundation-apply-", dir=plan_directory)
    temporary_root = Path(temporary.name)
    artifacts = materialize_verified_artifacts(
        offline_kit, verification, temporary_root / "artifacts"
    )
    extracted = extract_bundle_archive(artifacts.deployment_bundle, temporary_root / "bundle")
    bundle_verification = verify_bundle(
        extracted,
        public_key_pem=bundle_key,
        cli_version=__version__,
    )
    if bundle_verification.manifest_digest != context["deployment_bundle_digest"]:
        temporary.cleanup()
        raise ValueError("Foundation apply deployment bundle does not match the plan")
    source_root = extracted / "infra/genesis-foundation"
    provider_lock = source_root / ".terraform.lock.hcl"
    if hashlib.sha256(provider_lock.read_bytes()).hexdigest() != context["provider_lock_digest"]:
        temporary.cleanup()
        raise ValueError("Foundation apply provider lock does not match the plan")
    terraform_digest = dict(verification.file_digests)[verification.terraform_binary]
    if terraform_digest != context["terraform_digest"]:
        temporary.cleanup()
        raise ValueError("Foundation apply Terraform binary does not match the plan")
    persistent_bundle = plan_directory / "foundation-apply-bundle"
    if persistent_bundle.exists():
        candidates = [entry for entry in persistent_bundle.iterdir() if entry.is_dir()]
        if len(candidates) != 1:
            temporary.cleanup()
            raise ValueError("Foundation apply persistent bundle is invalid")
        persistent_root = candidates[0]
        persisted = verify_bundle(
            persistent_root,
            public_key_pem=bundle_key,
            cli_version=__version__,
        )
        if persisted.manifest_digest != context["deployment_bundle_digest"]:
            temporary.cleanup()
            raise ValueError("Foundation apply persistent bundle changed")
    else:
        persistent_bundle.mkdir(mode=0o700)
        persistent_root = persistent_bundle / extracted.name
        shutil.copytree(extracted, persistent_root)
        directories = [
            persistent_bundle,
            *[path for path in persistent_bundle.rglob("*") if path.is_dir()],
        ]
        for directory in directories:
            directory.chmod(0o700)
        for file in (p for p in persistent_bundle.rglob("*") if p.is_file()):
            file.chmod(0o600)
    infra_root = persistent_root / "infra/genesis-foundation"
    cli_config = temporary_root / "offline.tfrc"
    _exclusive_text(
        cli_config,
        "provider_installation {\n"
        "  filesystem_mirror {\n"
        f'    path = "{artifacts.provider_mirror}"\n'
        '    include = ["*/*"]\n'
        "  }\n"
        "  direct {\n"
        '    exclude = ["*/*"]\n'
        "  }\n"
        "}\n",
    )
    data_dir = temporary_root / "terraform-data"
    data_dir.mkdir(mode=0o700)
    return VerifiedSnapshot(
        temporary=temporary,
        terraform=artifacts.terraform_binary,
        mirror=artifacts.provider_mirror,
        infra_root=infra_root,
        cli_config=cli_config,
        data_dir=data_dir,
    )


def _foundation_review(directory: Path) -> dict[str, object]:
    review = load_json_object(
        read_private_bytes(directory / REVIEW_NAME, max_bytes=65_536),
        label="Foundation review",
    )
    digest = review.get("review_digest")
    without_digest = {key: value for key, value in review.items() if key != "review_digest"}
    if not isinstance(digest, str) or canonical_digest(without_digest) != digest:
        raise ValueError("Foundation review digest is invalid")
    return review


def _foundation_target(
    *,
    variables_path: Path,
    profile_path: Path,
    destination: Path,
    expected_context: dict[str, object],
) -> tuple[str, str]:
    profile = load_profile(profile_path)
    destination.unlink(missing_ok=True)
    context = snapshot_foundation_input(
        variables_path,
        destination,
        expected_target_binding=profile.target_binding,
        expected_region=profile.region,
        expected_environment=profile.environment,
    )
    values = read_plan_input(destination)
    if canonical_digest(values) != expected_context["variables_digest"]:
        destination.unlink(missing_ok=True)
        raise ValueError("Foundation apply variables do not match the reviewed plan")
    return context.subscription_id, context.tenant_id


def _claim(*, review: dict[str, object], target_binding: str) -> dict[str, object]:
    actor = _capture(
        ["az", "account", "show", "--query", "{type:user.type,name:user.name}", "--output", "json"],
        cwd=Path.cwd(),
        timeout=30,
        reason="authenticated Foundation operator identity is unavailable",
    )
    user = json.loads(actor)
    if (
        not isinstance(user, dict)
        or user.get("type") != "user"
        or not isinstance(user.get("name"), str)
    ):
        raise ValueError("Foundation apply requires an authenticated human operator")
    actor_digest = hashlib.sha256(
        f"{target_binding}:{user['name'].casefold()}".encode()
    ).hexdigest()
    claimed_at = _utc_now().replace(microsecond=0).isoformat()
    return {
        "schema_version": "fdai.genesis-foundation-apply-claim.v1",
        "state": "applying",
        "review_digest": review["review_digest"],
        "plan_digest": review["plan_digest"],
        "target_binding": target_binding,
        "actor_digest": actor_digest,
        "idempotency_key": canonical_digest(
            {"target_binding": target_binding, "plan_digest": review["plan_digest"]}
        ),
        "claimed_at": claimed_at,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _verify_foundation_effect(
    *,
    snapshot: VerifiedSnapshot,
    environment: dict[str, str],
    plan_directory: Path,
    review: dict[str, object],
    normalized_variables: Path,
) -> dict[str, object]:
    handoff_raw = _capture(
        [str(snapshot.terraform), "output", "-json", "private_handoff"],
        cwd=snapshot.infra_root,
        env=environment,
        timeout=120,
        reason="Foundation private handoff output is unavailable",
    )
    handoff = json.loads(handoff_raw)
    _validate_handoff(handoff, review)
    handoff_path = plan_directory / HANDOFF_NAME
    if handoff_path.exists():
        retained_handoff = load_json_object(
            read_private_bytes(handoff_path, max_bytes=1_048_576),
            label="Foundation private handoff",
        )
        if retained_handoff != handoff:
            raise ValueError("Foundation private handoff changed during re-observation")
    else:
        write_private_output(handoff_path, handoff_raw.rstrip() + "\n")
    _independent_readback(handoff, plan_directory)
    no_change = run_with_heartbeat(
        [
            str(snapshot.terraform),
            "plan",
            "-input=false",
            "-no-color",
            "-detailed-exitcode",
            f"-var-file={normalized_variables}",
        ],
        cwd=snapshot.infra_root,
        env=environment,
        timeout=900,
        capture_output=True,
        umask=0o077,
    )
    if no_change.returncode != 0:
        raise ValueError("Foundation post-apply plan is not zero-change")
    state_path = snapshot.infra_root / "terraform.tfstate"
    state = read_private_bytes(state_path, max_bytes=64 * 1024 * 1024)
    completed = _utc_now().replace(microsecond=0).isoformat()
    review_context = _object(review["context"], "Foundation review context")
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-foundation-apply-receipt.v1",
        "state": "applied",
        "review_digest": review["review_digest"],
        "plan_digest": review["plan_digest"],
        "target_binding": review_context["target_binding"],
        "source_commit": review_context["source_commit"],
        "state_digest": hashlib.sha256(state).hexdigest(),
        "state_ref": str(state_path.relative_to(plan_directory)),
        "handoff_digest": canonical_digest(handoff),
        "control_plane_readback_verified": True,
        "zero_change_verified": True,
        "remote_backend_authority_verified": False,
        "runner_attested": False,
        "mutation_performed": True,
        "subscription_ready": False,
        "completed_at": completed,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    return receipt


def _reobserve_completed_foundation(
    *,
    plan_directory: Path,
    review: dict[str, object],
    receipt: Mapping[str, object],
) -> None:
    handoff = load_json_object(
        read_private_bytes(plan_directory / HANDOFF_NAME, max_bytes=1_048_576),
        label="Foundation private handoff",
    )
    _validate_handoff(handoff, review)
    if canonical_digest(handoff) != receipt.get("handoff_digest"):
        raise ValueError("Foundation private handoff differs from its exact receipt")
    _independent_readback(handoff, plan_directory)


def _validate_handoff(handoff: object, review: dict[str, object]) -> None:
    if not isinstance(handoff, dict):
        raise ValueError("Foundation private handoff is invalid")
    required = {
        "terraform_root",
        "source_commit",
        "run_digest",
        "subscription_id",
        "tenant_id",
        "region",
        "app_resource_group",
        "ops",
        "state",
        "runner",
        "access",
    }
    if set(handoff) != required or handoff.get("terraform_root") != "infra/genesis-foundation":
        raise ValueError("Foundation private handoff fields are invalid")
    context = _object(review["context"], "Foundation review context")
    if handoff.get("source_commit") != context["source_commit"]:
        raise ValueError("Foundation private handoff source is invalid")
    for key in ("app_resource_group", "ops", "state", "runner", "access"):
        if not isinstance(handoff.get(key), dict):
            raise ValueError("Foundation private handoff component is invalid")
    runner = _object(handoff["runner"], "Foundation runner handoff")
    access = _object(handoff["access"], "Foundation access handoff")
    parallelism = runner.get("parallelism")
    if (
        not isinstance(runner.get("vm_id"), str)
        or not isinstance(runner.get("admin_username"), str)
        or type(parallelism) is not int
        or not 1 <= parallelism <= 5
        or not isinstance(runner.get("ssh_key_digest"), str)
        or _DIGEST.fullmatch(str(runner["ssh_key_digest"])) is None
        or type(runner.get("public_egress")) is not bool
    ):
        raise ValueError("Foundation runner access handoff is invalid")
    if access.get("method") == "bastion":
        if not isinstance(access.get("bastion_name"), str) or not isinstance(
            access.get("bastion_id"), str
        ):
            raise ValueError("Foundation Bastion handoff is invalid")
    elif (
        access.get("method") != "external"
        or access.get("bastion_name") is not None
        or access.get("bastion_id") is not None
    ):
        raise ValueError("Foundation access handoff is invalid")


def _independent_readback(handoff: dict[str, object], cwd: Path) -> None:
    app = _object(handoff["app_resource_group"], "Foundation application group")
    ops = _object(handoff["ops"], "Foundation operations handoff")
    state = _object(handoff["state"], "Foundation state handoff")
    runner = _object(handoff["runner"], "Foundation runner handoff")
    access = _object(handoff["access"], "Foundation access handoff")
    group = json.loads(
        _capture(
            ["az", "group", "show", "--ids", str(app["id"]), "--output", "json"],
            cwd=cwd,
            timeout=60,
            reason="Foundation application group readback failed",
        )
    )
    account = json.loads(
        _capture(
            [
                "az",
                "resource",
                "show",
                "--ids",
                str(state["account_id"]),
                "--api-version",
                "2023-05-01",
                "--output",
                "json",
            ],
            cwd=cwd,
            timeout=60,
            reason="Foundation state account readback failed",
        )
    )
    properties = account.get("properties") if isinstance(account, dict) else None
    if (
        not isinstance(group, dict)
        or str(group.get("id", "")).casefold() != str(app["id"]).casefold()
        or not isinstance(properties, dict)
        or properties.get("publicNetworkAccess") != "Disabled"
        or properties.get("allowSharedKeyAccess") is not False
        or properties.get("minimumTlsVersion") != "TLS1_2"
    ):
        raise ValueError("Foundation group or state protection readback failed")
    for container in (state["container_name"], state["plan_container"]):
        container_id = f"{state['account_id']}/blobServices/default/containers/{container}"
        _capture(
            [
                "az",
                "resource",
                "show",
                "--ids",
                container_id,
                "--api-version",
                "2023-05-01",
                "--output",
                "none",
            ],
            cwd=cwd,
            timeout=60,
            reason="Foundation private container readback failed",
        )
    vm = json.loads(
        _capture(
            [
                "az",
                "vm",
                "show",
                "--resource-group",
                str(ops["resource_group_name"]),
                "--name",
                str(runner["vm_name"]),
                "--output",
                "json",
            ],
            cwd=cwd,
            timeout=60,
            reason="Foundation runner VM readback failed",
        )
    )
    vm_object = _object(vm, "Foundation runner VM")
    identity = _object(vm_object.get("identity"), "Foundation runner VM identity")
    identities = identity.get("userAssignedIdentities")
    if (
        vm_object.get("provisioningState") != "Succeeded"
        or str(vm_object.get("id", "")).casefold() != str(runner["vm_id"]).casefold()
        or not isinstance(identities, dict)
        or not any(key.casefold() == str(runner["identity_id"]).casefold() for key in identities)
    ):
        raise ValueError("Foundation runner identity readback failed")
    if access.get("method") == "bastion":
        bastion_id = access.get("bastion_id")
        if not isinstance(bastion_id, str) or not bastion_id:
            raise ValueError("Foundation Bastion handoff is incomplete")
        bastion = json.loads(
            _capture(
                [
                    "az",
                    "network",
                    "bastion",
                    "show",
                    "--ids",
                    bastion_id,
                    "--query",
                    "{id:id,name:name,provisioningState:provisioningState,sku:sku.name,tunneling:enableTunneling}",
                    "--output",
                    "json",
                    "--only-show-errors",
                ],
                cwd=cwd,
                timeout=60,
                reason="Foundation Bastion readback failed",
            )
        )
        if (
            not isinstance(bastion, dict)
            or str(bastion.get("id", "")).casefold() != bastion_id.casefold()
            or bastion.get("provisioningState") != "Succeeded"
            or bastion.get("sku") != "Standard"
            or bastion.get("tunneling") is not True
        ):
            raise ValueError("Foundation Bastion native-tunnel readback failed")
    elif access.get("method") != "external":
        raise ValueError("Foundation access method is invalid")


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} is invalid")
    return {key: item for key, item in value.items()}


def _terraform_environment(
    *, data_dir: Path, cli_config: Path, subscription_id: str, tenant_id: str
) -> dict[str, str]:
    if any(
        key.startswith("TF_CLI_ARGS")
        or key in {"TF_WORKSPACE", "TF_DATA_DIR", "TF_CLI_CONFIG_FILE"}
        for key in os.environ
    ):
        raise ValueError("ambient Terraform control variables are not accepted")
    environment = dict(os.environ)
    environment.update(
        {
            "TF_DATA_DIR": str(data_dir),
            "TF_CLI_CONFIG_FILE": str(cli_config),
            "TF_IN_AUTOMATION": "1",
            "ARM_SUBSCRIPTION_ID": subscription_id,
            "ARM_TENANT_ID": tenant_id,
            "ARM_RESOURCE_PROVIDER_REGISTRATIONS": "none",
        }
    )
    return environment


def _platform_tag() -> str:
    machine = platform.machine().casefold()
    architecture = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }.get(machine)
    if sys.platform != "linux" or architecture is None:
        raise ValueError("Foundation apply supports Linux x86_64 or aarch64")
    return f"linux-{architecture}"


def _read_regular(path: Path, *, max_bytes: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat_is_regular(details.st_mode) or details.st_size > max_bytes:
            raise ValueError("Foundation trust input must be a bounded regular file")
        return stream.read(max_bytes + 1)


def stat_is_regular(mode: int) -> bool:
    """Return whether a descriptor mode denotes a regular file."""

    return stat.S_ISREG(mode)


def _exclusive_text(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


def _required(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    reason: str,
    env: Mapping[str, str] | None = None,
) -> None:
    completed = run_with_heartbeat(
        command,
        cwd=cwd,
        timeout=timeout,
        env=env,
        capture_output=True,
        umask=0o077,
    )
    if completed.returncode != 0:
        raise ValueError(reason)


def _capture(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    reason: str,
    env: Mapping[str, str] | None = None,
) -> str:
    completed = run_with_heartbeat(
        command,
        cwd=cwd,
        timeout=timeout,
        env=env,
        capture_output=True,
        umask=0o077,
    )
    if completed.returncode != 0:
        raise ValueError(reason)
    return completed.stdout


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017 - Python 3.10 entrypoint


def _print(result: Mapping[str, object], output: str) -> None:
    if output == "json":
        safe = {
            key: value
            for key, value in result.items()
            if key not in {"runner_image_id", "target_binding", "state_ref"}
        }
        print(json.dumps(safe, sort_keys=True, separators=(",", ":")))
    else:
        print(
            "Foundation exact apply verified; runner attestation and remote state remain required"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run exact Foundation apply or verification resume with stable failures."""

    args = _parser().parse_args(argv)
    try:
        result = _execute(args)
        _print(result, args.output)
        return 0
    except (
        CheckError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        reason = exc.reason_code if isinstance(exc, CheckError) else str(exc)
        print(f"genesis-foundation-apply: {reason}", file=sys.stderr)
        return exc.exit_code if isinstance(exc, CheckError) else 3
    finally:
        (_absolute(args.plan_directory) / ".foundation-apply-input.json").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
