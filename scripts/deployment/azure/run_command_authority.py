"""Validate current human approval and authoritative Azure target identity."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fdai_deployment_cli.contracts import ProvisionProfile, canonical_digest
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.target import compute_target_binding

_DIGEST = re.compile(r"[0-9a-f]{64}")
_GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

Capture = Callable[[tuple[str, ...]], str]


def validate_transport_authority(
    *,
    target: dict[str, object],
    profile_value: dict[str, object],
    approval: dict[str, object],
    operation_id: str,
    bundle_receipt_digest: str,
    receiver_digest: str,
    capture: Callable[..., str],
    deadline: DeploymentDeadline,
    now: datetime | None = None,
) -> str:
    """Require approved profile, current human actor, and exact live VM identity."""

    subscription_id, tenant_id, target_binding = _validate_authority_inputs(
        target=target,
        profile_value=profile_value,
        approval=approval,
        operation_id=operation_id,
        bundle_receipt_digest=bundle_receipt_digest,
        receiver_digest=receiver_digest,
        now=now or datetime.now(UTC),
    )
    _validate_human_actor(
        approval=approval,
        target_binding=target_binding,
        subscription_id=subscription_id,
        tenant_id=tenant_id,
        capture=capture,
        deadline=deadline,
    )
    _validate_vm_readback(
        target=target,
        subscription_id=subscription_id,
        capture=capture,
        deadline=deadline,
    )
    return str(approval["approval_digest"])


def capture_transport_authority(
    *,
    target: dict[str, object],
    profile_value: dict[str, object],
    approval: dict[str, object],
    operation_id: str,
    bundle_receipt_digest: str,
    receiver_digest: str,
    capture: Callable[..., str],
    deadline: DeploymentDeadline,
    now: datetime | None = None,
) -> dict[str, object]:
    """Capture a content-bound human authority receipt for distinct executor use."""

    moment = now or datetime.now(UTC)
    validate_transport_authority(
        target=target,
        profile_value=profile_value,
        approval=approval,
        operation_id=operation_id,
        bundle_receipt_digest=bundle_receipt_digest,
        receiver_digest=receiver_digest,
        capture=capture,
        deadline=deadline,
        now=moment,
    )
    receipt: dict[str, object] = {
        "schema_version": "fdai.run-command-private-relay-authority-receipt.v1",
        "state": "authorized",
        "target_binding": target["target_binding"],
        "target_digest": canonical_digest(target),
        "profile_digest": canonical_digest(
            ProvisionProfile.from_mapping(profile_value).to_mapping()
        ),
        "operation_id": operation_id,
        "bundle_receipt_digest": bundle_receipt_digest,
        "receiver_digest": receiver_digest,
        "approval_digest": approval["approval_digest"],
        "actor_digest": approval["actor_digest"],
        "authorized_at": moment.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "expires_at": approval["expires_at"],
        "human_actor_verified": True,
        "vm_readback_verified": True,
        "mutation_performed": False,
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    return receipt


def validate_delegated_transport_authority(
    *,
    target: dict[str, object],
    profile_value: dict[str, object],
    approval: dict[str, object],
    authority_receipt: dict[str, object],
    operation_id: str,
    bundle_receipt_digest: str,
    receiver_digest: str,
    capture: Callable[..., str],
    deadline: DeploymentDeadline,
    now: datetime | None = None,
) -> str:
    """Verify local human authority and the exact delegated Managed Identity."""

    moment = now or datetime.now(UTC)
    subscription_id, tenant_id, target_binding = _validate_authority_inputs(
        target=target,
        profile_value=profile_value,
        approval=approval,
        operation_id=operation_id,
        bundle_receipt_digest=bundle_receipt_digest,
        receiver_digest=receiver_digest,
        now=moment,
    )
    _validate_authority_receipt(
        authority_receipt,
        target=target,
        profile_value=profile_value,
        approval=approval,
        operation_id=operation_id,
        bundle_receipt_digest=bundle_receipt_digest,
        receiver_digest=receiver_digest,
        now=moment,
    )
    account = _capture_json(
        capture,
        (
            "az",
            "account",
            "show",
            "--subscription",
            subscription_id,
            "--query",
            "{subscription_id:id,tenant_id:tenantId,user_type:user.type}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        "run command executor account",
        timeout=deadline.remaining(120),
    )
    if (
        account.get("subscription_id") != subscription_id
        or account.get("tenant_id") != tenant_id
        or account.get("user_type") != "servicePrincipal"
    ):
        raise ValueError("run command executor account differs from the approved target")
    token = capture(
        (
            "az",
            "account",
            "get-access-token",
            "--subscription",
            subscription_id,
            "--resource",
            "https://management.azure.com/",
            "--query",
            "accessToken",
            "--output",
            "tsv",
            "--only-show-errors",
        ),
        timeout=deadline.remaining(120),
    ).strip()
    if _token_principal(token) != _required_guid(target, "identity_principal_id"):
        raise ValueError("run command executor principal differs from the approved identity")
    _validate_vm_readback(
        target=target,
        subscription_id=subscription_id,
        capture=capture,
        deadline=deadline,
    )
    if authority_receipt.get("target_binding") != target_binding:
        raise ValueError("run command delegated authority target differs")
    return str(approval["approval_digest"])


def _validate_authority_inputs(
    *,
    target: dict[str, object],
    profile_value: dict[str, object],
    approval: dict[str, object],
    operation_id: str,
    bundle_receipt_digest: str,
    receiver_digest: str,
    now: datetime,
) -> tuple[str, str, str]:
    profile = ProvisionProfile.from_mapping(profile_value)
    if (
        profile.environment != "dev"
        or profile.approval_quorum != 1
        or profile.host != "existing-host"
        or profile.transport != "manual"
        or profile.access_method != "run_command"
        or profile.target_binding != target.get("target_binding")
    ):
        raise ValueError("run command provision profile does not authorize this target")
    subscription_id = _required_guid(target, "subscription_id")
    tenant_id = _required_guid(target, "tenant_id")
    target_binding = str(target.get("target_binding", ""))
    if (
        compute_target_binding(tenant_id=tenant_id, subscription_id=subscription_id)
        != target_binding
    ):
        raise ValueError("run command target binding differs from Azure coordinates")

    target_digest = canonical_digest(target)
    profile_digest = canonical_digest(profile.to_mapping())
    _validate_approval(
        approval,
        target_binding=target_binding,
        target_digest=target_digest,
        profile_digest=profile_digest,
        operation_id=operation_id,
        bundle_receipt_digest=bundle_receipt_digest,
        receiver_digest=receiver_digest,
        now=now or datetime.now(UTC),
    )
    return subscription_id, tenant_id, target_binding


def _validate_human_actor(
    *,
    approval: dict[str, object],
    target_binding: str,
    subscription_id: str,
    tenant_id: str,
    capture: Callable[..., str],
    deadline: DeploymentDeadline,
) -> None:
    account = _capture_json(
        capture,
        (
            "az",
            "account",
            "show",
            "--subscription",
            subscription_id,
            "--query",
            "{subscription_id:id,tenant_id:tenantId,user_name:user.name,user_type:user.type}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        "run command approval actor",
        timeout=deadline.remaining(120),
    )
    login = account.get("user_name")
    if (
        account.get("subscription_id") != subscription_id
        or account.get("tenant_id") != tenant_id
        or account.get("user_type") != "user"
        or not isinstance(login, str)
        or not login.strip()
        or _actor_digest(target_binding, login) != approval.get("actor_digest")
    ):
        raise ValueError("current Azure actor does not match run command approval")


def _validate_vm_readback(
    *,
    target: dict[str, object],
    subscription_id: str,
    capture: Callable[..., str],
    deadline: DeploymentDeadline,
) -> None:

    resource_id = target.get("vm_resource_id")
    if not isinstance(resource_id, str) or not resource_id.startswith(
        f"/subscriptions/{subscription_id}/"
    ):
        raise ValueError("run command VM resource identity is invalid")
    vm = _capture_json(
        capture,
        (
            "az",
            "vm",
            "show",
            "--ids",
            resource_id,
            "--show-details",
            "--query",
            "{id:id,private_ips:privateIps,identities:identity.userAssignedIdentities}",
            "--output",
            "json",
            "--only-show-errors",
        ),
        "run command VM readback",
        timeout=deadline.remaining(120),
    )
    private_ips = vm.get("private_ips")
    observed_ips = (
        {item.strip() for item in private_ips.split(",") if item.strip()}
        if isinstance(private_ips, str)
        else set()
    )
    identities = vm.get("identities")
    expected_client = _required_guid(target, "identity_client_id")
    expected_principal = _required_guid(target, "identity_principal_id")
    matches = (
        [
            value
            for value in identities.values()
            if isinstance(identities, dict)
            and isinstance(value, dict)
            and value.get("clientId") == expected_client
            and value.get("principalId") == expected_principal
        ]
        if isinstance(identities, dict)
        else []
    )
    if (
        str(vm.get("id", "")).casefold() != resource_id.casefold()
        or target.get("host_private_ip") not in observed_ips
        or len(matches) != 1
    ):
        raise ValueError("run command VM readback differs from the approved target")


def _validate_authority_receipt(
    receipt: dict[str, object],
    *,
    target: dict[str, object],
    profile_value: dict[str, object],
    approval: dict[str, object],
    operation_id: str,
    bundle_receipt_digest: str,
    receiver_digest: str,
    now: datetime,
) -> None:
    expected = {
        "schema_version",
        "state",
        "target_binding",
        "target_digest",
        "profile_digest",
        "operation_id",
        "bundle_receipt_digest",
        "receiver_digest",
        "approval_digest",
        "actor_digest",
        "authorized_at",
        "expires_at",
        "human_actor_verified",
        "vm_readback_verified",
        "mutation_performed",
        "receipt_digest",
    }
    digest = receipt.get("receipt_digest")
    document = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    authorized_at = _moment(receipt.get("authorized_at"), "authorized_at")
    expires_at = _moment(receipt.get("expires_at"), "expires_at")
    if (
        set(receipt) != expected
        or receipt.get("schema_version") != "fdai.run-command-private-relay-authority-receipt.v1"
        or receipt.get("state") != "authorized"
        or receipt.get("target_binding") != target.get("target_binding")
        or receipt.get("target_digest") != canonical_digest(target)
        or receipt.get("profile_digest")
        != canonical_digest(ProvisionProfile.from_mapping(profile_value).to_mapping())
        or receipt.get("operation_id") != operation_id
        or receipt.get("bundle_receipt_digest") != bundle_receipt_digest
        or receipt.get("receiver_digest") != receiver_digest
        or receipt.get("approval_digest") != approval.get("approval_digest")
        or receipt.get("actor_digest") != approval.get("actor_digest")
        or receipt.get("expires_at") != approval.get("expires_at")
        or authorized_at > now
        or expires_at <= now
        or receipt.get("human_actor_verified") is not True
        or receipt.get("vm_readback_verified") is not True
        or receipt.get("mutation_performed") is not False
        or not isinstance(digest, str)
        or digest != canonical_digest(document)
    ):
        raise ValueError("run command delegated authority receipt is invalid")


def _token_principal(token: str) -> str:
    parts = token.split(".")
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (IndexError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("run command executor token is invalid") from exc
    principal = payload.get("oid") if isinstance(payload, dict) else None
    if not isinstance(principal, str) or _GUID.fullmatch(principal) is None:
        raise ValueError("run command executor token principal is invalid")
    return principal


def _validate_approval(
    approval: dict[str, object],
    *,
    target_binding: str,
    target_digest: str,
    profile_digest: str,
    operation_id: str,
    bundle_receipt_digest: str,
    receiver_digest: str,
    now: datetime,
) -> None:
    expected = {
        "schema_version",
        "decision",
        "target_binding",
        "target_digest",
        "profile_digest",
        "operation_id",
        "bundle_receipt_digest",
        "receiver_digest",
        "actor_digest",
        "approved_at",
        "expires_at",
        "approval_digest",
    }
    digest = approval.get("approval_digest")
    document = {key: value for key, value in approval.items() if key != "approval_digest"}
    approved_at = _moment(approval.get("approved_at"), "approved_at")
    expires_at = _moment(approval.get("expires_at"), "expires_at")
    if (
        set(approval) != expected
        or approval.get("schema_version") != "fdai.run-command-private-relay-approval.v1"
        or approval.get("decision") != "approved"
        or approval.get("target_binding") != target_binding
        or approval.get("target_digest") != target_digest
        or approval.get("profile_digest") != profile_digest
        or approval.get("operation_id") != operation_id
        or approval.get("bundle_receipt_digest") != bundle_receipt_digest
        or approval.get("receiver_digest") != receiver_digest
        or _DIGEST.fullmatch(bundle_receipt_digest) is None
        or _DIGEST.fullmatch(receiver_digest) is None
        or not isinstance(approval.get("actor_digest"), str)
        or _DIGEST.fullmatch(str(approval["actor_digest"])) is None
        or approved_at > now
        or expires_at <= now
        or expires_at - approved_at > timedelta(hours=1)
        or not isinstance(digest, str)
        or digest != canonical_digest(document)
    ):
        raise ValueError("run command transport approval is invalid")


def require_approval_current(approval: dict[str, object], *, now: datetime | None = None) -> None:
    """Reject an approval that is not current at the immediate effect boundary."""

    moment = now or datetime.now(UTC)
    approved_at = _moment(approval.get("approved_at"), "approved_at")
    expires_at = _moment(approval.get("expires_at"), "expires_at")
    if approved_at > moment or expires_at <= moment:
        raise ValueError("run command transport approval is expired")


def _capture_json(
    capture: Callable[..., str], command: tuple[str, ...], label: str, *, timeout: int
) -> dict[str, object]:
    try:
        value = json.loads(capture(command, timeout=timeout))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} is invalid")
    return value


def _required_guid(value: dict[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or _GUID.fullmatch(item) is None:
        raise ValueError(f"run command {field} is invalid")
    return item


def _moment(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"run command approval {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"run command approval {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"run command approval {field} is invalid")
    return parsed.astimezone(UTC)


def _actor_digest(target_binding: str, login: str) -> str:
    return hashlib.sha256(f"{target_binding}:{login.casefold()}".encode()).hexdigest()
