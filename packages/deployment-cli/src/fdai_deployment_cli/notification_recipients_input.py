"""Private operator-selected email recipients for the source AKS notifications add-on.

Addresses are personal data, so they are accepted only from a private local file and travel to
the managed host as one private staged file. They never enter the runtime profile, its digest,
plan reviews, receipts or logs; only the digest of the canonical recipient list is retained in the
managed host's private context so a later run can detect drift.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.private_output import read_private_bytes
from fdai_deployment_cli.standalone_host_state import replace_or_verify_private_json

_STAGED_SCHEMA = "fdai.notification-recipients-staged-input.v1"
_MAX_INPUT_BYTES = 16 * 1024
_MAX_RECIPIENTS = 20
_MAX_ADDRESS_LENGTH = 254
# Mirrors the `notification_email_recipients` validation in `infra/variables.tf`.
_ADDRESS = re.compile(r"[^@\s]+@[^@\s]+[.][^@\s]+")
_PLACEHOLDER_DOMAINS = frozenset({"example.com", "example.org", "example.net", "invalid", "test"})
_CONTEXT_KEY = "notification_recipients_digest"


@dataclass(frozen=True, slots=True)
class NotificationRecipientsDeploymentInput:
    """Validated, deduplicated recipient list and its content digest."""

    recipients: tuple[str, ...]
    input_digest: str

    def __repr__(self) -> str:
        return f"NotificationRecipientsDeploymentInput(count={len(self.recipients)})"


def load_notification_recipients(path: Path) -> NotificationRecipientsDeploymentInput:
    """Load one private recipients file from the operator-selected path."""

    return _from_mapping(_load_json_object(path, "notification recipients input"), staged=False)


def staged_notification_recipients_from_path(
    path: Path | None,
) -> NotificationRecipientsDeploymentInput | None:
    """Load a staged managed-host input, or report that none was supplied."""

    if path is None:
        return None
    return _from_mapping(
        _load_json_object(path, "staged notification recipients input"), staged=True
    )


def stage_notification_recipients(
    value: NotificationRecipientsDeploymentInput | None,
    *,
    tunnel: Any,
    prepared_root: Path,
    remote_root: str,
) -> tuple[str, ...]:
    """Copy the private recipient list to the managed host and return CLI arguments."""

    if value is None:
        return ()
    local_path = prepared_root / "notification-recipients-input.json"
    remote_path = f"{remote_root}/notification-recipients-input.json"
    replace_or_verify_private_json(
        local_path,
        {
            "schema_version": _STAGED_SCHEMA,
            "input_digest": value.input_digest,
            "recipients": list(value.recipients),
        },
    )
    tunnel.copy_to(local_path, remote_path, timeout=120)
    return ("--notification-recipients", remote_path)


def apply_notification_recipients(
    values: dict[str, object],
    value: NotificationRecipientsDeploymentInput | None,
) -> None:
    """Populate the Terraform recipients only when the input is supplied."""

    if value is None:
        return
    values["notification_email_recipients"] = list(value.recipients)


def require_recipients_for_notifications(
    *, notifications_selected: bool, value: NotificationRecipientsDeploymentInput | None
) -> None:
    """Fail closed before any Azure effect when the add-on and its input disagree."""

    if notifications_selected and value is None:
        raise ValueError(
            "the notifications add-on requires --notification-recipients with at least one address"
        )
    if value is not None and not notifications_selected:
        raise ValueError("--notification-recipients requires the notifications add-on")


def reconcile_retained_notification_recipients(
    value: NotificationRecipientsDeploymentInput | None,
    *,
    retained: dict[str, object],
    values: dict[str, object],
) -> bool:
    """Bind a recipient list onto a retained host context, or fail on drift."""

    previous = retained.get(_CONTEXT_KEY, "")
    if not isinstance(previous, str):
        raise ValueError("standalone host retained context differs")
    current = value.input_digest if value is not None else ""
    if previous and previous != current:
        raise ValueError("standalone host retained context differs")
    if value is None:
        return False
    apply_notification_recipients(values, value)
    if previous == current:
        return False
    retained[_CONTEXT_KEY] = current
    return True


def context_digest(value: NotificationRecipientsDeploymentInput | None) -> str:
    """Return the digest retained in the private managed-host context."""

    return value.input_digest if value is not None else ""


def _from_mapping(value: dict[str, Any], *, staged: bool) -> NotificationRecipientsDeploymentInput:
    expected = {"schema_version", "input_digest", "recipients"} if staged else {"recipients"}
    if set(value) != expected:
        raise ValueError("notification recipients input fields are invalid")
    recipients = _recipients(value["recipients"])
    digest = canonical_digest({"notification_email_recipients": list(recipients)})
    if staged:
        if value["schema_version"] != _STAGED_SCHEMA:
            raise ValueError("staged notification recipients input schema is unsupported")
        if value["input_digest"] != digest:
            raise ValueError("staged notification recipients input digest differs")
    return NotificationRecipientsDeploymentInput(recipients=recipients, input_digest=digest)


def _recipients(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("notification recipients MUST be a non-empty list")
    seen: dict[str, str] = {}
    for item in value:
        if not isinstance(item, str):
            raise ValueError("notification recipients MUST be strings")
        address = item.strip()
        if not address or len(address) > _MAX_ADDRESS_LENGTH or _ADDRESS.fullmatch(address) is None:
            raise ValueError("a notification recipient address is invalid")
        if address.rsplit("@", 1)[1].casefold() in _PLACEHOLDER_DOMAINS:
            raise ValueError("a notification recipient address uses a placeholder domain")
        seen.setdefault(address.casefold(), address)
    if len(seen) > _MAX_RECIPIENTS:
        raise ValueError(f"notification recipients exceed the limit of {_MAX_RECIPIENTS}")
    return tuple(seen[key] for key in sorted(seen))


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    data = read_private_bytes(path, max_bytes=_MAX_INPUT_BYTES)
    if not data:
        raise ValueError(f"{label} is empty")
    try:
        value = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} MUST be a JSON object")  # noqa: TRY004
    return value


__all__ = [
    "NotificationRecipientsDeploymentInput",
    "apply_notification_recipients",
    "context_digest",
    "load_notification_recipients",
    "reconcile_retained_notification_recipients",
    "require_recipients_for_notifications",
    "stage_notification_recipients",
    "staged_notification_recipients_from_path",
]
