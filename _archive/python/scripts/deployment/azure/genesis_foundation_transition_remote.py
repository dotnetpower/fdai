#!/usr/bin/env python3
"""Run one Foundation transition plan or verification on the private runner."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_WORK_REF = re.compile(r"[0-9a-f]{24}")
# The state migration owns 24-hex work directories in the same handoff base; transition
# evidence uses a distinct prefix so pruning never touches migration evidence.
_EVIDENCE_BASE = ".fdai-state-handoff"
_EVIDENCE_REF = re.compile(r"transition-[0-9a-f]{24}")
# Mirrors genesis_foundation_apply._bind_observed_public_ip_tags: policy-assigned values that the
# exact Foundation input cannot predict are bound from the applied state, within strict choices.
_OBSERVED_VARIABLES = "observed.tfvars.json"
_POLICY_TAGS = {"FirstPartyUsage": "/Unprivileged"}
_PUBLIC_IPS = (
    "module.bootstrap.azurerm_public_ip.bastion[0]",
    "module.bootstrap.azurerm_public_ip.nat[0]",
)
_RUNNER_VM = "module.bootstrap.azurerm_linux_virtual_machine.runner[0]"
_PATCH_MODES = ("ImageDefault", "AutomaticByPlatform")
_TRANSITION_FILE = re.compile(r"\.fdai-transfer-[0-9a-f]{24}-transition\.(?:tar\.gz|py)")
_AZURE_CLI = "/usr/bin/az"
_TERRAFORM = "/usr/local/bin/terraform"
_MAX_FILES = 4096
_MAX_BYTES = 1024 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "verify", "cleanup"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-digest", required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--state-account-id", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--account-name", required=True)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--backend-key", required=True)
    parser.add_argument("--expected-helper-digest", required=True)
    parser.add_argument("--expected-archive-digest", required=True)
    parser.add_argument("--expected-plan-digest")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        _validate(args)
        home = Path.home()
        base = home / ".fdai-foundation-transition"
        base.mkdir(mode=0o700, exist_ok=True)
        _require_directory(base)
        work = base / args.work_id[:24]
        if args.mode == "cleanup":
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(_evidence_directory(home, work.name), ignore_errors=True)
            args.archive.unlink(missing_ok=True)
            print(f"foundation_transition_cleanup_complete work_ref={args.work_id[:24]}")
            return 0
        if args.mode == "plan":
            if work.exists() or work.is_symlink():
                raise ValueError("Foundation transition work already exists")
            _prune_superseded(home, base, work_ref=work.name, archive=args.archive)
            work.mkdir(mode=0o700)
            digest = _extract_archive(args.archive, work)
            if digest != args.expected_archive_digest or digest != args.archive_digest:
                raise ValueError("Foundation transition archive digest differs")
            _verify_tree(work)
            # The verified extraction is the only copy later modes use.
            args.archive.unlink(missing_ok=True)
        else:
            _require_directory(work)
            _verify_tree(work, migrated=True)
        environment = _terraform_environment(work, args)
        _managed_identity_login(work, args, environment)
        root = work / "root"
        _terraform_init(root, environment, args)
        remote_state = _capture(
            (_TERRAFORM, "state", "pull"),
            cwd=root,
            env=environment,
            timeout=180,
            reason="Foundation transition remote state pull failed",
            max_bytes=64 * 1024 * 1024,
        )
        _require_managed_state(remote_state)
        _write_bytes(work / "remote-state.json", remote_state)
        if args.mode == "plan":
            result = _run_plan(root, work, environment, expect_zero=False)
            _write_observation(
                work / "plan-observation.json",
                args=args,
                remote_state=remote_state,
                plan_json=result.plan_json,
                plan_binary=result.plan_binary,
                zero_change=result.exit_code == 0,
                mutation_performed=False,
            )
            _publish_evidence(home, work, ("remote-plan.json", "plan-observation.json"))
            print(f"foundation_transition_plan_complete work_ref={args.work_id[:24]}")
            return 0
        if args.mode == "apply":
            plan_path = work / "transition.tfplan"
            if args.expected_plan_digest is None:
                raise ValueError("Foundation transition apply requires an expected plan digest")
            if _digest_file(plan_path) != args.expected_plan_digest:
                raise ValueError("Foundation transition plan digest differs before apply")
            _run(
                (_TERRAFORM, "apply", "-input=false", "-no-color", str(plan_path)),
                cwd=root,
                env=environment,
                timeout=1800,
                reason="Foundation transition apply failed; automatic retry is blocked",
            )
        # ``verify`` deliberately does not apply, even when the retained plan still has changes.
        after_state = _capture(
            (_TERRAFORM, "state", "pull"),
            cwd=root,
            env=environment,
            timeout=180,
            reason="Foundation transition post-apply state pull failed",
            max_bytes=64 * 1024 * 1024,
        )
        _require_managed_state(after_state)
        _write_bytes(work / "remote-state-after.json", after_state)
        result = _run_plan(root, work, environment, expect_zero=True)
        _write_observation(
            work / "apply-observation.json",
            args=args,
            remote_state=after_state,
            plan_json=result.plan_json,
            plan_binary=result.plan_binary,
            zero_change=True,
            mutation_performed=args.mode == "apply",
        )
        _publish_evidence(home, work, ("remote-zero-plan.json", "apply-observation.json"))
        print(f"foundation_transition_verified work_ref={args.work_id[:24]}")
        return 0
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        tarfile.TarError,
    ) as exc:
        print(f"fdai-foundation-transition: {exc}", file=sys.stderr)
        return 3


class _PlanResult:
    def __init__(self, *, exit_code: int, plan_binary: bytes, plan_json: bytes) -> None:
        self.exit_code = exit_code
        self.plan_binary = plan_binary
        self.plan_json = plan_json


def _bind_refreshed_observations(root: Path, work: Path, environment: dict[str, str]) -> None:
    """Bind policy-assigned values from a read-only refresh, never from a stale stored state.

    A tenant policy can change a resource after the Foundation apply recorded it. A refresh-only
    plan persists nothing, and its ``prior_state`` is the refreshed state.
    """

    refresh_plan = work / "refresh.tfplan"
    completed = subprocess.run(
        (
            _TERRAFORM,
            "plan",
            "-refresh-only",
            "-input=false",
            "-no-color",
            "-var-file=../variables.auto.tfvars.json",
            f"-out={refresh_plan}",
        ),
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=900,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("Foundation transition refresh failed")
    refreshed = _capture(
        (_TERRAFORM, "show", "-json", str(refresh_plan)),
        cwd=root,
        env=environment,
        timeout=180,
        reason="Foundation transition refresh inspection failed",
        max_bytes=64 * 1024 * 1024,
    )
    _write_json(work / _OBSERVED_VARIABLES, refreshed_policy_variables(refreshed))


def _run_plan(
    root: Path, work: Path, environment: dict[str, str], *, expect_zero: bool
) -> _PlanResult:
    _bind_refreshed_observations(root, work, environment)
    plan_path = work / ("remote-zero.tfplan" if expect_zero else "transition.tfplan")
    completed = subprocess.run(
        (
            _TERRAFORM,
            "plan",
            "-input=false",
            "-no-color",
            "-detailed-exitcode",
            "-var-file=../variables.auto.tfvars.json",
            f"-var-file=../{_OBSERVED_VARIABLES}",
            f"-out={plan_path}",
        ),
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=900,
        check=False,
    )
    if completed.returncode not in {0, 2}:
        raise ValueError("Foundation transition remote plan failed")
    if expect_zero and completed.returncode != 0:
        raise ValueError("Foundation transition verification plan is not zero-change")
    plan_json = _capture(
        (_TERRAFORM, "show", "-json", str(plan_path)),
        cwd=root,
        env=environment,
        timeout=180,
        reason="Foundation transition plan inspection failed",
        max_bytes=64 * 1024 * 1024,
    )
    _write_bytes(work / ("remote-zero-plan.json" if expect_zero else "remote-plan.json"), plan_json)
    return _PlanResult(
        exit_code=completed.returncode,
        plan_binary=plan_path.read_bytes(),
        plan_json=plan_json,
    )


def _write_observation(
    path: Path,
    *,
    args: argparse.Namespace,
    remote_state: bytes,
    plan_json: bytes,
    plan_binary: bytes,
    zero_change: bool,
    mutation_performed: bool,
) -> None:
    value = {
        "schema_version": "fdai.genesis-foundation-transition-observation.v1",
        "state": "verified",
        "work_id": args.work_id,
        "archive_digest": args.archive_digest,
        "helper_digest": args.expected_helper_digest,
        "remote_state_digest": state_identity_digest(remote_state),
        "plan_json_digest": hashlib.sha256(plan_json).hexdigest(),
        "plan_digest": hashlib.sha256(plan_binary).hexdigest(),
        "zero_change_verified": zero_change,
        "mutation_performed": mutation_performed,
        "subscription_ready": False,
    }
    _write_json(path, value)


def _validate(args: argparse.Namespace) -> None:
    digest_values = (
        args.archive_digest,
        args.work_id,
        args.expected_helper_digest,
        args.expected_archive_digest,
        *(value for value in (args.expected_plan_digest,) if value is not None),
    )
    if any(_DIGEST.fullmatch(value) is None for value in digest_values):
        raise ValueError("Foundation transition digest argument is invalid")
    if _GUID.fullmatch(args.subscription_id) is None or _GUID.fullmatch(args.tenant_id) is None:
        raise ValueError("Foundation transition target argument is invalid")


def _prune_superseded(home: Path, base: Path, *, work_ref: str, archive: Path) -> None:
    """Remove transition work and transfers that earlier attempts left behind.

    A new plan runs only after every earlier attempt is superseded: the local coordinator resumes
    an interrupted apply for the same inputs and refuses one for other inputs before planning.
    """

    for entry in base.iterdir():
        if entry.name == work_ref or _WORK_REF.fullmatch(entry.name) is None:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
    current = {archive.name, Path(__file__).name}
    for entry in home.iterdir():
        if entry.name in current or _TRANSITION_FILE.fullmatch(entry.name) is None:
            continue
        if entry.is_file() and not entry.is_symlink():
            entry.unlink()
    handoff = home / _EVIDENCE_BASE
    if handoff.is_dir() and not handoff.is_symlink():
        for entry in handoff.iterdir():
            if (
                entry.name == f"transition-{work_ref}"
                or _EVIDENCE_REF.fullmatch(entry.name) is None
            ):
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)


def state_identity_digest(state: bytes) -> str:
    """Digest the stored state identity, independent of Terraform's unordered check results."""

    value = json.loads(state)
    if not isinstance(value, dict):
        raise ValueError("Foundation transition remote state is empty or invalid")
    keys = ("version", "lineage", "serial", "resources", "outputs")
    return _canonical_digest({key: value.get(key) for key in keys})


def _require_managed_state(state: bytes) -> None:
    """Refuse to plan against an absent backend, which would recreate the whole Foundation."""

    try:
        value = json.loads(state)
    except ValueError as exc:
        raise ValueError("Foundation transition remote state is empty or invalid") from exc
    resources = value.get("resources") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("lineage"), str)
        or not value["lineage"]
        or not isinstance(resources, list)
        or not any(isinstance(item, dict) and item.get("mode") == "managed" for item in resources)
    ):
        raise ValueError("Foundation transition remote state is empty or invalid")


def _managed_instances(state: dict[str, object]) -> dict[str, dict[str, object]]:
    resources = state.get("resources")
    if not isinstance(resources, list):
        raise ValueError("Foundation transition remote state is empty or invalid")
    result: dict[str, dict[str, object]] = {}
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("mode") != "managed":
            continue
        parts = [resource.get("module", ""), resource.get("type"), resource.get("name")]
        if any(not isinstance(part, str) for part in parts) or not parts[1] or not parts[2]:
            raise ValueError("Foundation transition remote state address is invalid")
        prefix = ".".join(str(part) for part in parts if part)
        instances = resource.get("instances")
        if not isinstance(instances, list):
            raise ValueError("Foundation transition remote state instances are invalid")
        for instance in instances:
            if (
                not isinstance(instance, dict)
                or instance.get("deposed")
                or instance.get("status") not in (None, "ready")
                or not isinstance(instance.get("attributes"), dict)
            ):
                raise ValueError(
                    "Foundation transition remote state includes an incomplete instance"
                )
            index = instance.get("index_key")
            address = prefix + (f"[{json.dumps(index)}]" if index is not None else "")
            result[address] = instance["attributes"]
    return result


def observed_policy_variables(state_bytes: bytes) -> dict[str, object]:
    """Select only supported policy-assigned values from a Terraform state document."""

    value = json.loads(state_bytes)
    if not isinstance(value, dict):
        raise ValueError("Foundation transition remote state is empty or invalid")
    return _select_policy_variables(_managed_instances(value))


def refreshed_policy_variables(plan_bytes: bytes) -> dict[str, object]:
    """Select supported policy-assigned values from a refresh-only plan's refreshed state."""

    plan = json.loads(plan_bytes)
    prior = plan.get("prior_state") if isinstance(plan, dict) else None
    values = prior.get("values") if isinstance(prior, dict) else None
    root = values.get("root_module") if isinstance(values, dict) else None
    if not isinstance(root, dict):
        raise ValueError("Foundation transition refreshed state is unavailable")
    instances: dict[str, dict[str, object]] = {}
    pending = [root]
    while pending:
        module = pending.pop()
        for resource in module.get("resources", []) or []:
            if not isinstance(resource, dict) or resource.get("mode") != "managed":
                continue
            address = resource.get("address")
            attributes = resource.get("values")
            if not isinstance(address, str) or not isinstance(attributes, dict):
                raise ValueError("Foundation transition refreshed state is invalid")
            instances[address] = attributes
        children = module.get("child_modules", []) or []
        if not isinstance(children, list) or any(not isinstance(item, dict) for item in children):
            raise ValueError("Foundation transition refreshed state is invalid")
        pending.extend(children)
    if not instances:
        raise ValueError("Foundation transition refreshed state is unavailable")
    return _select_policy_variables(instances)


def _select_policy_variables(instances: dict[str, dict[str, object]]) -> dict[str, object]:
    observed: dict[str, object] = {}
    present = [address for address in _PUBLIC_IPS if address in instances]
    if present:
        if len(present) != len(_PUBLIC_IPS):
            raise ValueError("Foundation transition public IP policy evidence is incomplete")
        tags = [instances[address].get("ip_tags") for address in sorted(_PUBLIC_IPS)]
        tags = [{} if item is None else item for item in tags]
        if tags[0] != tags[1] or tags[0] not in ({}, _POLICY_TAGS):
            raise ValueError("Foundation transition public IP policy tags are unsupported")
        if tags[0]:
            observed["operations_public_ip_tags"] = dict(tags[0])
    runner = instances.get(_RUNNER_VM)
    mode = runner.get("patch_mode") if runner is not None else None
    if runner is not None and mode is not None:
        if not isinstance(mode, str) or mode not in _PATCH_MODES:
            raise ValueError("Foundation transition runner guest patch mode is unsupported")
        bypass = runner.get("bypass_platform_safety_checks_on_user_schedule_enabled")
        if bypass is None:
            bypass = False
        if not isinstance(bypass, bool):
            raise ValueError(
                "Foundation transition runner platform-safety selection is unsupported"
            )
        if mode != "AutomaticByPlatform" and bypass:
            raise ValueError(
                "Foundation transition platform-safety bypass requires platform patching"
            )
        observed["runner_patch_mode"] = mode
        observed["runner_bypass_platform_safety_checks"] = bypass
    return observed


def _evidence_directory(home: Path, work_ref: str) -> Path:
    return home / _EVIDENCE_BASE / f"transition-{work_ref}"


def _publish_evidence(home: Path, work: Path, names: tuple[str, ...]) -> None:
    """Copy bounded evidence where the Bastion evidence boundary permits retrieval."""

    base = home / _EVIDENCE_BASE
    base.mkdir(mode=0o700, exist_ok=True)
    _require_directory(base)
    target = _evidence_directory(home, work.name)
    target.mkdir(mode=0o700, exist_ok=True)
    _require_directory(target)
    for name in names:
        _write_bytes(target / name, (work / name).read_bytes())


def _extract_archive(archive: Path, destination: Path) -> str:
    digest = _digest_file(archive)
    count = 0
    total = 0
    with tarfile.open(archive, mode="r:gz") as bundle:
        for member in bundle:
            count += 1
            if count > _MAX_FILES:
                raise ValueError("Foundation transition archive has too many files")
            relative = PurePosixPath(member.name)
            if (
                relative.is_absolute()
                or any(part in {"", ".", ".."} for part in relative.parts)
                or not relative.parts
                or not (member.isdir() or member.isfile())
            ):
                raise ValueError("Foundation transition archive contains an unsafe member")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            total += member.size
            if total > _MAX_BYTES:
                raise ValueError("Foundation transition archive exceeds its size bound")
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError("Foundation transition archive member cannot be read")
            output = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with source, os.fdopen(output, "wb") as sink:
                shutil.copyfileobj(source, sink, length=1024 * 1024)
    return digest


def _verify_tree(work: Path, *, migrated: bool = False) -> None:
    manifest = _read_json(work / "manifest.json")
    digest = manifest.pop("manifest_digest", None)
    files = manifest.get("files")
    if (
        manifest.get("schema_version") != "fdai.genesis-foundation-transition-archive.v1"
        or not isinstance(digest, str)
        or _canonical_digest(manifest) != digest
        or not isinstance(files, dict)
        or not files
    ):
        raise ValueError("Foundation transition archive manifest is invalid")
    actual: dict[str, dict[str, object]] = {}
    for path in sorted(work.rglob("*")):
        relative = path.relative_to(work).as_posix()
        if stat.S_ISDIR(path.lstat().st_mode):
            continue
        if relative == "manifest.json":
            continue
        if migrated and relative.startswith(("root/.terraform/", "azure/")):
            continue
        if relative in {
            "remote-state.json",
            "remote-state-after.json",
            "remote-plan.json",
            "remote-zero-plan.json",
            "transition.tfplan",
            "remote-zero.tfplan",
            "plan-observation.json",
            "apply-observation.json",
            "offline.tfrc",
            _OBSERVED_VARIABLES,
            "refresh.tfplan",
        }:
            continue
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValueError("Foundation transition archive tree contains an unsafe file")
        actual[relative] = {"sha256": _digest_file(path), "executable": False}
    if files != actual:
        raise ValueError("Foundation transition archive file digests differ")


def _terraform_init(root: Path, environment: dict[str, str], args: argparse.Namespace) -> None:
    _run(
        (
            _TERRAFORM,
            "init",
            "-input=false",
            "-lockfile=readonly",
            f"-backend-config=resource_group_name={args.resource_group}",
            f"-backend-config=storage_account_name={args.account_name}",
            f"-backend-config=container_name={args.container_name}",
            f"-backend-config=key={args.backend_key}",
            "-backend-config=use_azuread_auth=true",
        ),
        cwd=root,
        env=environment,
        timeout=900,
        reason="Foundation transition backend initialization failed",
    )


def _managed_identity_login(
    work: Path, args: argparse.Namespace, environment: dict[str, str]
) -> None:
    azure = work / "azure"
    if azure.exists():
        shutil.rmtree(azure)
    azure.mkdir(mode=0o700)
    _run(
        (
            _AZURE_CLI,
            "login",
            "--identity",
            "--client-id",
            args.client_id,
            "--allow-no-subscriptions",
            "--output",
            "none",
            "--only-show-errors",
        ),
        cwd=work,
        env={**os.environ, "AZURE_CONFIG_DIR": str(azure)},
        timeout=60,
        reason="Foundation transition managed identity login failed",
    )
    _run(
        (
            _AZURE_CLI,
            "account",
            "set",
            "--subscription",
            args.subscription_id,
            "--only-show-errors",
        ),
        cwd=work,
        env=environment,
        timeout=30,
        reason="Foundation transition Azure subscription selection failed",
    )
    token = (
        _capture(
            (
                _AZURE_CLI,
                "account",
                "get-access-token",
                "--resource",
                "https://management.azure.com/",
                "--query",
                "accessToken",
                "--output",
                "tsv",
                "--only-show-errors",
            ),
            cwd=work,
            env=environment,
            timeout=30,
            reason="Foundation transition identity token readback failed",
            max_bytes=32 * 1024,
        )
        .decode()
        .strip()
    )
    payload = token.split(".")[1] + "=" * (-len(token.split(".")[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    if str(claims.get("oid", "")).casefold() != args.principal_id.casefold():
        raise ValueError("Foundation transition managed identity principal differs")


def _terraform_environment(work: Path, args: argparse.Namespace) -> dict[str, str]:
    if any(
        key.startswith("TF_CLI_ARGS")
        or key in {"TF_WORKSPACE", "TF_DATA_DIR", "TF_CLI_CONFIG_FILE"}
        for key in os.environ
    ):
        raise ValueError("ambient Terraform control variables are not accepted")
    cli_config = work / "offline.tfrc"
    cli_config.write_text(
        "provider_installation {\n"
        "  filesystem_mirror {\n"
        f'    path = "{work / "mirror"}"\n'
        '    include = ["*/*"]\n'
        "  }\n"
        "  direct {\n"
        '    exclude = ["*/*"]\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    cli_config.chmod(0o600)
    return {
        **os.environ,
        "AZURE_CONFIG_DIR": str(work / "azure"),
        "TF_DATA_DIR": str(work / "root/.terraform"),
        "TF_CLI_CONFIG_FILE": str(cli_config),
        "TF_IN_AUTOMATION": "1",
        "ARM_USE_MSI": "true",
        "ARM_USE_AZUREAD": "true",
        "ARM_CLIENT_ID": args.client_id,
        "ARM_SUBSCRIPTION_ID": args.subscription_id,
        "ARM_TENANT_ID": args.tenant_id,
        "ARM_RESOURCE_PROVIDER_REGISTRATIONS": "none",
    }


def _capture(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    reason: str,
    max_bytes: int = 1024 * 1024,
) -> bytes:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) > max_bytes:
        raise ValueError(reason)
    return result.stdout


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    reason: str,
) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(reason)


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Foundation transition JSON object is invalid")
    return {key: item for key, item in value.items()}


def _write_json(path: Path, value: dict[str, object]) -> None:
    _write_bytes(path, json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n")


def _write_bytes(path: Path, value: bytes) -> None:
    if path.exists():
        path.unlink()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)


def _require_directory(path: Path) -> None:
    details = path.lstat()
    if not stat.S_ISDIR(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o700:
        raise ValueError("Foundation transition directory is unsafe")


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
