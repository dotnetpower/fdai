#!/usr/bin/env python3
"""Plan, apply, and verify GitHub configuration from a private Foundation handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest, load_json_object
from fdai_deployment_cli.plan_input import read_plan_input
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SECRET_NAMES = ("POSTGRES_ADMIN_LOGIN", "POSTGRES_ADMIN_PASSWORD")


@dataclass(frozen=True, slots=True)
class RepositoryConfigPlan:
    """Exact private repository configuration derived from Foundation evidence."""

    variables: dict[str, str]
    required_existing_variables: tuple[str, ...]
    required_secrets: tuple[str, ...]
    digest: str


def create_repository_config_plan(
    *,
    repository: str,
    source_commit: str,
    handoff: dict[str, Any],
    foundation_variables: dict[str, object],
    preflight_template: dict[str, Any],
    image_refs: dict[str, str],
    entra_bindings: dict[str, str],
) -> RepositoryConfigPlan:
    """Derive one exact configuration without reading or creating credentials."""

    if _REPOSITORY.fullmatch(repository) is None or _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("repository configuration context is invalid")
    _validate_handoff(handoff, source_commit=source_commit)
    app = _object(handoff["app_resource_group"], "application resource group")
    ops = _object(handoff["ops"], "operations handoff")
    state = _object(handoff["state"], "state handoff")
    runner = _object(handoff["runner"], "runner handoff")
    region_short = foundation_variables.get("region_short")
    if (
        not isinstance(region_short, str)
        or re.fullmatch(r"[a-z][a-z0-9]{1,7}", region_short) is None
    ):
        raise ValueError("Foundation region short name is invalid")
    preflight = json.loads(json.dumps(preflight_template))
    live = _object(preflight.get("azure_live"), "preflight Azure profile")
    live["resource_group"] = app["name"]
    preflight["generated_at"] = "resolved-by-protected-runner"
    if set(image_refs) != {
        "fdai-core-control-plane",
        "fdai-operator-service",
        "fdai-document-ingestion-api",
    } or any(
        re.fullmatch(r"ghcr[.]io/[a-z0-9_.-]+/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}", value)
        is None
        for value in image_refs.values()
    ):
        raise ValueError("repository configuration image references are invalid")
    required_entra = {
        "ENTRA_CONSOLE_API_SCOPE",
        "ENTRA_CONSOLE_SPA_CLIENT_ID",
        "OPERATOR_API_AUDIENCE",
        "RBAC_APPROVERS_GROUP_ID",
        "RBAC_BREAK_GLASS_GROUP_ID",
        "RBAC_CONTRIBUTORS_GROUP_ID",
        "RBAC_OWNERS_GROUP_ID",
        "RBAC_READERS_GROUP_ID",
    }
    if set(entra_bindings) != required_entra or any(
        not value.strip() for value in entra_bindings.values()
    ):
        raise ValueError("repository configuration Entra bindings are incomplete")
    variables = {
        "ARM_SUBSCRIPTION_ID": str(handoff["subscription_id"]),
        "AZURE_TENANT_ID": str(handoff["tenant_id"]),
        "AZURE_REGION": str(handoff["region"]),
        "AZURE_REGION_SHORT": region_short,
        "OPS_RESOURCE_GROUP_NAME": str(ops["resource_group_name"]),
        "OPS_VNET_ID": str(ops["vnet_id"]),
        "OPS_VNET_NAME": str(ops["vnet_name"]),
        "STATE_STORAGE_ACCOUNT": str(state["account_name"]),
        "STATE_RESOURCE_GROUP": str(ops["resource_group_name"]),
        "STATE_CONTAINER": str(state["container_name"]),
        "DEPLOY_RUNNER_CLIENT_ID": str(runner["client_id"]),
        "DEPLOY_RUNNER_PRINCIPAL_ID": str(runner["principal_id"]),
        "MODEL_RESOLVER_DEPLOYER_OBJECT_ID": str(runner["principal_id"]),
        "FOUNDATION_RESOURCE_GROUP_CONTEXT_DIGEST": str(app["foundation_context_digest"]),
        "CORE_IMAGE": image_refs["fdai-core-control-plane"],
        "OPERATOR_API_IMAGE": image_refs["fdai-operator-service"],
        "OPERATOR_API_MIGRATION_IMAGE": image_refs["fdai-operator-service"],
        "INGESTION_IMAGE": image_refs["fdai-document-ingestion-api"],
        "INGESTION_MIGRATION_IMAGE": image_refs["fdai-document-ingestion-api"],
        "DEPLOY_PREFLIGHT_INPUT_JSON": json.dumps(preflight, sort_keys=True, separators=(",", ":")),
        "DEV_DEPLOY_REQUIRED_APPROVALS": "0",
        **entra_bindings,
    }
    required_existing: tuple[str, ...] = ()
    body = {
        "schema_version": "fdai.genesis-repository-config-plan.v1",
        "repository_digest": hashlib.sha256(repository.casefold().encode()).hexdigest(),
        "source_commit": source_commit,
        "variable_digests": {
            key: hashlib.sha256(value.encode()).hexdigest()
            for key, value in sorted(variables.items())
        },
        "required_existing_variables": list(required_existing),
        "required_secrets": list(_SECRET_NAMES),
    }
    return RepositoryConfigPlan(
        variables=variables,
        required_existing_variables=required_existing,
        required_secrets=_SECRET_NAMES,
        digest=canonical_digest(body),
    )


def apply_repository_config(
    *,
    repository: str,
    plan: RepositoryConfigPlan,
    actor_digest: str,
    receipt_path: Path,
) -> dict[str, object]:
    """Apply one approved plan with bounded rollback and exact name/value readback."""

    if _REPOSITORY.fullmatch(repository) is None or _DIGEST.fullmatch(actor_digest) is None:
        raise ValueError("repository configuration apply context is invalid")
    current_variables = _variable_map(repository)
    current_secrets = set(_secret_names(repository))
    changed: list[str] = []
    created_secrets: list[str] = []
    try:
        for name, value in sorted(plan.variables.items()):
            if current_variables.get(name) == value:
                continue
            _gh(("variable", "set", name, "--repo", repository, "--body", value))
            changed.append(name)
        if "POSTGRES_ADMIN_LOGIN" not in current_secrets:
            _gh(
                ("secret", "set", "POSTGRES_ADMIN_LOGIN", "--repo", repository),
                input_text="fdaiadmin",
            )
            created_secrets.append("POSTGRES_ADMIN_LOGIN")
        if "POSTGRES_ADMIN_PASSWORD" not in current_secrets:
            password = secrets.token_urlsafe(32)
            _gh(
                ("secret", "set", "POSTGRES_ADMIN_PASSWORD", "--repo", repository),
                input_text=password,
            )
            created_secrets.append("POSTGRES_ADMIN_PASSWORD")
            del password
        _verify_repository_config(repository, plan)
        _verify_entra_bindings(
            _variable_map(repository),
            (
                "ENTRA_CONSOLE_API_SCOPE",
                "ENTRA_CONSOLE_SPA_CLIENT_ID",
                "RBAC_APPROVERS_GROUP_ID",
                "RBAC_BREAK_GLASS_GROUP_ID",
                "RBAC_CONTRIBUTORS_GROUP_ID",
                "RBAC_OWNERS_GROUP_ID",
                "RBAC_READERS_GROUP_ID",
            ),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        _rollback(repository, changed, current_variables, created_secrets)
        raise
    receipt: dict[str, object] = {
        "schema_version": "fdai.genesis-repository-config-receipt.v1",
        "state": "applied",
        "plan_digest": plan.digest,
        "actor_digest": actor_digest,
        "changed_variables": sorted(changed),
        "created_secrets": sorted(created_secrets),
        "readback_verified": True,
        "rollback_required": False,
        "mutation_performed": bool(changed or created_secrets),
        "subscription_ready": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    write_private_output(
        receipt_path,
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return receipt


def _verify_repository_config(repository: str, plan: RepositoryConfigPlan) -> None:
    actual = _variable_map(repository)
    if any(actual.get(name) != value for name, value in plan.variables.items()):
        raise ValueError("repository variable readback differs from the approved plan")
    if not set(plan.required_secrets) <= set(_secret_names(repository)):
        raise ValueError("repository secret-name readback is incomplete")


def _verify_entra_bindings(variables: dict[str, str], required_names: tuple[str, ...]) -> None:
    """Read back every required app and group from the active Azure tenant."""

    if any(name not in variables for name in required_names):
        raise ValueError("repository Entra binding inventory is incomplete")
    api_scope = variables["ENTRA_CONSOLE_API_SCOPE"]
    match = re.fullmatch(r"api://([^/]+)/[^/]+", api_scope)
    if match is None:
        raise ValueError("repository Console API scope is invalid")
    app_ids = (variables["ENTRA_CONSOLE_SPA_CLIENT_ID"], match.group(1))
    for app_id in app_ids:
        result = _az(("ad", "app", "show", "--id", app_id, "--query", "appId", "-o", "tsv"))
        if result.casefold() != app_id.casefold():
            raise ValueError("repository Entra application does not belong to the active tenant")
    for name in required_names:
        if not name.startswith("RBAC_"):
            continue
        group_id = variables[name]
        result = _az(("ad", "group", "show", "--group", group_id, "--query", "id", "-o", "tsv"))
        if result.casefold() != group_id.casefold():
            raise ValueError("repository RBAC group does not belong to the active tenant")


def _rollback(
    repository: str,
    changed: list[str],
    previous: dict[str, str],
    created_secrets: list[str],
) -> None:
    failures = False
    for name in reversed(changed):
        result = (
            _gh_result(("variable", "set", name, "--repo", repository, "--body", previous[name]))
            if name in previous
            else _gh_result(("variable", "delete", name, "--repo", repository))
        )
        failures |= result.returncode != 0
    for name in reversed(created_secrets):
        failures |= _gh_result(("secret", "delete", name, "--repo", repository)).returncode != 0
    if failures:
        raise ValueError("repository configuration rollback is incomplete")


def _variable_map(repository: str) -> dict[str, str]:
    raw = _gh(("variable", "list", "--repo", repository, "--json", "name,value"))
    value = json.loads(raw)
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError("repository variable inventory is invalid")
    result: dict[str, str] = {}
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("value"), str)
        ):
            raise ValueError("repository variable inventory is invalid")
        result[item["name"]] = item["value"]
    return result


def _secret_names(repository: str) -> tuple[str, ...]:
    raw = _gh(("secret", "list", "--repo", repository, "--json", "name"))
    value = json.loads(raw)
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError("repository secret inventory is invalid")
    names = []
    for item in value:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str):
            raise ValueError("repository secret inventory is invalid")
        names.append(name)
    return tuple(names)


def _gh(arguments: tuple[str, ...], *, input_text: str | None = None) -> str:
    result = _gh_result(arguments, input_text=input_text)
    if result.returncode != 0:
        raise ValueError("GitHub repository configuration command failed")
    return result.stdout


def _gh_result(
    arguments: tuple[str, ...], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *arguments],
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _az(arguments: tuple[str, ...]) -> str:
    completed = subprocess.run(
        ["az", *arguments, "--only-show-errors"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise ValueError("target-tenant Entra binding readback failed")
    return completed.stdout.strip()


def _validate_handoff(handoff: dict[str, Any], *, source_commit: str) -> None:
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
    if set(handoff) != required or handoff.get("source_commit") != source_commit:
        raise ValueError("Foundation handoff does not match the source revision")
    for name in ("app_resource_group", "ops", "state", "runner", "access"):
        _object(handoff.get(name), name)


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} is invalid")
    return value


def _load_private(path: Path, label: str) -> dict[str, Any]:
    return dict(
        load_json_object(
            read_private_bytes(path, max_bytes=1_048_576),
            label=label,
            max_bytes=1_048_576,
        )
    )


def main() -> int:
    """Plan or apply repository configuration from private Genesis files."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--foundation-variables", type=Path, required=True)
    parser.add_argument("--preflight-template", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--actor-digest")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    plan = create_repository_config_plan(
        repository=args.repository,
        source_commit=args.source_commit,
        handoff=_load_private(args.handoff, "Foundation handoff"),
        foundation_variables=read_plan_input(args.foundation_variables),
        preflight_template=json.loads(args.preflight_template.read_text(encoding="utf-8")),
        image_refs={
            "fdai-core-control-plane": os.environ.get("FDAI_CORE_IMAGE", ""),
            "fdai-operator-service": os.environ.get("FDAI_OPERATOR_IMAGE", ""),
            "fdai-document-ingestion-api": os.environ.get("FDAI_INGESTION_IMAGE", ""),
        },
        entra_bindings=json.loads(os.environ.get("FDAI_ENTRA_BINDINGS_JSON", "{}")),
    )
    plan_value = {
        "schema_version": "fdai.genesis-repository-config-plan.v1",
        "plan_digest": plan.digest,
        "variable_names": sorted(plan.variables),
        "required_existing_variables": list(plan.required_existing_variables),
        "required_secret_names": list(plan.required_secrets),
        "mutation_performed": False,
        "subscription_ready": False,
    }
    if args.mode == "plan":
        write_private_output(
            args.plan,
            json.dumps(plan_value, sort_keys=True, separators=(",", ":")) + "\n",
        )
        print(json.dumps(plan_value, sort_keys=True, separators=(",", ":")))
        return 0
    retained = _load_private(args.plan, "repository configuration plan")
    if retained != plan_value or args.receipt is None or args.actor_digest is None:
        raise ValueError("repository configuration plan changed before apply")
    result = apply_repository_config(
        repository=args.repository,
        plan=plan,
        actor_digest=args.actor_digest,
        receipt_path=args.receipt,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
