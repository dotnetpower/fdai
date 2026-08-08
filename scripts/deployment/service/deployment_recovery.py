#!/usr/bin/env python3
"""Verify exact service health and build bounded Container Apps rollback commands."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_DIGEST_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}")


class DeploymentRecoveryError(ValueError):
    """Raised when health or rollback evidence does not match the sealed target."""


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeploymentRecoveryError(f"{path.name} must contain a JSON object")
    return value


def _required(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise DeploymentRecoveryError(f"{label} is missing")
    return value


def _revision_image(revision: dict[str, Any]) -> str:
    properties = revision.get("properties")
    template = properties.get("template") if isinstance(properties, dict) else None
    containers = template.get("containers") if isinstance(template, dict) else None
    if not isinstance(containers, list) or len(containers) != 1:
        raise DeploymentRecoveryError("revision must contain exactly one container")
    image = containers[0].get("image") if isinstance(containers[0], dict) else None
    if not isinstance(image, str) or _DIGEST_IMAGE.fullmatch(image) is None:
        raise DeploymentRecoveryError("revision image must be pinned by sha256 digest")
    return image


def _target(context: dict[str, Any]) -> dict[str, Any]:
    target = context.get("target")
    if not isinstance(target, dict):
        raise DeploymentRecoveryError("sealed context has no target")
    return target


def validate_health(
    *,
    context: dict[str, Any],
    service_output: dict[str, Any],
    account: dict[str, Any],
    app: dict[str, Any],
    revision: dict[str, Any],
    previous_revision: str,
) -> None:
    """Require exact Azure identity, component, digest, and a new healthy revision."""
    target = _target(context)
    expected_subscription = _required(context, "subscription_id", label="subscription id")
    if str(account.get("id", "")).lower() != expected_subscription.lower():
        raise DeploymentRecoveryError("Azure account subscription does not match sealed context")
    expected_id = _required(target, "service_resource_id", label="service resource id")
    expected_name = _required(target, "service_name", label="service name")
    expected_component = _required(target, "component_tag", label="component tag")
    expected_image = _required(target, "image_ref", label="image reference")
    if str(service_output.get("id", "")).lower() != expected_id.lower():
        raise DeploymentRecoveryError("Terraform service resource id does not match sealed context")
    if service_output.get("name") != expected_name:
        raise DeploymentRecoveryError("Terraform service name does not match sealed context")
    if str(app.get("id", "")).lower() != expected_id.lower() or app.get("name") != expected_name:
        raise DeploymentRecoveryError(
            "observed Container App identity does not match sealed context"
        )
    tags = app.get("tags")
    if not isinstance(tags, dict) or tags.get("fdai:component") != expected_component:
        raise DeploymentRecoveryError("observed component tag does not match sealed context")
    app_properties = app.get("properties")
    latest_revision = (
        app_properties.get("latestRevisionName") if isinstance(app_properties, dict) else None
    )
    terraform_revision = service_output.get("latest_revision_name")
    if not isinstance(latest_revision, str) or latest_revision != terraform_revision:
        raise DeploymentRecoveryError("latest revision does not match Terraform output")
    if latest_revision == previous_revision:
        raise DeploymentRecoveryError("post-apply health did not observe a new revision")
    if revision.get("name") != latest_revision:
        raise DeploymentRecoveryError("health evidence is not for the new revision")
    properties = revision.get("properties")
    if not isinstance(properties, dict):
        raise DeploymentRecoveryError("revision properties are missing")
    if properties.get("provisioningState") != "Provisioned":
        raise DeploymentRecoveryError("new revision is not Provisioned")
    if properties.get("healthState") != "Healthy" or properties.get("active") is not True:
        raise DeploymentRecoveryError("new revision is not healthy and active")
    if _revision_image(revision) != expected_image:
        raise DeploymentRecoveryError("new revision image digest does not match sealed context")


def capture_snapshot(
    *,
    context: dict[str, Any],
    account: dict[str, Any],
    app: dict[str, Any],
    revision: dict[str, Any],
    rollback_contract: dict[str, Any],
) -> dict[str, Any]:
    """Capture the exact current revision and image before applying a protected plan."""
    target = _target(context)
    expected_subscription = _required(context, "subscription_id", label="subscription id")
    if str(account.get("id", "")).lower() != expected_subscription.lower():
        raise DeploymentRecoveryError("Azure account subscription does not match sealed context")
    expected_id = _required(target, "service_resource_id", label="service resource id")
    if str(app.get("id", "")).lower() != expected_id.lower():
        raise DeploymentRecoveryError("rollback snapshot resource id does not match sealed context")
    properties = app.get("properties")
    previous_revision = (
        properties.get("latestRevisionName") if isinstance(properties, dict) else None
    )
    if not isinstance(previous_revision, str) or revision.get("name") != previous_revision:
        raise DeploymentRecoveryError("rollback snapshot revision is not the current revision")
    authority_fallback = rollback_contract.get("authority_fallback", "")
    if authority_fallback not in ("", "core-in-process"):
        raise DeploymentRecoveryError("rollback authority fallback is unsupported")
    return {
        "subscription_id": expected_subscription,
        "service_resource_id": expected_id,
        "service_name": _required(target, "service_name", label="service name"),
        "resource_group": _required(target, "resource_group", label="resource group"),
        "component_tag": _required(target, "component_tag", label="component tag"),
        "previous_revision": previous_revision,
        "previous_image": _revision_image(revision),
        "platform_rollback_required": authority_fallback == "core-in-process",
    }


def rollback_command(snapshot: dict[str, Any], *, revision_suffix: str) -> list[str]:
    """Build a bounded revision-copy rollback using the exact captured revision and image."""
    if not re.fullmatch(r"[a-z0-9-]{1,50}", revision_suffix):
        raise DeploymentRecoveryError("rollback revision suffix is invalid")
    command = [
        "az",
        "containerapp",
        "revision",
        "copy",
        "--resource-group",
        _required(snapshot, "resource_group", label="resource group"),
        "--name",
        _required(snapshot, "service_name", label="service name"),
        "--from-revision",
        _required(snapshot, "previous_revision", label="previous revision"),
        "--image",
        _required(snapshot, "previous_image", label="previous image"),
        "--revision-suffix",
        revision_suffix,
        "--only-show-errors",
        "--output",
        "json",
    ]
    return command


def validate_rollback(
    *,
    snapshot: dict[str, Any],
    account: dict[str, Any],
    app: dict[str, Any],
    revision: dict[str, Any],
) -> None:
    """Require a new healthy revision running the exact captured image after rollback."""
    expected_subscription = _required(snapshot, "subscription_id", label="subscription id")
    if str(account.get("id", "")).lower() != expected_subscription.lower():
        raise DeploymentRecoveryError("rollback subscription does not match snapshot")
    expected_id = _required(snapshot, "service_resource_id", label="service resource id")
    expected_name = _required(snapshot, "service_name", label="service name")
    if str(app.get("id", "")).lower() != expected_id.lower() or app.get("name") != expected_name:
        raise DeploymentRecoveryError("rollback Container App identity does not match snapshot")
    tags = app.get("tags")
    if not isinstance(tags, dict) or tags.get("fdai:component") != snapshot.get("component_tag"):
        raise DeploymentRecoveryError("rollback component tag does not match snapshot")
    properties = app.get("properties")
    latest_revision = properties.get("latestRevisionName") if isinstance(properties, dict) else None
    previous_revision = _required(snapshot, "previous_revision", label="previous revision")
    if not isinstance(latest_revision, str) or latest_revision == previous_revision:
        raise DeploymentRecoveryError("rollback did not create a new recovery revision")
    revision_properties = revision.get("properties")
    if revision.get("name") != latest_revision or not isinstance(revision_properties, dict):
        raise DeploymentRecoveryError("rollback evidence is not for the recovery revision")
    if (
        revision_properties.get("provisioningState") != "Provisioned"
        or revision_properties.get("healthState") != "Healthy"
        or revision_properties.get("active") is not True
    ):
        raise DeploymentRecoveryError("rollback revision is not healthy and active")
    if _revision_image(revision) != _required(snapshot, "previous_image", label="previous image"):
        raise DeploymentRecoveryError("rollback revision image does not match snapshot")


def main() -> int:
    """Validate health, capture a rollback snapshot, or emit a rollback command."""
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify")
    capture = commands.add_parser("capture")
    for command in (verify, capture):
        command.add_argument("--context", type=Path, required=True)
        command.add_argument("--account", type=Path, required=True)
        command.add_argument("--app", type=Path, required=True)
        command.add_argument("--revision", type=Path, required=True)
    verify.add_argument("--service-output", type=Path, required=True)
    verify.add_argument("--previous-revision", required=True)
    capture.add_argument("--rollback-contract", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    rollback = commands.add_parser("rollback-command")
    rollback.add_argument("--snapshot", type=Path, required=True)
    rollback.add_argument("--revision-suffix", required=True)
    rollback_verify = commands.add_parser("verify-rollback")
    rollback_verify.add_argument("--snapshot", type=Path, required=True)
    rollback_verify.add_argument("--account", type=Path, required=True)
    rollback_verify.add_argument("--app", type=Path, required=True)
    rollback_verify.add_argument("--revision", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_health(
                context=_object(args.context),
                service_output=_object(args.service_output),
                account=_object(args.account),
                app=_object(args.app),
                revision=_object(args.revision),
                previous_revision=args.previous_revision,
            )
        elif args.command == "capture":
            snapshot = capture_snapshot(
                context=_object(args.context),
                account=_object(args.account),
                app=_object(args.app),
                revision=_object(args.revision),
                rollback_contract=_object(args.rollback_contract),
            )
            args.output.write_text(json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8")
        elif args.command == "rollback-command":
            values = rollback_command(_object(args.snapshot), revision_suffix=args.revision_suffix)
            sys.stdout.buffer.write("\0".join(values).encode() + b"\0")
        else:
            validate_rollback(
                snapshot=_object(args.snapshot),
                account=_object(args.account),
                app=_object(args.app),
                revision=_object(args.revision),
            )
    except (OSError, json.JSONDecodeError, DeploymentRecoveryError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
