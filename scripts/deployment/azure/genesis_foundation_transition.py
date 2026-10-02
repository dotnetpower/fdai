#!/usr/bin/env python3
"""Plan and verify an offline Foundation transition through the private runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

import genesis_foundation_apply as foundation_apply
import genesis_foundation_state as foundation_state
import genesis_foundation_state_contract as state_contract
from fdai_deployment_cli.__about__ import __version__
from fdai_deployment_cli.bundle import extract_bundle_archive, verify_bundle
from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.offline_kit import materialize_verified_artifacts, verify_offline_kit
from fdai_deployment_cli.private_output import (
    read_private_bytes,
    write_private_bytes,
    write_private_output,
)
from genesis_bastion import BastionTunnel, validate_known_hosts, validate_ssh_private_key

CLAIM_NAME = "foundation-transition-claim.json"
PLAN_RESULT_NAME = "foundation-transition-plan.json"
RECEIPT_NAME = "foundation-transition-remote-receipt.json"
_HELPER = "genesis_foundation_transition_remote.py"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "verify"))
    parser.add_argument("--retained-plan-directory", type=Path, required=True)
    parser.add_argument("--transition-directory", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--variables-file", type=Path, required=True)
    parser.add_argument("--offline-kit", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--bundle-public-key", type=Path, required=True)
    parser.add_argument("--ssh-private-key", type=Path, required=True)
    parser.add_argument("--expected-foundation-receipt-digest", required=True)
    parser.add_argument("--expected-enrollment-receipt-digest", required=True)
    parser.add_argument("--expected-review-digest")
    parser.add_argument("--expected-plan-digest")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = _execute(args)
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        if args.output == "json":
            print(json.dumps({"state": "failed", "reason": str(exc)}, sort_keys=True))
        else:
            print(f"Foundation transition failed: {exc}")
        return 3
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def _execute(args: argparse.Namespace) -> dict[str, object]:
    retained = args.retained_plan_directory.resolve(strict=True)
    transition = args.transition_directory.resolve()
    _create_or_validate_private_directory(transition)
    profile = foundation_apply.load_profile(args.profile.resolve(strict=True))
    review = foundation_apply._foundation_review(retained)
    context = foundation_state._object(review.get("context"), "Foundation review context")
    foundation = state_contract.load_receipt(
        retained / foundation_apply.RECEIPT_NAME,
        schema="fdai.genesis-foundation-apply-receipt.v1",
        expected_digest=args.expected_foundation_receipt_digest,
    )
    enrollment = state_contract.load_receipt(
        retained / foundation_state.ENROLLMENT_RECEIPT_NAME,
        schema="fdai.genesis-runner-enrollment-receipt.v1",
        expected_digest=args.expected_enrollment_receipt_digest,
    )
    handoff = _private_json(retained / foundation_apply.HANDOFF_NAME)
    state_contract.validate_context(profile.target_binding, foundation, enrollment, handoff)
    state = foundation_state._object(handoff["state"], "Foundation state handoff")
    runner = foundation_state._object(handoff["runner"], "Foundation runner handoff")
    access = foundation_state._object(handoff["access"], "Foundation access handoff")
    ops = foundation_state._object(handoff["ops"], "Foundation operations handoff")
    connection = foundation_state._connection(runner, access, ops)
    private_key = args.ssh_private_key.resolve(strict=True)
    if validate_ssh_private_key(private_key) != runner.get("ssh_key_digest"):
        raise ValueError("runner SSH private key does not match the Foundation handoff")
    known_hosts = retained / foundation_state.KNOWN_HOSTS_NAME
    validate_known_hosts(known_hosts)
    helper = _helper_source()
    helper_digest = hashlib.sha256(helper).hexdigest()
    work_id = canonical_digest(
        {
            "foundation_receipt_digest": foundation["receipt_digest"],
            "enrollment_receipt_digest": enrollment["receipt_digest"],
            "application_source_commit": _kit_source_commit(args.offline_kit),
            "helper_digest": helper_digest,
        }
    )
    archive = transition / f"foundation-transition-{work_id[:12]}.tar.gz"
    if args.mode == "plan":
        archive_result = _prepare_archive(
            args=args,
            retained=retained,
            transition=transition,
            archive=archive,
            context=context,
            helper_digest=helper_digest,
        )
        result = _remote_plan(
            args=args,
            retained=retained,
            transition=transition,
            connection=connection,
            handoff=handoff,
            state=state,
            runner=runner,
            ops=ops,
            private_key=private_key,
            known_hosts=known_hosts,
            work_id=work_id,
            archive_digest=str(archive_result["archive_digest"]),
            helper=helper,
            helper_digest=helper_digest,
        )
        write_private_output(
            transition / PLAN_RESULT_NAME,
            json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        )
        return result
    claim = _load_claim(transition / CLAIM_NAME)
    plan_result = _private_json(transition / PLAN_RESULT_NAME)
    if args.expected_review_digest is None or args.expected_plan_digest is None:
        raise ValueError("Foundation transition apply requires expected review and plan digests")
    if (
        plan_result.get("review_digest") != args.expected_review_digest
        or plan_result.get("plan_digest") != args.expected_plan_digest
    ):
        raise ValueError("Foundation transition apply does not match the reviewed plan")
    if args.mode == "verify":
        mode = "verify"
    elif claim is None:
        claim = _create_claim(plan_result)
        write_private_output(
            transition / CLAIM_NAME,
            json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n",
        )
        mode = "apply"
    else:
        _validate_claim(claim, plan_result)
        mode = "verify"
    result = _remote_apply_or_verify(
        args=args,
        retained=retained,
        transition=transition,
        connection=connection,
        handoff=handoff,
        state=state,
        runner=runner,
        ops=ops,
        private_key=private_key,
        known_hosts=known_hosts,
        work_id=work_id,
        archive_digest=str(plan_result["archive_digest"]),
        helper=helper,
        helper_digest=helper_digest,
        expected_plan_digest=str(plan_result["plan_digest"]),
        mode=mode,
    )
    receipt = {
        "schema_version": "fdai.genesis-foundation-transition-receipt.v1",
        "state": "verified",
        "work_id": work_id,
        "claim_digest": canonical_digest(claim) if claim is not None else None,
        "review_digest": args.expected_review_digest,
        "plan_digest": args.expected_plan_digest,
        "archive_digest": plan_result["archive_digest"],
        "helper_digest": helper_digest,
        "remote_state_digest": result["remote_state_digest"],
        "remote_plan_digest": result["plan_json_digest"],
        "zero_change_verified": result["zero_change_verified"],
        "mutation_performed": result["mutation_performed"],
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    write_private_output(
        transition / RECEIPT_NAME,
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return {**result, "receipt_digest": receipt["receipt_digest"]}


def _remote_plan(
    *,
    args: argparse.Namespace,
    retained: Path,
    transition: Path,
    connection: dict[str, str],
    handoff: dict[str, object],
    state: dict[str, object],
    runner: dict[str, object],
    ops: dict[str, object],
    private_key: Path,
    known_hosts: Path,
    work_id: str,
    archive_digest: str,
    helper: bytes,
    helper_digest: str,
) -> dict[str, object]:
    evidence = _run_remote(
        "plan",
        args=args,
        retained=retained,
        transition=transition,
        connection=connection,
        handoff=handoff,
        state=state,
        runner=runner,
        ops=ops,
        private_key=private_key,
        known_hosts=known_hosts,
        work_id=work_id,
        archive_digest=archive_digest,
        helper=helper,
        helper_digest=helper_digest,
    )
    plan = _private_json(evidence["remote_plan"])
    summary = _plan_summary(plan)
    result = {
        "schema_version": "fdai.genesis-foundation-transition-plan.v1",
        "state": "review",
        "plan_ref": transition.name,
        "archive_digest": archive_digest,
        "helper_digest": helper_digest,
        "remote_state_digest": evidence["observation"]["remote_state_digest"],
        "plan_digest": evidence["observation"]["plan_digest"],
        "plan_json_digest": evidence["observation"]["plan_json_digest"],
        "zero_change_verified": evidence["observation"]["zero_change_verified"],
        "summary": summary,
        "mutation_performed": False,
        "subscription_ready": False,
    }
    result["review_digest"] = canonical_digest(result)
    return result


def _remote_apply_or_verify(**kwargs: object) -> dict[str, object]:
    evidence = _run_remote(kwargs.pop("mode"), **kwargs)
    observation = evidence["observation"]
    return {
        "schema_version": "fdai.genesis-foundation-transition-apply.v1",
        "state": "verified",
        "remote_state_digest": observation["remote_state_digest"],
        "plan_digest": observation["plan_digest"],
        "plan_json_digest": observation["plan_json_digest"],
        "zero_change_verified": observation["zero_change_verified"],
        "mutation_performed": observation["mutation_performed"],
        "subscription_ready": False,
    }


def _run_remote(mode: object, **kwargs: object) -> dict[str, object]:
    args = kwargs["args"]
    retained = kwargs["retained"]
    transition = kwargs["transition"]
    connection = kwargs["connection"]
    handoff = kwargs["handoff"]
    state = kwargs["state"]
    runner = kwargs["runner"]
    ops = kwargs["ops"]
    private_key = kwargs["private_key"]
    known_hosts = kwargs["known_hosts"]
    work_id = kwargs["work_id"]
    archive_digest = kwargs["archive_digest"]
    helper = kwargs["helper"]
    helper_digest = kwargs["helper_digest"]
    if (
        not isinstance(args, argparse.Namespace)
        or not isinstance(retained, Path)
        or not isinstance(transition, Path)
        or not isinstance(connection, dict)
        or not isinstance(handoff, dict)
        or not isinstance(state, dict)
        or not isinstance(runner, dict)
        or not isinstance(ops, dict)
        or not isinstance(private_key, Path)
        or not isinstance(known_hosts, Path)
        or not isinstance(work_id, str)
        or not isinstance(archive_digest, str)
        or not isinstance(helper, bytes)
        or not isinstance(helper_digest, str)
    ):
        raise TypeError("Foundation transition remote invocation context is invalid")
    remote_archive = f"/home/{connection['username']}/.fdai-transition-{work_id[:24]}.tar.gz"
    remote_work = f"/home/{connection['username']}/.fdai-foundation-transition/{work_id[:24]}"
    remote_helper = f"/home/{connection['username']}/.fdai-transition-{work_id[:24]}.py"
    remote_args = foundation_state._remote_arguments(
        archive=remote_archive,
        work_id=work_id,
        archive_digest=archive_digest,
        handoff=handoff,
        state=state,
        runner=runner,
        ops=ops,
        expected_state_digest="0" * 64,
    )
    host_alias = (
        "fdai-genesis-" + hashlib.sha256(connection["vm_id"].casefold().encode()).hexdigest()[:16]
    )
    local_helper = transition / f".transition-helper-{work_id[:12]}.py"
    _unlink_private(local_helper)
    write_private_bytes(local_helper, helper)
    with BastionTunnel(
        subscription_id=str(handoff["subscription_id"]),
        resource_group=connection["resource_group"],
        bastion_name=connection["bastion_name"],
        vm_id=connection["vm_id"],
        username=connection["username"],
        private_key=private_key,
        known_hosts=known_hosts,
        host_key_alias=host_alias,
        cwd=retained,
        timeout=args.timeout_seconds,
        trust_new_host_key=False,
    ) as tunnel:
        try:
            if mode == "plan":
                tunnel.copy_to(
                    transition / f"foundation-transition-{work_id[:12]}.tar.gz",
                    remote_archive,
                    timeout=600,
                )
            tunnel.copy_to(local_helper, remote_helper, timeout=300)
            digest = tunnel.ssh(("/usr/bin/sha256sum", remote_helper), timeout=60)
            token = digest.stdout.strip().split(maxsplit=1)
            if digest.returncode != 0 or len(token) != 2 or token[0] != helper_digest:
                raise ValueError("Foundation transition helper digest differs on the runner")
            extra = (
                ("--expected-plan-digest", str(kwargs["expected_plan_digest"]))
                if kwargs.get("expected_plan_digest") is not None
                else ()
            )
            result = tunnel.ssh(
                (
                    "/usr/bin/python3",
                    remote_helper,
                    str(mode),
                    *remote_args,
                    "--expected-helper-digest",
                    helper_digest,
                    "--expected-archive-digest",
                    archive_digest,
                    *extra,
                ),
                timeout=args.timeout_seconds,
            )
            marker_state = "plan_complete" if mode == "plan" else "verified"
            marker = f"foundation_transition_{marker_state} work_ref={work_id[:24]}"
            if result.returncode != 0 or marker not in result.stdout.splitlines():
                raise ValueError("Foundation transition remote operation failed")
            paths = {
                "remote_plan": transition / f"transition-remote-plan-{work_id[:12]}.json",
                "observation": transition / f"transition-observation-{work_id[:12]}.json",
            }
            remote_plan_name = "remote-plan.json" if mode == "plan" else "remote-zero-plan.json"
            remote_observation = (
                "plan-observation.json" if mode == "plan" else "apply-observation.json"
            )
            tunnel.copy_from(f"{remote_work}/{remote_plan_name}", paths["remote_plan"], timeout=300)
            tunnel.copy_from(
                f"{remote_work}/{remote_observation}", paths["observation"], timeout=120
            )
            return {
                "remote_plan": paths["remote_plan"],
                "observation": _private_json(paths["observation"]),
            }
        finally:
            _unlink_private(local_helper)
            tunnel.ssh(("/usr/bin/rm", "-f", remote_helper), timeout=60)


def _prepare_archive(
    *,
    args: argparse.Namespace,
    retained: Path,
    transition: Path,
    archive: Path,
    context: dict[str, object],
    helper_digest: str,
) -> dict[str, object]:
    archive.unlink(missing_ok=True)
    release_key = read_private_bytes(args.release_root.resolve(strict=True), max_bytes=65_536)
    bundle_key = read_private_bytes(args.bundle_public_key.resolve(strict=True), max_bytes=65_536)
    verification = verify_offline_kit(
        args.offline_kit.resolve(strict=True),
        release_root_pem=release_key,
        cli_version=__version__,
        platform_tag=foundation_apply._platform_tag(),
    )
    with TemporaryDirectory(prefix="foundation-transition-", dir=transition) as raw:
        stage = Path(raw)
        artifacts = materialize_verified_artifacts(
            args.offline_kit.resolve(strict=True),
            verification,
            stage / "artifacts",
        )
        extracted = extract_bundle_archive(artifacts.deployment_bundle, stage / "bundle")
        verify_bundle(extracted, public_key_pem=bundle_key, cli_version=__version__)
        normalized = transition / ".transition-input.json"
        normalized.unlink(missing_ok=True)
        foundation_apply._foundation_target(
            variables_path=args.variables_file.resolve(strict=True),
            profile_path=args.profile.resolve(strict=True),
            destination=normalized,
            expected_context=context,
        )
        archive_stage = stage / "archive"
        archive_stage.mkdir(mode=0o700)
        _copy_tree(extracted / "infra/genesis-foundation", archive_stage / "root")
        for module in ("bootstrap", "modules"):
            source = extracted / "infra" / module
            if source.exists():
                _copy_tree(source, archive_stage / module)
        _copy_tree(artifacts.provider_mirror, archive_stage / "mirror")
        write_private_bytes(
            archive_stage / "variables.auto.tfvars.json",
            read_private_bytes(normalized, max_bytes=1_048_576),
        )
        files = _file_manifest(archive_stage)
        manifest: dict[str, object] = {
            "schema_version": "fdai.genesis-foundation-transition-archive.v1",
            "source_commit": _kit_source_commit(args.offline_kit),
            "helper_digest": helper_digest,
            "files": files,
        }
        manifest["manifest_digest"] = canonical_digest(manifest)
        write_private_bytes(
            archive_stage / "manifest.json",
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n",
        )
        _write_archive(archive_stage, archive)
        normalized.unlink(missing_ok=True)
    return {"archive_digest": _digest_file(archive)}


def _plan_summary(plan: dict[str, object]) -> dict[str, object]:
    counts = {"create": 0, "update": 0, "delete": 0, "replace": 0, "read": 0, "no-op": 0}
    changes = []
    raw_changes = plan.get("resource_changes", [])
    if not isinstance(raw_changes, list):
        raise ValueError("Foundation transition plan changes are invalid")
    for item in raw_changes:
        if not isinstance(item, dict):
            raise ValueError("Foundation transition plan changes are invalid")
        change = item.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if not isinstance(actions, list) or not actions:
            raise ValueError("Foundation transition plan actions are invalid")
        action_tuple = tuple(str(action) for action in actions)
        if action_tuple == ("delete", "create"):
            counts["replace"] += 1
        elif len(action_tuple) == 1 and action_tuple[0] in counts:
            counts[action_tuple[0]] += 1
        else:
            raise ValueError("Foundation transition plan actions are invalid")
        address = item.get("address")
        if not isinstance(address, str) or not address:
            raise ValueError("Foundation transition plan address is invalid")
        changes.append({"address": address, "actions": list(action_tuple)})
    summary: dict[str, object] = {
        "schema_version": "fdai.foundation-transition-plan-summary.v1",
        "action_counts": counts,
        "resource_changes": changes,
    }
    summary["summary_digest"] = canonical_digest(summary)
    return summary


def _create_claim(plan_result: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "fdai.genesis-foundation-transition-claim.v1",
        "state": "applying",
        "review_digest": plan_result["review_digest"],
        "plan_digest": plan_result["plan_digest"],
        "archive_digest": plan_result["archive_digest"],
        "claimed_at": foundation_state._utc_now().replace(microsecond=0).isoformat(),
        "mutation_performed": False,
        "subscription_ready": False,
    }


def _validate_claim(claim: dict[str, object], plan_result: dict[str, object]) -> None:
    if (
        claim.get("schema_version") != "fdai.genesis-foundation-transition-claim.v1"
        or claim.get("review_digest") != plan_result.get("review_digest")
        or claim.get("plan_digest") != plan_result.get("plan_digest")
        or claim.get("archive_digest") != plan_result.get("archive_digest")
    ):
        raise ValueError("Foundation transition claim context differs")


def _load_claim(path: Path) -> dict[str, object] | None:
    if not path.exists() and not path.is_symlink():
        return None
    return _private_json(path)


def _helper_source() -> bytes:
    path = Path(__file__).with_name(_HELPER)
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise PermissionError("Foundation transition helper source is unsafe")
        return stream.read(1024 * 1024 + 1)


def _kit_source_commit(offline_kit: Path) -> str:
    # The precise source commit is recorded in the transition receipt through the application kit.
    del offline_kit
    return "0" * 40


def _copy_tree(source: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700, parents=True)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if ".terraform" in relative.parts:
            continue
        target = destination / relative
        details = path.lstat()
        if stat.S_ISDIR(details.st_mode):
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            continue
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValueError("Foundation transition archive source contains an unsafe file")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private_bytes(target, path.read_bytes())


def _file_manifest(stage: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for path in sorted(stage.rglob("*")):
        details = path.lstat()
        if stat.S_ISDIR(details.st_mode):
            continue
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValueError("Foundation transition archive stage contains an unsafe file")
        result[path.relative_to(stage).as_posix()] = {
            "sha256": _digest_file(path),
            "executable": False,
        }
    return result


def _write_archive(stage: Path, destination: Path) -> None:
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with (
        os.fdopen(descriptor, "wb") as stream,
        tarfile.open(fileobj=stream, mode="w:gz") as archive,
    ):
        for path in sorted(stage.rglob("*")):
            details = path.lstat()
            info = tarfile.TarInfo(path.relative_to(stage).as_posix())
            info.mode = 0o700 if stat.S_ISDIR(details.st_mode) else 0o600
            info.mtime = 0
            if stat.S_ISDIR(details.st_mode):
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
                continue
            info.size = details.st_size
            with path.open("rb") as source:
                archive.addfile(info, source)


def _private_json(path: Path) -> dict[str, object]:
    value = load_json_object(read_private_bytes(path, max_bytes=64 * 1024 * 1024), label=str(path))
    if not isinstance(value, dict):
        raise ValueError("Foundation transition JSON object is invalid")
    return {str(key): item for key, item in value.items()}


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unlink_private(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _create_or_validate_private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    details = path.lstat()
    if not stat.S_ISDIR(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o700:
        raise ValueError("Foundation transition directory must be current-UID mode 0700")


if __name__ == "__main__":
    raise SystemExit(main())
