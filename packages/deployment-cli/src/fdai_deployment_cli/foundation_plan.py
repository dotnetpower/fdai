"""Private saved foundation plans and non-authoritative integrity verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai_deployment_cli.contracts import (
    ProvisionProfile,
    canonical_bytes,
    canonical_digest,
    load_json_object,
)
from fdai_deployment_cli.private_output import (
    read_private_bytes,
    write_private_bytes,
    write_private_output,
)
from fdai_deployment_cli.profile import load_profile

PLAN_NAME = "foundation.tfplan"
REVIEW_NAME = "foundation-plan.json"
_MAX_PLAN_BYTES = 64 * 1024 * 1024
_MAX_JSON_BYTES = 16 * 1024 * 1024
_SCHEMA = "fdai.foundation-saved-plan.v1"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_CONTEXT_KEYS = {
    "offline_manifest_digest",
    "deployment_bundle_digest",
    "profile_digest",
    "target_binding",
    "variables_digest",
    "terraform_digest",
    "provider_lock_digest",
    "run_digest",
    "foundation_context_digest",
    "source_commit",
}
_AUTHORITY = {
    "apply_authorized": False,
    "source_eligibility_verified": False,
    "plan_origin_verified": False,
    "subscription_ready": False,
    "mutation_performed": False,
}


def foundation_plan_context(
    *,
    profile: ProvisionProfile,
    variables: dict[str, object],
    offline_manifest_digest: str,
    deployment_bundle_digest: str,
    terraform_digest: str,
    provider_lock: bytes,
) -> dict[str, object]:
    """Bind verified artifact metadata to normalized variables, not source eligibility."""

    result = {
        "offline_manifest_digest": offline_manifest_digest,
        "deployment_bundle_digest": deployment_bundle_digest,
        "profile_digest": canonical_digest(profile.to_mapping()),
        "target_binding": profile.target_binding,
        "variables_digest": canonical_digest(variables),
        "terraform_digest": terraform_digest,
        "provider_lock_digest": hashlib.sha256(provider_lock).hexdigest(),
        "source_commit": variables["source_commit"],
        "run_digest": variables["run_digest"],
        "foundation_context_digest": variables["foundation_context_digest"],
    }
    _validate_context(result)
    return result


def save_foundation_plan(
    *,
    plan: Path,
    destination: Path,
    terraform: Path,
    root: Path,
    environment: dict[str, str],
    context: dict[str, object],
    variables: dict[str, object],
) -> dict[str, object]:
    """Validate the exact saved plan and publish private bytes plus a review receipt.

    The caller owns a new private destination and a temporary private plan directory.
    No provider values reach the receipt. Source SHA and local time are declarations,
    not provenance or authenticated approval-time evidence. No apply is performed.
    """

    _validate_context(context)
    if context["variables_digest"] != canonical_digest(variables):
        raise ValueError("foundation plan variables do not match the saved context")
    payload = read_private_bytes(plan, max_bytes=_MAX_PLAN_BYTES)
    projection = plan.parent / "plan.json"
    descriptor = os.open(projection, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        shown = subprocess.run(
            [str(terraform), "show", "-json", str(plan)],
            cwd=root,
            env=environment,
            stdout=stream,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=300,
            umask=0o077,
        )
    if shown.returncode != 0:
        raise ValueError("saved foundation plan could not be inspected")
    projected = read_private_bytes(projection, max_bytes=_MAX_JSON_BYTES)
    details = load_json_object(projected, label="saved foundation plan", max_bytes=_MAX_JSON_BYTES)
    version = _validate_projection(details, variables)
    if read_private_bytes(plan, max_bytes=_MAX_PLAN_BYTES) != payload:
        raise ValueError("saved foundation plan changed during inspection")
    now = datetime.now(UTC).replace(microsecond=0)
    receipt: dict[str, object] = {
        "schema_version": _SCHEMA,
        "state": "review",
        **_AUTHORITY,
        "context": context,
        "plan_digest": hashlib.sha256(payload).hexdigest(),
        "plan_json_digest": hashlib.sha256(projected).hexdigest(),
        "terraform_version": version,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
    }
    receipt["review_digest"] = canonical_digest(receipt)
    output = destination / PLAN_NAME
    write_private_bytes(output, payload)
    try:
        write_private_output(
            destination / REVIEW_NAME, (canonical_bytes(receipt) + b"\n").decode("utf-8")
        )
    except (OSError, ValueError):
        output.unlink()
        raise
    return receipt


def verify_foundation_plan(
    *, directory: Path, profile: ProvisionProfile, expected_review_digest: str
) -> dict[str, object]:
    """Check private saved bytes against a separately retained digest; never approve apply."""

    if _DIGEST.fullmatch(expected_review_digest) is None:
        raise ValueError("expected foundation review digest is invalid")
    receipt = load_json_object(
        read_private_bytes(directory / REVIEW_NAME, max_bytes=65_536),
        label="foundation review",
    )
    expected_keys = {
        "schema_version",
        "state",
        "context",
        "plan_digest",
        "plan_json_digest",
        "terraform_version",
        "created_at",
        "expires_at",
        "review_digest",
        *_AUTHORITY,
    }
    if (
        set(receipt) != expected_keys
        or receipt["schema_version"] != _SCHEMA
        or receipt["state"] != "review"
        or any(receipt[key] is not value for key, value in _AUTHORITY.items())
    ):
        raise ValueError("foundation review schema or authority is invalid")
    digest = receipt.pop("review_digest")
    if digest != expected_review_digest or canonical_digest(receipt) != expected_review_digest:
        raise ValueError("foundation review digest does not match")
    context = receipt["context"]
    if not isinstance(context, dict) or set(context) != _CONTEXT_KEYS:
        raise ValueError("foundation review context is invalid")
    _validate_context(context)
    if (
        context["profile_digest"] != canonical_digest(profile.to_mapping())
        or context["target_binding"] != profile.target_binding
    ):
        raise ValueError("foundation review does not match the profile")
    _validate_review_time(receipt)
    payload = read_private_bytes(directory / PLAN_NAME, max_bytes=_MAX_PLAN_BYTES)
    if hashlib.sha256(payload).hexdigest() != receipt["plan_digest"]:
        raise ValueError("saved foundation plan digest does not match")
    return {
        "schema_version": "fdai.foundation-plan-integrity.v1",
        "state": "review",
        "review_digest": expected_review_digest,
        "plan_digest": receipt["plan_digest"],
        "integrity_verified": True,
        **_AUTHORITY,
    }


def _validate_context(context: dict[str, object]) -> None:
    if set(context) != _CONTEXT_KEYS:
        raise ValueError("foundation plan context fields are invalid")
    for key, value in context.items():
        pattern = r"[0-9a-f]{40}" if key == "source_commit" else r"[0-9a-f]{64}"
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            raise ValueError("foundation plan context binding is invalid")


def _validate_projection(details: dict[str, object], variables: dict[str, object]) -> str:
    if (
        details.get("format_version") not in ("1.1", "1.2")
        or details.get("complete") is not True
        or details.get("errored") is not False
        or type(details.get("applyable")) is not bool
        or details.get("deferred_changes")
    ):
        raise ValueError("saved foundation plan is incomplete or unsupported")
    version = details.get("terraform_version")
    if not isinstance(version, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError("saved foundation plan Terraform version is invalid")
    actual = details.get("variables")
    if not isinstance(actual, dict) or any(
        canonical_bytes(actual.get(key)) != canonical_bytes({"value": value})
        for key, value in variables.items()
    ):
        raise ValueError("saved foundation plan does not match the normalized input")
    return version


def _validate_review_time(receipt: dict[str, object]) -> None:
    timestamps: list[datetime] = []
    for key in ("created_at", "expires_at"):
        value = receipt[key]
        if not isinstance(value, str) or not value:
            raise ValueError("foundation review timestamp is invalid")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("foundation review timestamp is invalid") from None
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("foundation review timestamp MUST be UTC")
        timestamps.append(parsed)
    created, expires = timestamps
    if expires - created != timedelta(hours=1) or not created <= datetime.now(UTC) < expires:
        raise ValueError("foundation review is expired or outside its local time window")


def register_foundation_plan_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register local saved-plan verification without Azure access or execution."""

    parser = commands.add_parser("verify-foundation-plan")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--expected-review-digest", required=True)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    parser.set_defaults(handler=_verify_command)


def _verify_command(args: argparse.Namespace) -> int:
    result = verify_foundation_plan(
        directory=args.directory,
        profile=load_profile(args.profile),
        expected_review_digest=args.expected_review_digest,
    )
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.output == "json"
        else "saved foundation plan integrity verified; protected approval remains required"
    )
    return 0
