#!/usr/bin/env python3
"""Coordinate one registered Terraform scope on the managed host through Action Run Command.

The ordinary PC reaches only Azure Resource Manager. The private Terraform backend stays behind its
private endpoint; the fixed receiver runs Terraform on the managed host under the host's
user-assigned deployment identity. See `docs/roadmap/deployment/provisioning-execution-profiles.md`.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import select
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scoped_terraform_receiver as receiver  # noqa: E402

PROFILE_SCHEMA = "fdai.scoped-terraform-profile.v1"
APPROVAL_PROFILES = frozenset({"dev-single-operator"})
RECEIVER_PATH = "scripts/deployment/azure/scoped_terraform_receiver.py"
MAX_SCRIPT_BYTES = 192 * 1024
MAX_VARS_BYTES = 64 * 1024
SECRET_MARKERS = re.compile(
    r"(AccountKey=|SharedAccessSignature|[?&]sig=|-----BEGIN|client_secret|password|"
    r"\"access_key\"|\"sas_token\")",
    re.IGNORECASE,
)
VARIABLE = re.compile(r'^variable\s+"([A-Za-z0-9_]+)"', re.MULTILINE)
TIMEOUTS = {"plan": 2400, "apply": 5100, "verify": 2400}
STATE_ROOT = Path.home() / ".local/state/fdai/scoped-terraform"
REPOSITORY = Path(__file__).resolve().parents[3]
Runner = Callable[[tuple[str, ...], int], str]


class CoordinatorError(Exception):
    """An actionable, secret-free coordinator failure."""


def capture(command: tuple[str, ...], timeout: int) -> str:
    label = " ".join(command[:4:3] if command[1:2] == ("-C",) else command[:2])
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        raise CoordinatorError(f"{label} exceeded {timeout}s") from None
    if completed.returncode != 0:
        raise CoordinatorError(f"{label} failed with {completed.returncode}")
    return completed.stdout


def private_file(path: Path, *, limit: int) -> bytes:
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise CoordinatorError(f"{path.name} must be a private regular file owned by the operator")
    data = path.read_bytes()
    if len(data) > limit:
        raise CoordinatorError(f"{path.name} exceeds {limit} bytes")
    return data


def load_profile(path: Path) -> dict[str, Any]:
    profile = json.loads(private_file(path, limit=16 * 1024))
    expected = {
        "schema_version",
        "approval_profile",
        "tenant_id",
        "subscription_id",
        "vm_resource_id",
        "executor_client_id",
        "backend",
    }
    if not isinstance(profile, dict) or set(profile) != expected:
        raise CoordinatorError("scoped Terraform profile fields are invalid")
    if profile["schema_version"] != PROFILE_SCHEMA:
        raise CoordinatorError("scoped Terraform profile schema is unsupported")
    if profile["approval_profile"] not in APPROVAL_PROFILES:
        raise CoordinatorError("scoped Terraform requires the dev single-operator approval profile")
    for key in ("tenant_id", "subscription_id", "executor_client_id"):
        if not receiver.GUID.fullmatch(str(profile[key])):
            raise CoordinatorError(f"profile {key} must be a lowercase GUID")
    vm = str(profile["vm_resource_id"])
    if not re.fullmatch(
        rf"/subscriptions/{profile['subscription_id']}/resourceGroups/[^/]+/providers/"
        r"Microsoft\.Compute/virtualMachines/[^/]+",
        vm,
    ):
        raise CoordinatorError("profile vm_resource_id must name a VM in the profile subscription")
    backend = profile["backend"]
    if not isinstance(backend, dict) or set(backend) != set(receiver.BACKEND_FIELDS):
        raise CoordinatorError("profile backend accepts only account, container, key, and group")
    return profile


def load_variables(path: Path, declared: set[str]) -> bytes:
    data = private_file(path, limit=MAX_VARS_BYTES)
    values = json.loads(data)
    if not isinstance(values, dict) or not set(values) <= declared:
        raise CoordinatorError("variable file names undeclared Terraform variables")
    if SECRET_MARKERS.search(data.decode("utf-8")):
        raise CoordinatorError("variable file contains secret-like material; refuse to transfer it")
    return receiver.canonical(values)


def resolve_source(run: Runner, ref: str) -> str:
    run(("git", "-C", str(REPOSITORY), "fetch", "--quiet", "origin", "main"), 180)
    commit = run(
        ("git", "-C", str(REPOSITORY), "rev-parse", "--verify", f"{ref}^{{commit}}"), 30
    ).strip()
    if not receiver.COMMIT.fullmatch(commit):
        raise CoordinatorError("source ref does not resolve to one commit")
    try:
        run(
            ("git", "-C", str(REPOSITORY), "merge-base", "--is-ancestor", commit, "origin/main"), 30
        )
    except CoordinatorError:
        raise CoordinatorError("source commit must be contained in protected origin/main") from None
    return commit


def export_source(commit: str, root: str, destination: Path) -> None:
    archive = subprocess.run(
        ("git", "-C", str(REPOSITORY), "archive", "--format=tar", commit, root),
        capture_output=True,
        timeout=120,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(destination / "export", filter="data")
    (destination / "export" / root).rename(destination / "source")


def payload_archive(source: Path, request: dict[str, Any], variables: bytes) -> bytes:
    buffer = io.BytesIO()

    def add(name: str, data: bytes) -> None:
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.mtime = len(data), 0o600, 0
        tar.addfile(info, io.BytesIO(data))

    with tarfile.open(fileobj=buffer, mode="w:gz", compresslevel=9) as tar:
        add("request.json", receiver.canonical(request))
        add("vars.json", variables)
        for path in sorted(source.rglob("*")):
            if path.is_file():
                add(f"source/{path.relative_to(source).as_posix()}", path.read_bytes())
    return buffer.getvalue()


def build_script(receiver_bytes: bytes, payload: bytes) -> str:
    receiver_b64 = base64.encodebytes(receiver_bytes).decode().strip()
    payload_b64 = base64.encodebytes(payload).decode().strip()
    failure = receiver.RESULT_PREFIX + '{"code":"transfer_digest_mismatch","state":"error"}'
    script = f"""#!/bin/bash
set -eu
umask 077
base={receiver.DEFAULT_BASE}
install -d -m 0700 "$base"
incoming="$(mktemp -d "$base/.incoming-XXXXXXXX")"
trap 'rm -rf "$incoming"' EXIT
base64 -d > "$incoming/receiver.py" <<'FDAI_RECEIVER'
{receiver_b64}
FDAI_RECEIVER
base64 -d > "$incoming/payload.tar.gz" <<'FDAI_PAYLOAD'
{payload_b64}
FDAI_PAYLOAD
if ! printf '%s  %s\\n' {receiver.sha256(receiver_bytes)} "$incoming/receiver.py" \\
    {receiver.sha256(payload)} "$incoming/payload.tar.gz" | sha256sum -c --quiet --status; then
  echo '{failure}'
  exit 1
fi
python3 -I "$incoming/receiver.py" --incoming "$incoming" 2>"$incoming/stderr" \\
  | grep '^{receiver.RESULT_PREFIX}' | tail -n 1
"""
    if len(script.encode()) > MAX_SCRIPT_BYTES:
        raise CoordinatorError("Run Command script exceeds the reviewed size bound")
    return script


def parse_result(output: str) -> dict[str, Any]:
    value = json.loads(output)
    message = str(((value.get("value") or [{}])[0]).get("message", ""))
    stdout = message.split("[stderr]", 1)[0]
    lines = [line for line in stdout.splitlines() if line.startswith(receiver.RESULT_PREFIX)]
    if not lines:
        raise CoordinatorError("Run Command returned no receiver result; run verify, never apply")
    result = json.loads(lines[-1][len(receiver.RESULT_PREFIX) :])
    if not isinstance(result, dict):
        raise CoordinatorError("receiver result is invalid")
    return result


def invoke(run: Runner, vm: str, script: str, operation: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", prefix="fdai-scoped-", suffix=".sh") as handle:
        os.chmod(handle.name, 0o600)
        handle.write(script)
        handle.flush()
        output = run(
            (
                "az",
                "vm",
                "run-command",
                "invoke",
                "--ids",
                vm,
                "--command-id",
                "RunShellScript",
                "--scripts",
                f"@{handle.name}",
                "--only-show-errors",
                "-o",
                "json",
            ),
            TIMEOUTS[operation],
        )
    return parse_result(output)


def verify_context(run: Runner, profile: dict[str, Any]) -> str:
    account = json.loads(run(("az", "account", "show", "-o", "json"), 60))
    if (
        account.get("tenantId") != profile["tenant_id"]
        or account.get("id") != (profile["subscription_id"])
    ):
        raise CoordinatorError("active Azure CLI account does not match the profile target")
    if (account.get("user") or {}).get("type") != "user":
        raise CoordinatorError("scoped Terraform approval requires an interactive human account")
    actor = run(("az", "ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"), 60).strip()
    if not receiver.GUID.fullmatch(actor):
        raise CoordinatorError("signed-in human object id is unavailable")
    vm = json.loads(run(("az", "vm", "show", "-d", "--ids", profile["vm_resource_id"]), 120))
    identities = ((vm.get("identity") or {}).get("userAssignedIdentities") or {}).values()
    if vm.get("powerState") != "VM running" or not any(
        item.get("clientId") == profile["executor_client_id"] for item in identities
    ):
        raise CoordinatorError("managed host is not running with the profile executor identity")
    return actor


def approve(review: dict[str, Any], binding: dict[str, Any], actor: str) -> dict[str, object]:
    token = f"{binding['mode']} {review['plan_sha256'][:12]}"
    print(json.dumps({"review": review, "binding": binding}, indent=2), file=sys.stderr)
    print(f"Type '{token}' to approve this exact plan: ", end="", file=sys.stderr, flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], 600)
    if not ready or sys.stdin.readline().strip() != token:
        raise CoordinatorError("scoped Terraform plan approval was denied")
    now = datetime.now(UTC).replace(microsecond=0)
    approval: dict[str, object] = {
        "operation_id": binding["operation_id"],
        "plan_sha256": review["plan_sha256"],
        "scope": binding["scope"],
        "mode": binding["mode"],
        "actor_object_id": actor,
        "approved_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    approval["approval_digest"] = receiver.sha256(receiver.canonical(approval))
    return approval


def check_container_insights(
    run: Runner, resources: dict[str, str], variables: dict[str, Any], mode: str
) -> dict[str, bool]:
    dcr_address, dcra_address = receiver.SCOPES["aks-container-insights"]["targets"]
    if mode == "destroy":
        return {"terraform_state_absent": not resources}

    def read(resource_id: str) -> dict[str, Any]:
        url = f"https://management.azure.com{resource_id}?api-version=2022-06-01"
        return json.loads(run(("az", "rest", "--method", "get", "--url", url), 120))

    dcr_id, dcra_id = resources.get(dcr_address, ""), resources.get(dcra_address, "")
    if not dcr_id or not dcra_id:
        raise CoordinatorError("Terraform state lacks the Container Insights resource ids")
    dcr = read(dcr_id).get("properties") or {}
    workspaces = {
        str(item.get("workspaceResourceId", "")).lower()
        for item in (dcr.get("destinations") or {}).get("logAnalytics") or []
    }
    streams = {stream for flow in dcr.get("dataFlows") or [] for stream in flow.get("streams", [])}
    settings = [
        (item.get("extensionSettings") or {}).get("dataCollectionSettings") or {}
        for item in (dcr.get("dataSources") or {}).get("extensions") or []
    ]
    association = read(dcra_id).get("properties") or {}
    return {
        "dcr_workspace_bound": str(variables["log_analytics_workspace_id"]).lower() in workspaces,
        "dcr_default_stream": "Microsoft-ContainerInsights-Group-Default" in streams,
        "dcr_container_log_v2": any(item.get("enableContainerLogV2") is True for item in settings),
        "association_bound": str(association.get("dataCollectionRuleId", "")).lower()
        == dcr_id.lower(),
    }


READBACK = {"aks-container-insights": check_container_insights}


def pointer_key(scope: str, mode: str, profile: dict[str, Any]) -> str:
    return receiver.sha256(
        receiver.canonical(
            {
                "scope": scope,
                "mode": mode,
                "vm_resource_id": profile["vm_resource_id"],
                "executor_client_id": profile["executor_client_id"],
                "backend": profile["backend"],
            }
        )
    )[:24]


def succeeded(operation: str, result: dict[str, Any]) -> bool:
    if result.get("state") in {"error", "busy", "verification-incomplete", "recovery-required"}:
        return False
    if result.get("apply_outcome", "applied") != "applied":
        return False
    if operation in {"apply", "verify"} and result.get("scope_zero_change") is not True:
        return False
    readback = result.get("independent_readback")
    return readback is None or (
        isinstance(readback, dict) and all(value is True for value in readback.values())
    )


def execute(args: argparse.Namespace, run: Runner = capture) -> dict[str, object]:
    profile = load_profile(args.profile)
    scope = receiver.SCOPES.get(args.scope)
    if scope is None:
        raise CoordinatorError("scope is not registered")
    actor = verify_context(run, profile)
    pointer_path = STATE_ROOT / "pointers" / f"{pointer_key(args.scope, args.mode, profile)}.json"
    pointer = json.loads(pointer_path.read_text()) if pointer_path.is_file() else None
    if args.operation == "plan" or pointer is None:
        if args.operation == "apply":
            raise CoordinatorError("apply requires a retained plan for this scope and target")
        commit = resolve_source(run, args.source_ref or "origin/main")
    else:
        commit = resolve_source(run, pointer["source_commit"])
        if args.source_ref and resolve_source(run, args.source_ref) != commit:
            raise CoordinatorError("apply and verify use the source commit retained at plan time")
    with tempfile.TemporaryDirectory(prefix="fdai-scoped-") as temporary:
        work = Path(temporary)
        export_source(commit, scope["root"], work)
        source = work / "source"
        declared = {
            name for path in source.glob("*.tf") for name in VARIABLE.findall(path.read_text())
        }
        variables = load_variables(args.var_file, declared)
        receiver_bytes = run(
            ("git", "-C", str(REPOSITORY), "show", f"{commit}:{RECEIVER_PATH}"), 30
        ).encode()
        binding: dict[str, Any] = {
            "scope": args.scope,
            "mode": args.mode,
            "source_commit": commit,
            "source_tree_digest": receiver.tree_digest(source),
            "receiver_digest": receiver.sha256(receiver_bytes),
            "vars_digest": receiver.sha256(variables),
            "backend": profile["backend"],
            "executor": {
                "client_id": profile["executor_client_id"],
                "tenant_id": profile["tenant_id"],
                "subscription_id": profile["subscription_id"],
            },
            "vm_resource_id": profile["vm_resource_id"],
        }
        binding["operation_id"] = receiver.operation_id(binding)
        if (
            args.operation != "plan"
            and pointer
            and pointer["operation_id"] != binding["operation_id"]
        ):
            raise CoordinatorError("inputs changed since plan; create and approve a new plan")
        local = STATE_ROOT / binding["operation_id"]
        local.mkdir(mode=0o700, parents=True, exist_ok=True)
        request = {
            "schema_version": receiver.REQUEST_SCHEMA,
            "operation": args.operation,
            **binding,
        }
        if args.operation == "apply":
            review_path = local / "review.json"
            if not review_path.is_file():
                raise CoordinatorError("apply requires a retained plan review from this operation")
            review = json.loads(review_path.read_text())
            request["approval"] = approve(review, binding, actor)
        script = build_script(receiver_bytes, payload_archive(source, request, variables))
        result = invoke(run, profile["vm_resource_id"], script, args.operation)
    if args.operation == "plan" and result.get("state") == "planned":
        receiver.validate_plan(
            {
                "resource_changes": [
                    {"address": c["address"], "change": c} for c in result["changes"]
                ]
            },
            scope=args.scope,
            mode=args.mode,
        )
        (local / "review.json").write_text(json.dumps(result, sort_keys=True))
    if args.operation == "plan" and result.get("state") in {"planned", "converged"}:
        pointer_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        pointer_path.write_text(
            json.dumps({"operation_id": binding["operation_id"], "source_commit": commit})
        )
    if result.get("apply_outcome", "applied") != "applied":
        result["independent_readback"] = {"skipped_after_failed_apply": False}
    elif "resource_ids" in result:
        try:
            result["independent_readback"] = READBACK[args.scope](
                run, dict(result["resource_ids"]), json.loads(variables), args.mode
            )
        except (CoordinatorError, subprocess.SubprocessError, ValueError, KeyError) as error:
            result["independent_readback"] = {"readback_failed": False, "detail": str(error)}
    return {"operation_id": binding["operation_id"], "source_commit": commit, "result": result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "apply", "verify"))
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--var-file", type=Path, required=True)
    parser.add_argument("--scope", required=True, choices=sorted(receiver.SCOPES))
    parser.add_argument("--mode", default="apply", choices=sorted(receiver.MODES))
    parser.add_argument("--source-ref", help="plan source (default origin/main)")
    args = parser.parse_args(argv)
    try:
        outcome = execute(args)
    except (CoordinatorError, receiver.ReceiverError, subprocess.SubprocessError) as error:
        print(f"scoped-terraform: {error}", file=sys.stderr)
        return 1
    print(json.dumps(outcome, indent=2, sort_keys=True))
    return 0 if succeeded(args.operation, outcome["result"]) else 1


if __name__ == "__main__":
    sys.exit(main())
