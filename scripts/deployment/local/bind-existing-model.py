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
) -> dict[str, Any]:
    """Preserve T1 and review policy while binding only the requested T2 producer."""
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
    if any(
        item["name"] == "t2.reasoner.secondary"
        and item["status"] in {"resolved", "capacity-reduced"}
        and item.get("publisher") == "OpenAI"
        for item in result["capabilities"]
    ):
        raise ValueError("T2 primary binding MUST preserve the distinct-publisher reviewer")
    primary = next(item for item in result["capabilities"] if item["name"] == "t2.reasoner.primary")
    primary.update(
        status="resolved",
        publisher="OpenAI",
        family=family,
        version=version,
        sku=deployment["sku"]["name"],
        capacity_tpm=capacity * 1000,
        selection_mode="pinned",
        reasons=["existing_deployment_observed"],
    )
    primary["capacity"] = {"unit": "tpm", "value": capacity * 1000}
    binding = {
        "binding_id": "local-existing:t2.reasoner.primary",
        "capability": "t2.reasoner.primary",
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
            "embeddings": False,
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
        item
        for item in result.get("endpoint_bindings", [])
        if item["capability"] != "t2.reasoner.primary"
    ] + [binding]
    result.pop("reasoner_primary_candidates", None)
    ResolvedModels.from_json(json.dumps(result))
    return result


def main() -> int:
    """Write only an ignored local artifact, retaining the exact prior content."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--backup-dir", type=Path, default=Path(".fdai/model-binding-backups"))
    args = parser.parse_args()
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
    result = bind_existing_model(
        json.loads(original),
        json.loads(args.evidence.read_text()),
        family=args.family,
        now=datetime.now(UTC),
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
    print("Existing T2 primary deployment bound; T1 and independent review policy preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
