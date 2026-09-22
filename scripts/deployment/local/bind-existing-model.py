#!/usr/bin/env python3
"""Bind an observed existing Azure deployment in a private local model artifact."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fdai.rule_catalog.schema.llm_resolver import ResolvedModels
from fdai.rule_catalog.schema.model_endpoint import ModelEndpointBinding


def bind_existing_model(
    original: dict[str, Any],
    evidence: dict[str, Any],
    *,
    family: str,
    now: datetime,
    capability: str = "t2.reasoner.primary",
) -> dict[str, Any]:
    """Bind a T2 producer or seal the selected legacy embedding deployment from readback."""
    if capability not in {"t2.reasoner.primary", "t1.embedding"}:
        raise ValueError("existing model binding capability is unsupported")
    if capability == "t1.embedding":
        selected = next(
            (item for item in original["capabilities"] if item["name"] == capability), None
        )
        if (
            selected is None
            or selected["status"] not in {"resolved", "capacity-reduced"}
            or selected["publisher"] != "OpenAI"
            or selected["family"] != family
            or any(
                item["capability"] == capability for item in original.get("endpoint_bindings", [])
            )
        ):
            raise ValueError("embedding binding requires the unchanged unbound legacy selection")
    observed_at = datetime.fromisoformat(evidence["observed_at"])
    if observed_at.tzinfo is None or not timedelta(0) <= now - observed_at <= timedelta(minutes=5):
        raise ValueError("model deployment evidence MUST be current and timezone-aware")
    account = evidence["account"]
    endpoint = account["properties"]["endpoint"].rstrip("/")
    if urlsplit(endpoint).hostname != urlsplit(original["narrator"]["endpoint"]).hostname:
        raise ValueError("observed account MUST match the configured model endpoint")
    matches = [
        item
        for item in evidence["deployments"]
        if item["properties"].get("model", {}).get("name") == family
        and item["properties"].get("model", {}).get("format") == "OpenAI"
        and item["properties"].get("provisioningState") == "Succeeded"
        and (capability != "t1.embedding" or item["name"] == capability)
    ]
    if len(matches) != 1:
        raise ValueError("model binding requires exactly one successful observed deployment")
    deployment = matches[0]
    if (
        deployment["id"].casefold()
        != (account["id"] + "/deployments/" + deployment["name"]).casefold()
    ):
        raise ValueError("deployment evidence is outside the configured account")
    if deployment["sku"]["name"] not in {"Standard", "GlobalStandard", "DataZoneStandard"}:
        raise ValueError("existing model binding supports token-capacity deployments only")
    capacity = deployment["sku"]["capacity"]
    if type(capacity) is not int or capacity <= 0:
        raise ValueError("observed deployment capacity MUST be positive")
    version = deployment["properties"]["model"]["version"]
    result = copy.deepcopy(original)
    if capability == "t2.reasoner.primary" and any(
        item["name"] == "t2.reasoner.secondary"
        and item["status"] in {"resolved", "capacity-reduced"}
        and item.get("publisher") == "OpenAI"
        for item in result["capabilities"]
    ):
        raise ValueError("T2 primary binding MUST preserve the distinct-publisher reviewer")
    producer = next(item for item in result["capabilities"] if item["name"] == capability)
    if capability == "t1.embedding":
        producer["version"] = version
    else:
        producer.update(
            status="resolved",
            publisher="OpenAI",
            family=family,
            version=version,
            sku=deployment["sku"]["name"],
            capacity_tpm=capacity * 1000,
            selection_mode="pinned",
            reasons=["existing_deployment_observed"],
        )
        producer["capacity"] = {"unit": "tpm", "value": capacity * 1000}
    binding = {
        "binding_id": f"local-existing:{capability}",
        "capability": capability,
        "provider_kind": "azure-openai",
        "route_kind": "direct",
        "api_style": "azure-openai",
        "endpoint_ref": f"azure-openai:{account['name']}",
        "deployment": deployment["name"],
        "api_version": original["narrator"]["api_version"],
        "auth": {"kind": "entra", "audience": "https://cognitiveservices.azure.com/.default"},
        "model": {"publisher": "OpenAI", "family": family, "version": version},
        "capacity": {"unit": "tpm", "value": capacity * 1000},
        "features": {
            "streaming": False,
            "embeddings": capability == "t1.embedding",
            "structured_output": False,
            "tool_calling": False,
        },
        "discovery": {
            "source": "azure-management",
            "resource_ref_digest": hashlib.sha256(deployment["id"].encode()).hexdigest(),
            "verified_at": observed_at.isoformat(),
        },
    }
    ModelEndpointBinding.from_dict(binding)
    result["endpoint_bindings"] = [
        item for item in result.get("endpoint_bindings", []) if item["capability"] != capability
    ] + [binding]
    if capability == "t2.reasoner.primary":
        result.pop("reasoner_primary_candidates", None)
    ResolvedModels.from_json(json.dumps(result))
    return result


def restore_existing_account(
    original: dict[str, Any],
    evidence: dict[str, Any],
    *,
    account_name: str,
    family: str,
    now: datetime,
) -> dict[str, Any]:
    """Restore a direct account from readback while preserving capability membership and holds."""
    ResolvedModels.from_json(json.dumps(original))
    account = evidence["account"]
    if account["name"] != account_name or account.get("kind") != "OpenAI":
        raise ValueError("restoration requires the explicitly selected Azure OpenAI account")
    account_id = account["id"]
    parts = account_id.split("/")
    if (
        len(parts) != 9
        or parts[1].casefold() != "subscriptions"
        or parts[2].casefold() != original["subscription_id"].casefold()
        or parts[5:7] != ["providers", "Microsoft.CognitiveServices"]
        or parts[7] != "accounts"
        or parts[8] != account_name
        or account["properties"].get("provisioningState") != "Succeeded"
    ):
        raise ValueError("restoration account identity or provisioning state is invalid")
    endpoint = account["properties"]["endpoint"].rstrip("/")
    if endpoint != f"https://{account_name}.openai.azure.com":
        raise ValueError("restoration requires the account's direct HTTPS origin")
    if original.get("endpoint_bindings") or original.get("binding_policy"):
        raise ValueError("restore reviewed endpoint bindings through their owning policy")
    deployments = {item["name"]: item for item in evidence["deployments"]}
    if len(deployments) != len(evidence["deployments"]):
        raise ValueError("deployment readback contains duplicate names")
    result = copy.deepcopy(original)
    result["narrator"]["endpoint"] = endpoint
    result["region"] = account["location"]
    primary_evidence = {**evidence, "deployments": [deployments["t2.reasoner.primary"]]}
    result = bind_existing_model(result, primary_evidence, family=family, now=now)
    for capability in result["capabilities"]:
        if capability["status"] == "hil-only" or capability["name"] == "t2.reasoner.primary":
            continue
        deployment = deployments.get(capability["name"])
        if deployment is None:
            raise ValueError("configured capability deployment is absent from the selected account")
        model = deployment["properties"]["model"]
        capacity = deployment["sku"]["capacity"]
        if (
            deployment["id"].casefold()
            != f"{account_id}/deployments/{capability['name']}".casefold()
            or deployment["properties"].get("provisioningState") != "Succeeded"
            or model["format"] != "OpenAI"
            or capability["publisher"] != "OpenAI"
            or model["name"] != capability["family"]
            or deployment["sku"]["name"] not in {"Standard", "GlobalStandard", "DataZoneStandard"}
            or type(capacity) is not int
            or capacity <= 0
        ):
            raise ValueError("configured capability does not match the selected account readback")
        capability.update(
            version=model["version"],
            sku=deployment["sku"]["name"],
            capacity_tpm=capacity * 1000,
            selection_mode="pinned",
            reasons=["existing_deployment_observed"],
        )
        capability["capacity"] = {"unit": "tpm", "value": capacity * 1000}
    for key in ("narrator_candidates", "vision_candidates", "web_search_candidates"):
        for candidate in result.get(key, []):
            candidate["endpoint"] = endpoint
    candidates = [result["narrator"]] + [
        candidate
        for key in ("narrator_candidates", "vision_candidates", "web_search_candidates")
        for candidate in result.get(key, [])
    ]
    verified_names = {
        item["name"] for item in result["capabilities"] if item["status"] != "hil-only"
    }
    if any(candidate["deployment"] not in verified_names for candidate in candidates):
        raise ValueError("candidate deployment lacks a verified capability in the selected account")
    ResolvedModels.from_json(json.dumps(result))
    return result


def main() -> int:
    """Write only an ignored local artifact, retaining the exact prior content."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument(
        "--capability",
        choices=("t2.reasoner.primary", "t1.embedding"),
        default="t2.reasoner.primary",
        help="Seal only the selected capability; embedding mode preserves model selection",
    )
    parser.add_argument("--restore-account", help="Explicitly restore an observed direct account")
    parser.add_argument("--backup-dir", type=Path, default=Path(".fdai/model-binding-backups"))
    args = parser.parse_args()
    if args.restore_account and args.capability != "t2.reasoner.primary":
        raise ValueError("embedding binding cannot be combined with account restoration")
    if (
        args.artifact.is_symlink()
        or subprocess.run(
            ["git", "check-ignore", "--quiet", "--", str(args.artifact)],  # noqa: S607
            check=False,
        ).returncode
        != 0
    ):
        raise ValueError("existing model binding requires an ignored, non-symlink artifact")
    original = args.artifact.read_bytes()
    binder = restore_existing_account if args.restore_account else bind_existing_model
    options = (
        {"account_name": args.restore_account}
        if args.restore_account
        else {"capability": args.capability}
    )
    result = binder(
        json.loads(original),
        json.loads(args.evidence.read_text()),
        family=args.family,
        now=datetime.now(UTC),
        **options,
    )
    args.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (
        subprocess.run(
            ["git", "check-ignore", "--quiet", "--", str(args.backup_dir)],  # noqa: S607
            check=False,
        ).returncode
        != 0
    ):
        raise ValueError("model backup directory MUST be ignored")
    backup = args.backup_dir / (
        args.artifact.name + ".before-binding-" + hashlib.sha256(original).hexdigest()[:12]
    )
    if not backup.exists():
        with backup.open("xb") as stream:
            os.chmod(backup, 0o600)
            stream.write(original)
    elif backup.read_bytes() != original:
        raise ValueError("existing model backup does not match the source")
    descriptor, temporary = tempfile.mkstemp(dir=args.artifact.parent, prefix=".model-binding-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if args.artifact.read_bytes() != original:
            raise ValueError("model artifact changed during binding")
        os.replace(temporary, args.artifact)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print("Existing model binding updated; independent review policy preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
