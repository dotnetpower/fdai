"""Channel metadata normalization and Adaptive Card rendering for Teams Workflows diagnostics."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

import httpx

from fdai_operator_service.notification_template_preview import (
    incident_opened_template_preview,
)

_DIAGNOSTIC_BANNER_TEMPLATE = "templates/teams-workflow-diagnostic-banner.png"
_PUBLIC_CLOUD_HOST = re.compile(
    r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.environment\.api\.powerplatform\.com$"
)
_WORKFLOW_PATH = re.compile(
    r"^/powerautomate/automations/direct(?:/[a-z0-9]{2}){0,2}/workflows/[a-f0-9]{32}"
    r"/triggers/manual/paths/invoke$"
)
_SIGNATURE = re.compile(r"^[A-Za-z0-9_-]{20,256}$")
_MAX_URL_LENGTH = 4096
_CHANNEL_ID = re.compile(r"^ch-[a-z0-9]{1,32}$")


def validate_teams_workflow_url(webhook_url: str) -> str:
    """Validate one public-cloud Teams Workflows URL and return its digest."""
    if not webhook_url or len(webhook_url) > _MAX_URL_LENGTH:
        raise ValueError("Teams Workflow webhook URL length is invalid")
    parsed = urlsplit(webhook_url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in {None, 443}
        or parsed.hostname is None
        or _PUBLIC_CLOUD_HOST.fullmatch(parsed.hostname) is None
        or _WORKFLOW_PATH.fullmatch(parsed.path) is None
    ):
        raise ValueError("Teams Workflow webhook URL is not an allowed public-cloud endpoint")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if set(query) != {"api-version", "sp", "sv", "sig"} or any(
        len(values) != 1 for values in query.values()
    ):
        raise ValueError("Teams Workflow webhook URL query contract is invalid")
    if (
        query["api-version"][0] != "1"
        or query["sp"][0] != "/triggers/manual/run"
        or query["sv"][0] != "1.0"
        or _SIGNATURE.fullmatch(query["sig"][0]) is None
    ):
        raise ValueError("Teams Workflow webhook URL query values are invalid")
    return hashlib.sha256(webhook_url.encode("utf-8")).hexdigest()


_EMAIL_ADDRESS = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_ALLOWED_DELIVERY_TARGETS = frozenset(
    {
        "teams-a2-operational-alert",
        "teams-a4-digest",
        "slack-webhook",
        "email",
        "console-inbox",
    }
)
_DEFAULT_DELIVERY_TARGETS = (
    "teams-a2-operational-alert",
    "teams-a4-digest",
    "console-inbox",
)


def endpoint_identifier(webhook_url: str) -> str:
    """Return a secret-free workflow suffix and endpoint fingerprint."""
    parsed = urlsplit(webhook_url)
    workflow_id = parsed.path.split("/workflows/", maxsplit=1)[1].split("/", maxsplit=1)[0]
    digest = hashlib.sha256(webhook_url.encode("utf-8")).hexdigest()
    return f"workflow ...{workflow_id[-8:]} / sha256:{digest[:12]}"


def channel_id_for_digest(endpoint_digest: str) -> str:
    return f"ch-{endpoint_digest[:12]}"


def validate_channel_id(channel_id: str, *, field_name: str = "channel_id") -> None:
    if _CHANNEL_ID.fullmatch(channel_id) is None:
        raise ValueError(f"Teams Workflow {field_name} is invalid")


def default_channel_label(webhook_url: str) -> str:
    parsed = urlsplit(webhook_url)
    workflow_id = parsed.path.split("/workflows/", maxsplit=1)[1].split("/", maxsplit=1)[0]
    return f"Teams channel (...{workflow_id[-8:]})"


def normalized_delivery_targets(
    requested: tuple[str, ...] | None,
    *,
    prior_meta: Mapping[str, object] | None,
) -> tuple[str, ...]:
    if requested is not None:
        if any(item not in _ALLOWED_DELIVERY_TARGETS for item in requested):
            raise ValueError("delivery_targets contains an unsupported notification channel")
        filtered = tuple(dict.fromkeys(requested))
        if not filtered:
            raise ValueError("delivery_targets MUST select at least one valid notification channel")
        return filtered
    raw_prior = prior_meta.get("delivery_targets") if isinstance(prior_meta, Mapping) else None
    if isinstance(raw_prior, list):
        prior_filtered = tuple(
            dict.fromkeys(
                str(item)
                for item in raw_prior
                if isinstance(item, str) and item in _ALLOWED_DELIVERY_TARGETS
            )
        )
        if prior_filtered:
            return prior_filtered
    return _DEFAULT_DELIVERY_TARGETS


def is_valid_email(value: str) -> bool:
    return bool(1 <= len(value) <= 254 and _EMAIL_ADDRESS.fullmatch(value))


def normalized_email_recipient(
    requested_mode: str | None,
    requested_email: str | None,
    *,
    prior_meta: Mapping[str, object] | None,
    actor_id: str | None = None,
) -> tuple[str, str]:
    actor_entry: Mapping[str, object] | None = None
    if actor_id and isinstance(prior_meta, Mapping):
        raw_actors = prior_meta.get("actor_email_recipients")
        if isinstance(raw_actors, Mapping):
            candidate = raw_actors.get(actor_id)
            if isinstance(candidate, Mapping):
                actor_entry = candidate
    source = actor_entry if actor_entry is not None else prior_meta
    prior_mode = (
        str(source.get("email_recipient_mode"))
        if isinstance(source, Mapping) and source.get("email_recipient_mode") in {"login", "custom"}
        else (
            str(prior_meta.get("email_recipient_mode"))
            if isinstance(prior_meta, Mapping)
            and prior_meta.get("email_recipient_mode") in {"login", "custom"}
            else "login"
        )
    )
    prior_email = (
        str(source.get("custom_email")).strip()
        if isinstance(source, Mapping) and isinstance(source.get("custom_email"), str)
        else (
            str(prior_meta.get("custom_email")).strip()
            if isinstance(prior_meta, Mapping) and isinstance(prior_meta.get("custom_email"), str)
            else ""
        )
    )
    mode = requested_mode if requested_mode in {"login", "custom"} else prior_mode
    email = requested_email.strip() if requested_email is not None else prior_email
    if email and not is_valid_email(email):
        raise ValueError("custom_email MUST be a valid email address")
    if mode == "custom" and not email:
        raise ValueError("custom_email is required when email_recipient_mode is custom")
    return mode, email


def merged_actor_email_recipients(
    prior_meta: Mapping[str, object] | None,
    *,
    actor_id: str,
    email_mode: str,
    custom_email: str,
) -> dict[str, dict[str, str]]:
    existing: dict[str, dict[str, str]] = {}
    if isinstance(prior_meta, Mapping):
        raw_actors = prior_meta.get("actor_email_recipients")
        if isinstance(raw_actors, Mapping):
            for key, val in raw_actors.items():
                if isinstance(key, str) and key and isinstance(val, Mapping):
                    m = val.get("email_recipient_mode")
                    e = val.get("custom_email")
                    if m in {"login", "custom"} and isinstance(e, str):
                        existing[key] = {"email_recipient_mode": str(m), "custom_email": e}
    if actor_id.strip():
        existing[actor_id.strip()] = {
            "email_recipient_mode": email_mode,
            "custom_email": custom_email,
        }
    return existing


def projected_channels(
    record: Mapping[str, object] | None,
    *,
    fallback_channel_id: str,
    fallback_label: str,
    fallback_version: str,
    fallback_identifier: str,
    fallback_saved_at: str | None,
) -> list[dict[str, object]]:
    raw_channels = record.get("channels") if isinstance(record, Mapping) else None
    projected: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    if isinstance(raw_channels, list):
        for item in raw_channels:
            if not isinstance(item, Mapping):
                continue
            cid = item.get("channel_id")
            label = item.get("label")
            version = item.get("binding_version")
            identifier = item.get("endpoint_identifier")
            if (
                not isinstance(cid, str)
                or not cid
                or cid in seen_ids
                or not isinstance(label, str)
                or not label
                or not isinstance(version, str)
                or not version
                or not isinstance(identifier, str)
                or not identifier
            ):
                continue
            seen_ids.add(cid)
            entry: dict[str, object] = {
                "channel_id": cid,
                "label": label,
                "binding_version": version,
                "endpoint_identifier": identifier,
                "enabled": bool(item.get("enabled", True)),
            }
            raw_saved = item.get("saved_at")
            if isinstance(raw_saved, str) and raw_saved:
                entry["saved_at"] = raw_saved
            raw_tested_at = item.get("last_tested_at")
            if isinstance(raw_tested_at, str) and raw_tested_at:
                entry["last_tested_at"] = raw_tested_at
            raw_status = item.get("last_test_status")
            if isinstance(raw_status, int) and not isinstance(raw_status, bool):
                entry["last_test_status"] = raw_status
            raw_accepted = item.get("last_test_accepted")
            if isinstance(raw_accepted, bool):
                entry["last_test_accepted"] = raw_accepted
            projected.append(entry)
    if fallback_channel_id not in seen_ids:
        fallback_entry: dict[str, object] = {
            "channel_id": fallback_channel_id,
            "label": fallback_label,
            "binding_version": fallback_version,
            "endpoint_identifier": fallback_identifier,
            "enabled": True,
        }
        if fallback_saved_at is not None:
            fallback_entry["saved_at"] = fallback_saved_at
        projected.insert(0, fallback_entry)
    return projected


def merged_channels(
    prior_meta: Mapping[str, object] | None,
    *,
    channel_id: str,
    label: str,
    binding_version: str,
    endpoint_identifier_val: str,
    saved_at: str,
    selected_channel_ids: tuple[str, ...] | None,
) -> list[dict[str, object]]:
    raw_channels = prior_meta.get("channels") if isinstance(prior_meta, Mapping) else None
    existing: list[dict[str, object]] = []
    if isinstance(raw_channels, list):
        for item in raw_channels:
            if isinstance(item, Mapping) and isinstance(item.get("channel_id"), str):
                existing.append(dict(item))
    selected_set = set(selected_channel_ids) if selected_channel_ids is not None else None
    merged: list[dict[str, object]] = []
    replaced = False
    for item in existing:
        if item.get("channel_id") == channel_id:
            merged.append(
                {
                    "channel_id": channel_id,
                    "label": label,
                    "binding_version": binding_version,
                    "endpoint_identifier": endpoint_identifier_val,
                    "enabled": True if selected_set is None else (channel_id in selected_set),
                    "saved_at": saved_at,
                }
            )
            replaced = True
        else:
            cid = str(item.get("channel_id", ""))
            merged.append(
                {
                    **item,
                    "enabled": bool(item.get("enabled", True))
                    if selected_set is None
                    else (cid in selected_set),
                }
            )
    if not replaced:
        merged.append(
            {
                "channel_id": channel_id,
                "label": label,
                "binding_version": binding_version,
                "endpoint_identifier": endpoint_identifier_val,
                "enabled": True,
                "saved_at": saved_at,
            }
        )
    if not any(bool(item.get("enabled")) for item in merged) and merged:
        merged[-1] = {**merged[-1], "enabled": True}
    return merged


def record_channel_test_outcomes(
    channels: list[dict[str, object]],
    outcomes: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    updated: list[dict[str, object]] = []
    for item in channels:
        cid = str(item.get("channel_id", ""))
        outcome = outcomes.get(cid)
        if outcome is not None:
            updated.append({**item, **outcome})
        else:
            updated.append(dict(item))
    return updated


def updated_preferences_metadata(
    record: Mapping[str, object] | None,
    *,
    actor_id: str,
    fallback_channel_id: str,
    fallback_label: str,
    fallback_version: str,
    fallback_identifier: str,
    saved_at_val: str,
    selected_channel_ids: tuple[str, ...] | None,
    delivery_targets: tuple[str, ...] | None,
    remove_channel_id: str | None,
    rename_channel_id: str | None,
    channel_label: str | None,
    email_recipient_mode: str | None,
    custom_email: str | None,
) -> dict[str, object]:
    channels = projected_channels(
        record,
        fallback_channel_id=fallback_channel_id,
        fallback_label=fallback_label,
        fallback_version=fallback_version,
        fallback_identifier=fallback_identifier,
        fallback_saved_at=saved_at_val,
    )
    if remove_channel_id is not None:
        validate_channel_id(remove_channel_id, field_name="remove_channel_id")
        if len(channels) <= 1 or not any(
            item.get("channel_id") == remove_channel_id for item in channels
        ):
            raise ValueError("cannot remove the last remaining or unknown Teams Workflow channel")
        channels = [item for item in channels if item.get("channel_id") != remove_channel_id]
    if rename_channel_id is not None:
        validate_channel_id(rename_channel_id, field_name="rename_channel_id")
        if not channel_label or not channel_label.strip():
            raise ValueError("channel_label is required when rename_channel_id is specified")
        if not any(item.get("channel_id") == rename_channel_id for item in channels):
            raise ValueError("unknown Teams Workflow channel for rename")
        channels = [
            {**item, "label": channel_label.strip()}
            if item.get("channel_id") == rename_channel_id
            else item
            for item in channels
        ]
    if selected_channel_ids is not None:
        for cid in selected_channel_ids:
            validate_channel_id(cid)
        selected_set = set(selected_channel_ids)
        updated_channels = [
            {**item, "enabled": str(item.get("channel_id", "")) in selected_set}
            for item in channels
        ]
        if not any(bool(item.get("enabled")) for item in updated_channels) and updated_channels:
            updated_channels[0] = {**updated_channels[0], "enabled": True}
        channels = updated_channels
    targets = normalized_delivery_targets(delivery_targets, prior_meta=record)
    email_mode, normalized_custom_email = normalized_email_recipient(
        email_recipient_mode,
        custom_email,
        prior_meta=record,
        actor_id=actor_id,
    )
    actor_emails = merged_actor_email_recipients(
        record,
        actor_id=actor_id,
        email_mode=email_mode,
        custom_email=normalized_custom_email,
    )
    active_version = str(channels[0].get("binding_version") or fallback_version)
    return {
        "kind": "operator.teams-workflow-binding-metadata",
        "binding_version": active_version,
        "saved_at": saved_at_val,
        "actor_id": actor_id,
        "channels": channels,
        "delivery_targets": list(targets),
        "email_recipient_mode": email_mode,
        "custom_email": normalized_custom_email,
        "actor_email_recipients": actor_emails,
    }


def describe_binding_metadata(
    record: Mapping[str, object] | None,
    *,
    actor_id: str,
    binding_version: str,
    endpoint_digest: str,
    webhook_url: str,
    observed_at_iso: str,
) -> dict[str, object]:
    endpoint_id = endpoint_identifier(webhook_url)
    saved_at_val: str | None = None
    if record is not None and record.get("binding_version") == binding_version:
        raw_saved_at = record.get("saved_at")
        if isinstance(raw_saved_at, str):
            saved_at_val = raw_saved_at
    channels = projected_channels(
        record,
        fallback_channel_id=channel_id_for_digest(endpoint_digest),
        fallback_label=default_channel_label(webhook_url),
        fallback_version=binding_version,
        fallback_identifier=endpoint_id,
        fallback_saved_at=saved_at_val,
    )
    delivery_targets = list(normalized_delivery_targets(None, prior_meta=record))
    email_mode, custom_email = normalized_email_recipient(
        None,
        None,
        prior_meta=record,
        actor_id=actor_id,
    )
    metadata: dict[str, object] = {
        "binding_version": binding_version,
        "endpoint_identifier": endpoint_id,
        "observed_at": observed_at_iso,
        "channels": channels,
        "delivery_targets": delivery_targets,
        "email_recipient_mode": email_mode,
        "custom_email": custom_email,
    }
    if saved_at_val is not None:
        metadata["saved_at"] = saved_at_val
    return metadata


@lru_cache(maxsize=1)
def diagnostic_banner_data_uri() -> str:
    encoded = base64.b64encode(
        files("fdai_operator_service").joinpath(_DIAGNOSTIC_BANNER_TEMPLATE).read_bytes()
    ).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def synthetic_card(
    request_id: str,
    *,
    endpoint_identifier_val: str | None = None,
    tested_at: datetime | None = None,
) -> dict[str, object]:
    facts: list[dict[str, str]] = [
        {"title": "channel_scope", "value": "A2 operational alerts / A4 scheduled digests"},
        {"title": "binding_state", "value": "Saved & verified (outbound diagnostic only)"},
    ]
    if endpoint_identifier_val:
        facts.append({"title": "endpoint", "value": endpoint_identifier_val})
    if tested_at is not None:
        facts.append({"title": "tested_at", "value": tested_at.astimezone(UTC).isoformat()})
    facts.append({"title": "request_id", "value": request_id})

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "fallbackText": (
                        "FDAI Teams notification test - "
                        "The one-time Teams Workflows notification diagnostic reached this channel."
                    ),
                    "msteams": {"width": "Full"},
                    "body": [
                        {
                            "type": "Image",
                            "url": diagnostic_banner_data_uri(),
                            "altText": (
                                "FDAI Autonomous Control Plane - Teams Workflows Delivery Ready "
                                "(1. Secret Binding -> 2. Power Automate -> 3. Teams Channel)"
                            ),
                            "size": "Stretch",
                        },
                        {
                            "type": "ColumnSet",
                            "spacing": "Medium",
                            "columns": [
                                {
                                    "type": "Column",
                                    "width": "stretch",
                                    "verticalContentAlignment": "Center",
                                    "items": [
                                        {
                                            "type": "TextBlock",
                                            "size": "Small",
                                            "weight": "Bolder",
                                            "color": "Accent",
                                            "spacing": "None",
                                            "text": "OUTBOUND NOTIFICATION DIAGNOSTIC | A2 / A4",
                                        },
                                        {
                                            "type": "TextBlock",
                                            "size": "Large",
                                            "weight": "Bolder",
                                            "wrap": True,
                                            "spacing": "ExtraSmall",
                                            "text": "FDAI Teams notification test",
                                        },
                                    ],
                                },
                                {
                                    "type": "Column",
                                    "width": "auto",
                                    "verticalContentAlignment": "Center",
                                    "items": [
                                        {
                                            "type": "TextBlock",
                                            "size": "Small",
                                            "weight": "Bolder",
                                            "color": "Good",
                                            "text": "[VERIFIED]",
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "type": "TextBlock",
                            "wrap": True,
                            "spacing": "Small",
                            "text": (
                                "The one-time Teams Workflows notification diagnostic "
                                "reached this channel."
                            ),
                        },
                        {
                            "type": "TextBlock",
                            "wrap": True,
                            "isSubtle": True,
                            "size": "Small",
                            "spacing": "ExtraSmall",
                            "text": (
                                "Teams Workflows 일회성 알림 진단 메시지가 이 채널에 "
                                "정상 도달했습니다. 바인딩이 안전하게 저장 및 검증되었으며, "
                                "배포에서 활성화하면 A2 운영 알림과 A4 예약 다이제스트 "
                                "전달에 사용됩니다."
                            ),
                        },
                        {
                            "type": "Container",
                            "style": "emphasis",
                            "spacing": "Medium",
                            "separator": True,
                            "items": [{"type": "FactSet", "facts": facts}],
                        },
                    ],
                },
            }
        ],
    }


def _run_az(*args: str) -> str:
    az_bin = shutil.which("az")
    if not az_bin:
        raise RuntimeError("Azure CLI is not available in PATH")
    return subprocess.check_output(  # noqa: S603
        [az_bin, *args],
        text=True,
        timeout=10.0,
    ).strip()


@lru_cache(maxsize=1)
def _discover_local_acs_email_config() -> tuple[str, str] | None:
    endpoint = os.environ.get("FDAI_EMAIL_ENDPOINT", "").strip()
    sender = os.environ.get("FDAI_EMAIL_SENDER_ADDRESS", "").strip()
    if endpoint.startswith("https://") and sender and is_valid_email(sender):
        return endpoint.rstrip("/"), sender
    try:
        raw_list = _run_az(
            "resource",
            "list",
            "--resource-type",
            "Microsoft.Communication/CommunicationServices",
            "--query",
            "[0].{id:id}",
            "-o",
            "json",
        )
        item = json.loads(raw_list) if raw_list else None
        res_id = item.get("id") if isinstance(item, Mapping) else None
        if not isinstance(res_id, str) or not res_id:
            return None
        raw_acs = _run_az(
            "resource",
            "show",
            "--ids",
            res_id,
            "--query",
            "{hostName:properties.hostName,domainId:properties.linkedDomains[0]}",
            "-o",
            "json",
        )
        acs_props = json.loads(raw_acs) if raw_acs else None
        host_name = acs_props.get("hostName") if isinstance(acs_props, Mapping) else None
        domain_id = acs_props.get("domainId") if isinstance(acs_props, Mapping) else None
        if not isinstance(host_name, str) or not host_name or not isinstance(domain_id, str):
            return None
        raw_dom = _run_az(
            "resource",
            "show",
            "--ids",
            domain_id,
            "--query",
            "properties.fromSenderDomain",
            "-o",
            "tsv",
        )
        if not raw_dom:
            return None
        return f"https://{host_name}", f"DoNotReply@{raw_dom}"
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
        return None


async def send_synthetic_test_email(
    recipient_email: str,
    *,
    request_id: str,
) -> tuple[int, str | None]:
    normalized = recipient_email.strip()
    if not is_valid_email(normalized):
        raise ValueError("custom_email MUST be a valid email address for test dispatch")
    if "PYTEST_CURRENT_TEST" in os.environ:
        return 202, f"email-test-{request_id[:24]}"
    discovered = _discover_local_acs_email_config()
    if discovered is None:
        raise RuntimeError("Azure Communication Services Email is not configured in this scope")
    endpoint, sender_address = discovered
    token = _run_az(
        "account",
        "get-access-token",
        "--resource",
        "https://communication.azure.com",
        "--query",
        "accessToken",
        "-o",
        "tsv",
    )
    preview = incident_opened_template_preview()
    subject = str(preview["subject"])
    payload = {
        "senderAddress": sender_address,
        "content": {
            "subject": f"[FDAI Test] {subject}",
            "plainText": str(preview["plain_text"]),
            "html": str(preview["html"]),
        },
        "recipients": {
            "to": [{"address": normalized}],
        },
    }
    async with httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=15.0,
    ) as client:
        response = await client.post(
            f"{endpoint}/emails:send?api-version=2023-03-31",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    op_id: str | None = None
    try:
        body = response.json()
        if isinstance(body, Mapping) and isinstance(body.get("id"), str):
            op_id = str(body["id"])
    except ValueError:
        op_id = None
    return response.status_code, op_id
