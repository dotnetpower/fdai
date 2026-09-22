#!/usr/bin/env python3
"""Generate missing local model bindings from existing, scope-bound Azure deployments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fdai.rule_catalog.schema.llm_registry import LlmRegistry, load_llm_registry_from_yaml
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    NarratorCandidate,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.rule_catalog.schema.model_endpoint import ModelEndpointBinding


def resolve_existing(
    registry: LlmRegistry,
    accounts: list[dict[str, Any]],
    *,
    subscription_id: str,
    resource_group: str,
    principal_id: str,
) -> ResolvedModels:
    """Select one unambiguous existing OpenAI account; never propose new deployments."""
    candidates: list[ResolvedModels] = []
    for account in accounts:
        expected = (
            f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{account['name']}"
        )
        if account.get("id", "").casefold() != expected.casefold():
            raise ValueError(
                "model account is outside the selected subscription and resource group"
            )
        properties = account.get("properties", {})
        if (
            account.get("kind") not in {"OpenAI", "AIServices"}
            or properties.get("provisioningState") != "Succeeded"
        ):
            continue
        endpoint = properties.get("endpoints", {}).get(
            "OpenAI Language Model Instance API"
        ) or properties.get("endpoint", "")
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("observed model endpoint must be a credential-free HTTPS URL")
        endpoint = f"{parsed.scheme}://{parsed.netloc}"
        deployments = account.get("deployments", [])
        if len(deployments) > 100 or len({item["name"] for item in deployments}) != len(
            deployments
        ):
            raise ValueError("model deployment inventory is duplicated or exceeds its bound")
        observed: dict[str, dict[str, Any]] = {}
        for deployment in deployments:
            if (
                deployment.get("id", "").casefold()
                != f"{expected}/deployments/{deployment['name']}".casefold()
            ):
                raise ValueError("model deployment is outside its observed account")
            model = deployment.get("properties", {}).get("model", {})
            if (
                deployment.get("properties", {}).get("provisioningState") != "Succeeded"
                or model.get("format") != "OpenAI"
            ):
                continue
            sku = deployment.get("sku", {})
            capacity = sku.get("capacity")
            if (
                sku.get("name") not in {"Standard", "GlobalStandard", "DataZoneStandard"}
                or type(capacity) is not int
                or capacity <= 0
            ):
                continue
            if not isinstance(model.get("version"), str) or not model["version"]:
                continue
            observed[deployment["name"]] = deployment
        capabilities: list[ResolvedCapability] = []
        bindings: list[ModelEndpointBinding] = []
        narrators: list[NarratorCandidate] = []
        for name, spec in registry.models.items():
            if name not in {"t1.embedding", "t1.judge", "t2.reasoner.primary"}:
                continue
            selected = observed.get(name)
            if name == "t1.judge":
                for preference in spec.preferences:
                    matches = [
                        item
                        for item in observed.values()
                        if preference.publisher == "OpenAI"
                        and item["properties"]["model"]["name"] == preference.family
                    ]
                    if len(matches) > 1:
                        raise ValueError(
                            "model family has multiple deployments; "
                            "select an explicit model artifact"
                        )
                    if matches:
                        narrators.append(NarratorCandidate(endpoint, matches[0]["name"]))
                        selected = selected or matches[0]
            capability = ResolvedCapability(
                name=name,
                status=CapabilityStatus.HIL_ONLY,
                publisher=None,
                family=None,
                sku=None,
                capacity_tpm=0,
                invocation=spec.invocation.value,
                reasons=("existing_deployment_not_bound",),
            )
            if selected is not None and any(
                preference.publisher == "OpenAI"
                and preference.family == selected["properties"]["model"]["name"]
                for preference in spec.preferences
            ):
                capability = replace(
                    capability,
                    status=CapabilityStatus.RESOLVED,
                    publisher="OpenAI",
                    family=selected["properties"]["model"]["name"],
                    version=selected["properties"]["model"]["version"],
                    sku=selected["sku"]["name"],
                    capacity_tpm=selected["sku"]["capacity"] * 1000,
                    selection_mode="pinned",
                    reasons=("existing_deployment_observed",),
                )
                if selected["name"] != name:
                    bindings.append(
                        ModelEndpointBinding.from_dict(
                            {
                                "binding_id": f"local-existing:{name}",
                                "capability": name,
                                "provider_kind": "azure-openai",
                                "route_kind": "direct",
                                "api_style": "azure-openai",
                                "endpoint_ref": f"azure-openai:{account['name']}",
                                "deployment": selected["name"],
                                "api_version": "2024-08-01-preview",
                                "auth": {
                                    "kind": "entra",
                                    "audience": "https://cognitiveservices.azure.com/.default",
                                },
                                "model": {
                                    "publisher": "OpenAI",
                                    "family": capability.family,
                                    "version": capability.version,
                                },
                                "capacity": {"unit": "tpm", "value": capability.capacity_tpm},
                                "features": {
                                    "streaming": False,
                                    "embeddings": False,
                                    "structured_output": False,
                                    "tool_calling": False,
                                },
                                "discovery": {
                                    "source": "azure-management",
                                    "resource_ref_digest": hashlib.sha256(
                                        selected["id"].encode()
                                    ).hexdigest(),
                                    "verified_at": datetime.now(UTC).isoformat(),
                                },
                            }
                        )
                    )
            if capability.status is CapabilityStatus.RESOLVED:
                capabilities.append(capability)
        if not narrators or not any(
            item.name == "t1.embedding" and item.status is CapabilityStatus.RESOLVED
            for item in capabilities
        ):
            continue
        candidates.append(
            ResolvedModels(
                schema_version="1.0.0",
                region=account["location"],
                subscription_id=subscription_id,
                deployer_object_id=principal_id,
                mixed_model_mode="hil-only",
                capabilities=tuple(capabilities),
                narrator=narrators[0],
                narrator_candidates=tuple(narrators),
                endpoint_bindings=tuple(bindings),
            )
        )
    if len(candidates) != 1:
        raise ValueError(
            "local models require exactly one account with a registry-matched narrator "
            "and embedding deployment; select an explicit artifact or provision missing models"
        )
    return candidates[0]


def validate_artifact(target: Path) -> ResolvedModels:
    """Validate an existing private model selection without changing its bytes or policy."""
    metadata = target.stat()
    if target.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 1_000_000:
        raise ValueError("model artifact must be a bounded regular file")
    resolved = ResolvedModels.from_json(target.read_text(encoding="utf-8"))
    if resolved.narrator is None and not resolved.narrator_candidates:
        raise ValueError("existing model artifact has no narrator binding")
    return resolved


def eligible_vision_artifact(target: Path) -> bool:
    """Reuse vision settings only when the runtime's capability and route fences hold."""
    try:
        resolved = validate_artifact(target)
    except (OSError, ValueError, TypeError, KeyError):
        return False
    bindable = {
        item.name
        for item in resolved.capabilities
        if item.status in {CapabilityStatus.RESOLVED, CapabilityStatus.CAPACITY_REDUCED}
    }
    narrators = resolved.narrator_candidates or (resolved.narrator,)
    return (
        "t1.embedding" in bindable
        and (
            {"t2.reasoner.primary", "t2.reasoner.secondary"} <= bindable
            or resolved.mixed_model_mode == "hil-only"
        )
        and bool(resolved.vision_candidates)
        and len({item.deployment for item in resolved.vision_candidates})
        == len(resolved.vision_candidates)
        and all(item in narrators for item in resolved.vision_candidates)
    )


def write_artifact(target: Path, content: str) -> None:
    """Publish a complete owner-only artifact atomically without replacing an existing file."""
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=".local-models-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
    finally:
        os.unlink(temporary)


def main() -> int:
    """Reuse a selected artifact or create one privately from bounded read-only discovery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--resource-group", default="")
    args = parser.parse_args()
    override = os.environ.get("FDAI_LOCAL_RESOLVED_MODELS_PATH", "")
    target = Path(override or args.repo_root / "resolved-models.json")
    if target.is_symlink():
        raise ValueError("model artifact must not be a symbolic link")
    vision = args.repo_root / ".fdai/resolved-models-vision.json"
    if override and not target.is_absolute():
        raise ValueError("explicit model artifact must have an absolute path")
    if not override and eligible_vision_artifact(vision):
        print("local-models: reused selected vision artifact")
        return 0
    if target.exists():
        validate_artifact(target)
        print("local-models: reused")
        return 0
    if os.environ.get("FDAI_LOCAL_RESOLVED_MODELS_PATH"):
        raise ValueError(
            "explicit model artifact is missing; refusing to replace the selected policy"
        )
    ignored = subprocess.run(
        ["git", "-C", str(args.repo_root), "check-ignore", "--quiet", "--", str(target)],
        capture_output=True,
        timeout=5,
        check=False,
    )
    if ignored.returncode != 0:
        raise ValueError("generated model artifact must be ignored by git")

    deadline = time.monotonic() + 120

    def command(arguments: list[str]) -> Any:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("model discovery exceeded its total deadline")
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            timeout=min(20, remaining),
            check=False,
        )
        if result.returncode:
            raise ValueError(
                "existing Azure model discovery failed; check login and selected scope"
            )
        if len(result.stdout) > 2_000_000:
            raise ValueError("model discovery response exceeds its byte bound")
        return json.loads(result.stdout)

    def azure(*arguments: str) -> Any:
        return command([os.environ.get("FDAI_AZ_BIN", "az"), *arguments, "--output", "json"])

    if not re.fullmatch(r"[A-Za-z0-9._()-]{1,90}", args.resource_group):
        raise ValueError("model discovery requires an explicitly selected resource group")
    identity = azure("account", "show")
    subscription = identity["id"]
    principal = azure("ad", "signed-in-user", "show", "--query", "id")
    accounts = azure(
        "cognitiveservices",
        "account",
        "list",
        "--subscription",
        subscription,
        "--resource-group",
        args.resource_group,
    )
    if len(accounts) > 8:
        raise ValueError("model account discovery exceeds its eight-account bound")
    for account in accounts:
        if account.get("kind") not in {"OpenAI", "AIServices"}:
            continue
        account["deployments"] = azure(
            "cognitiveservices",
            "account",
            "deployment",
            "list",
            "--subscription",
            subscription,
            "--resource-group",
            args.resource_group,
            "--name",
            account["name"],
        )
    registry = load_llm_registry_from_yaml(args.repo_root / "rule-catalog/llm-registry.yaml")
    resolved = resolve_existing(
        registry,
        accounts,
        subscription_id=subscription,
        resource_group=args.resource_group,
        principal_id=principal,
    )
    content = resolved.to_json()
    ResolvedModels.from_json(content)
    write_artifact(target, content)
    print("local-models: generated from observed deployments; model invocation not yet verified")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, TypeError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(
            f"local-models: preparation failed ({type(error).__name__}); "
            "check the selected scope and existing deployments"
        ) from None
