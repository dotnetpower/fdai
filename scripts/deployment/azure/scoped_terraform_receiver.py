#!/usr/bin/env python3
"""Run one registered Terraform scope on the managed deployment host.

The coordinator (`scoped_terraform.py`) delivers this file from an exact protected commit through
Action Run Command. It uses only the standard library, executes Terraform under the host's
user-assigned deployment identity, and returns one bounded result line.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RESULT_PREFIX = "FDAI_SCOPED_RESULT="
MAX_RESULT_BYTES = 3000
REQUEST_SCHEMA = "fdai.scoped-terraform-request.v1"
DEFAULT_BASE = Path("/var/lib/fdai/scoped-terraform")
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DIGEST = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
OPERATION_ID = re.compile(r"[0-9a-f]{24}")
AZURE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,89}")
STATE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}")
BACKEND_FIELDS = ("storage_account_name", "container_name", "key", "resource_group_name")
MODES = {"apply": frozenset({("create",), ("update",)}), "destroy": frozenset({("delete",)})}
IMDS = "http://169.254.169.254/metadata/identity/oauth2/token"
SEARCH_PATH = "/usr/local/bin:/usr/bin:/bin"

# Registered scopes. Adding a scope is a reviewed source change with focused tests.
SCOPES: dict[str, dict[str, Any]] = {
    "aks-container-insights": {
        "root": "infra/runtimes/aks/cluster",
        "targets": (
            "azurerm_monitor_data_collection_rule.container_insights",
            "azurerm_monitor_data_collection_rule_association.container_insights",
        ),
    },
}


class ReceiverError(Exception):
    """A typed, secret-free receiver failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_digest(root: Path) -> str:
    """Digest regular files under root by relative path and content; reject links."""

    entries: list[list[str]] = []
    for path in sorted(root.rglob("*")):
        details = path.lstat()
        if stat.S_ISLNK(details.st_mode):
            raise ReceiverError("source_symlink_rejected")
        if stat.S_ISREG(details.st_mode):
            entries.append([path.relative_to(root).as_posix(), sha256(path.read_bytes())])
    return sha256(canonical(entries))


def operation_id(binding: dict[str, object]) -> str:
    return sha256(canonical(binding))[:24]


def scope_key(request: dict[str, Any]) -> str:
    """Identify one state target independently of source revision and mode."""

    return sha256(
        canonical(
            {
                "scope": request["scope"],
                "backend": request["backend"],
                "executor": request["executor"],
                "vm_resource_id": request["vm_resource_id"],
            }
        )
    )[:24]


def pending_claims(base: Path, key: str) -> list[str]:
    """Return operations for this state target whose apply claim has no receipt."""

    markers = base / "scopes" / key
    if not markers.is_dir():
        return []
    return sorted(
        marker.stem
        for marker in markers.glob("*.claim")
        if (base / marker.stem / "claim.json").exists()
        and not (base / marker.stem / "receipt.json").exists()
    )


def binding_of(request: dict[str, Any]) -> dict[str, object]:
    return {
        "scope": request["scope"],
        "mode": request["mode"],
        "source_commit": request["source_commit"],
        "source_tree_digest": request["source_tree_digest"],
        "receiver_digest": request["receiver_digest"],
        "vars_digest": request["vars_digest"],
        "backend": request["backend"],
        "executor": request["executor"],
        "vm_resource_id": request["vm_resource_id"],
    }


def validate_request(request: object) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("schema_version") != REQUEST_SCHEMA:
        raise ReceiverError("request_schema_invalid")
    if request.get("operation") not in {"plan", "apply", "verify"}:
        raise ReceiverError("request_operation_invalid")
    if request.get("scope") not in SCOPES or request.get("mode") not in MODES:
        raise ReceiverError("request_scope_invalid")
    if not COMMIT.fullmatch(str(request.get("source_commit", ""))):
        raise ReceiverError("request_commit_invalid")
    for key in ("source_tree_digest", "receiver_digest", "vars_digest"):
        if not DIGEST.fullmatch(str(request.get(key, ""))):
            raise ReceiverError("request_digest_invalid")
    backend = request.get("backend")
    if not isinstance(backend, dict) or set(backend) != set(BACKEND_FIELDS):
        raise ReceiverError("request_backend_invalid")
    if not all(AZURE_NAME.fullmatch(str(backend[key])) for key in BACKEND_FIELDS if key != "key"):
        raise ReceiverError("request_backend_invalid")
    if not STATE_KEY.fullmatch(str(backend["key"])) or ".." in str(backend["key"]):
        raise ReceiverError("request_backend_invalid")
    executor = request.get("executor")
    if not isinstance(executor, dict) or set(executor) != {
        "client_id",
        "tenant_id",
        "subscription_id",
    }:
        raise ReceiverError("request_executor_invalid")
    if not all(GUID.fullmatch(str(value)) for value in executor.values()):
        raise ReceiverError("request_executor_invalid")
    if not isinstance(request.get("vm_resource_id"), str):
        raise ReceiverError("request_vm_invalid")
    if request.get("operation_id") != operation_id(binding_of(request)):
        raise ReceiverError("operation_id_mismatch")
    if request["operation"] == "apply":
        approval = request.get("approval")
        if not isinstance(approval, dict):
            raise ReceiverError("approval_missing")
        if not DIGEST.fullmatch(str(approval.get("plan_sha256", ""))) or not DIGEST.fullmatch(
            str(approval.get("approval_digest", ""))
        ):
            raise ReceiverError("approval_invalid")
        if not GUID.fullmatch(str(approval.get("actor_object_id", ""))):
            raise ReceiverError("approval_invalid")
        unsigned = {key: value for key, value in approval.items() if key != "approval_digest"}
        if sha256(canonical(unsigned)) != approval["approval_digest"]:
            raise ReceiverError("approval_digest_mismatch")
        if approval.get("operation_id") != request["operation_id"]:
            raise ReceiverError("approval_operation_mismatch")
        try:
            expires = datetime.fromisoformat(str(approval["expires_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            raise ReceiverError("approval_invalid") from None
        if expires <= datetime.now(UTC):
            raise ReceiverError("approval_expired")
    return request


def validate_plan(plan: dict[str, Any], *, scope: str, mode: str) -> list[dict[str, object]]:
    """Return the changed resources, rejecting anything outside the registered scope."""

    targets = set(SCOPES[scope]["targets"])
    allowed = MODES[mode]
    changes: list[dict[str, object]] = []
    for change in plan.get("resource_changes") or []:
        actions = tuple((change.get("change") or {}).get("actions") or ())
        if actions in {("no-op",), ("read",)}:
            continue
        address = str(change.get("address", ""))
        if address not in targets:
            raise ReceiverError("plan_scope_violation")
        if actions not in allowed:
            raise ReceiverError("plan_action_rejected")
        changes.append({"address": address, "actions": list(actions)})
    return changes


def private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    details = path.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise ReceiverError("private_directory_invalid")
    return path


def write_once(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(canonical(value))
        handle.flush()
        os.fsync(handle.fileno())


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ReceiverError("state_symlink_rejected")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ReceiverError("state_invalid")
    return value


def replace_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.unlink(missing_ok=True)
    write_once(temporary, value)
    os.replace(temporary, path)


def probe_identity(executor: dict[str, str]) -> None:
    """Require the host to mint a management token for the exact executor identity."""

    url = (
        f"{IMDS}?api-version=2018-02-01&resource=https://management.azure.com/"
        f"&client_id={executor['client_id']}"
    )
    request = urllib.request.Request(url, headers={"Metadata": "true"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            token = json.loads(response.read())["access_token"]
        claims = token.split(".")[1]
        claims += "=" * (-len(claims) % 4)
        payload = json.loads(base64.urlsafe_b64decode(claims))
    except Exception:  # noqa: BLE001 - never surface token material
        raise ReceiverError("executor_identity_unavailable") from None
    if payload.get("appid") != executor["client_id"] or payload.get("tid") != executor["tenant_id"]:
        raise ReceiverError("executor_identity_mismatch")


class Terraform:
    """Run Terraform in one private workspace with an isolated environment."""

    def __init__(self, workspace: Path, state: Path, request: dict[str, Any]) -> None:
        self.workspace = workspace
        self.state = state
        executor = request["executor"]
        self.environment = {
            "PATH": SEARCH_PATH,
            "HOME": str(private_directory(state / "home")),
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
            "TF_DATA_DIR": str(state / "terraform-data"),
            "TF_PLUGIN_CACHE_DIR": str(private_directory(state.parent / ".plugin-cache")),
            "ARM_USE_MSI": "true",
            "ARM_USE_CLI": "false",
            "ARM_USE_OIDC": "false",
            "ARM_CLIENT_ID": executor["client_id"],
            "ARM_TENANT_ID": executor["tenant_id"],
            "ARM_SUBSCRIPTION_ID": executor["subscription_id"],
            "ARM_STORAGE_USE_AZUREAD": "true",
        }

    def run(self, *arguments: str, log: str, timeout: int, codes: tuple[int, ...] = (0,)) -> int:
        with (self.state / log).open("ab") as handle:
            try:
                completed = subprocess.run(
                    ("terraform", *arguments),
                    cwd=self.workspace,
                    env=self.environment,
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=handle,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise ReceiverError(f"terraform_{arguments[0]}_timeout") from None
        if completed.returncode not in codes:
            raise ReceiverError(f"terraform_{arguments[0]}_failed")
        return completed.returncode

    def json(self, *arguments: str, timeout: int = 300) -> dict[str, Any]:
        completed = subprocess.run(
            ("terraform", *arguments),
            cwd=self.workspace,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise ReceiverError(f"terraform_{arguments[0]}_failed")
        value = json.loads(completed.stdout)
        if not isinstance(value, dict):
            raise ReceiverError("terraform_json_invalid")
        return value


def prepare_workspace(incoming: Path, state: Path, request: dict[str, Any]) -> Terraform:
    source = incoming / "payload" / "source"
    if tree_digest(source) != request["source_tree_digest"]:
        raise ReceiverError("source_digest_mismatch")
    variables = incoming / "payload" / "vars.json"
    if sha256(variables.read_bytes()) != request["vars_digest"]:
        raise ReceiverError("vars_digest_mismatch")
    for path in source.glob("*.tf"):
        if re.search(r"\bbackend\s+\"", path.read_text(encoding="utf-8")):
            raise ReceiverError("source_backend_block_rejected")
    workspace = state / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    shutil.copytree(source, workspace, symlinks=False)
    os.chmod(workspace, 0o700)
    shutil.copyfile(variables, state / "vars.json")
    (workspace / "fdai_scoped_backend.tf").write_text(
        'terraform {\n  backend "azurerm" {}\n}\n', encoding="utf-8"
    )
    terraform = Terraform(workspace, state, request)
    backend = request["backend"]
    executor = request["executor"]
    settings = {
        **backend,
        "use_azuread_auth": "true",
        "use_msi": "true",
        "client_id": executor["client_id"],
        "tenant_id": executor["tenant_id"],
        "subscription_id": executor["subscription_id"],
    }
    terraform.run(
        "init",
        "-input=false",
        "-no-color",
        "-reconfigure",
        "-lockfile=readonly",
        *(f"-backend-config={key}={value}" for key, value in sorted(settings.items())),
        log="init.log",
        timeout=900,
    )
    initialized = read_json(state / "terraform-data" / "terraform.tfstate").get("backend") or {}
    config = initialized.get("config") or {}
    if initialized.get("type") != "azurerm" or any(
        config.get(key) != value for key, value in backend.items()
    ):
        raise ReceiverError("backend_binding_mismatch")
    return terraform


def target_arguments(request: dict[str, Any]) -> list[str]:
    return [f"-target={target}" for target in SCOPES[request["scope"]]["targets"]]


def plan(terraform: Terraform, state: Path, request: dict[str, Any]) -> dict[str, object]:
    if (state / "claim.json").exists() and not (state / "receipt.json").exists():
        return {"state": "recovery-required"}
    if (state / "receipt.json").exists():
        receipt = read_json(state / "receipt.json")
        return {"state": "already-applied", "apply_outcome": receipt.get("outcome")}
    plan_path = state / "plan.tfplan"
    plan_path.unlink(missing_ok=True)
    arguments = ["plan", "-input=false", "-no-color", "-lock-timeout=120s"]
    arguments += [f"-var-file={state / 'vars.json'}", f"-out={plan_path}"]
    if request["mode"] == "destroy":
        arguments.append("-destroy")
    terraform.run(*arguments, *target_arguments(request), log="plan.log", timeout=1800)
    changes = validate_plan(
        terraform.json("show", "-json", str(plan_path)),
        scope=request["scope"],
        mode=request["mode"],
    )
    if not changes:
        plan_path.unlink(missing_ok=True)
        (state / "review.json").unlink(missing_ok=True)
        return {"state": "converged", "changes": []}
    review = {"plan_sha256": sha256(plan_path.read_bytes()), "changes": changes}
    replace_json(state / "review.json", review)
    return {"state": "planned", **review}


def apply(terraform: Terraform, state: Path, request: dict[str, Any]) -> dict[str, object]:
    approval = request["approval"]
    if (state / "claim.json").exists() or (state / "claim.json").is_symlink():
        raise ReceiverError("apply_already_claimed")
    review_path = state / "review.json"
    plan_path = state / "plan.tfplan"
    if not review_path.is_file() or not plan_path.is_file() or plan_path.is_symlink():
        raise ReceiverError("apply_plan_missing")
    review = read_json(review_path)
    digest = sha256(plan_path.read_bytes())
    if digest != review.get("plan_sha256") or digest != approval["plan_sha256"]:
        raise ReceiverError("apply_plan_digest_mismatch")
    markers = private_directory(private_directory(state.parent / "scopes") / scope_key(request))
    write_once(markers / f"{request['operation_id']}.claim", {"claimed_at": moment()})
    write_once(
        state / "claim.json",
        {
            "operation_id": request["operation_id"],
            "plan_sha256": digest,
            "approval_digest": approval["approval_digest"],
            "actor_object_id": approval["actor_object_id"],
            "claimed_at": moment(),
        },
    )
    try:
        terraform.run(
            "apply",
            "-input=false",
            "-no-color",
            "-lock-timeout=120s",
            str(plan_path),
            log="apply.log",
            timeout=3600,
        )
        outcome, code = "applied", ""
    except ReceiverError as error:
        outcome, code = "apply-failed", error.code
    write_once(
        state / "receipt.json",
        {"operation_id": request["operation_id"], "outcome": outcome, "completed_at": moment()},
    )
    try:
        result = verify(terraform, state, request)
    except ReceiverError as error:
        result = {"state": "verification-incomplete", "verify_code": error.code}
    result["apply_outcome"] = outcome
    if code:
        result["error_code"] = code
    return result


def verify(terraform: Terraform, state: Path, request: dict[str, Any]) -> dict[str, object]:
    """Report claim state and targeted convergence without applying anything."""

    exit_code = terraform.run(
        "plan",
        "-input=false",
        "-no-color",
        "-lock-timeout=120s",
        "-detailed-exitcode",
        f"-var-file={state / 'vars.json'}",
        *(["-destroy"] if request["mode"] == "destroy" else []),
        *target_arguments(request),
        log="verify.log",
        timeout=1800,
        codes=(0, 2),
    )
    targets = set(SCOPES[request["scope"]]["targets"])
    resources: dict[str, str] = {}
    for resource in (
        terraform.json("show", "-json").get("values", {}).get("root_module", {}).get("resources")
        or []
    ):
        if resource.get("address") in targets:
            resources[str(resource["address"])] = str(resource.get("values", {}).get("id", ""))
    return {
        "state": "verified",
        "claimed": (state / "claim.json").exists(),
        "receipt": (state / "receipt.json").exists(),
        "scope_zero_change": exit_code == 0,
        "resource_ids": resources,
    }


def moment() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def extract_payload(incoming: Path) -> dict[str, Any]:
    destination = incoming / "payload"
    with tarfile.open(incoming / "payload.tar.gz", "r:gz") as archive:
        for member in archive.getmembers():
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir()):
                raise ReceiverError("payload_member_rejected")
        archive.extractall(destination, filter="data")
    return validate_request(json.loads((destination / "request.json").read_bytes()))


def run(
    incoming: Path,
    *,
    base: Path = DEFAULT_BASE,
    identity: Callable[[dict[str, str]], None] = probe_identity,
) -> dict[str, object]:
    request = extract_payload(incoming)
    if sha256((incoming / "receiver.py").read_bytes()) != request["receiver_digest"]:
        raise ReceiverError("receiver_digest_mismatch")
    private_directory(base)
    lock = os.open(base / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"state": "busy"}
        pending = pending_claims(base, scope_key(request))
        if request["operation"] != "verify" and pending:
            return {"state": "recovery-required", "pending_operation_ids": pending[:3]}
        state = private_directory(base / request["operation_id"])
        identity(request["executor"])
        terraform = prepare_workspace(incoming, state, request)
        handler = {"plan": plan, "apply": apply, "verify": verify}[request["operation"]]
        return handler(terraform, state, request)
    finally:
        os.close(lock)


def emit(result: dict[str, object]) -> str:
    line = RESULT_PREFIX + canonical(result).decode()
    if len(line.encode()) > MAX_RESULT_BYTES:
        line = RESULT_PREFIX + canonical({"state": "error", "code": "result_too_large"}).decode()
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incoming", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.incoming)
    except ReceiverError as error:
        result = {"state": "error", "code": error.code}
    except Exception:  # noqa: BLE001 - fixed code; details stay in host logs
        result = {"state": "error", "code": "receiver_internal_error"}
    print(emit(result))
    return 0 if result.get("state") not in {"error", "busy"} else 1


if __name__ == "__main__":
    sys.exit(main())
