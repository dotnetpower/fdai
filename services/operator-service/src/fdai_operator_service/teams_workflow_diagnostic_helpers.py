"""Channel metadata normalization and Adaptive Card rendering for Teams Workflows diagnostics."""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from urllib.parse import urlsplit

_DIAGNOSTIC_BANNER_TEMPLATE = "templates/teams-workflow-diagnostic-banner.png"
_CHANNEL_ID = re.compile(r"^ch-[a-z0-9]{1,32}$")
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
) -> tuple[str, str]:
    prior_mode = (
        str(prior_meta.get("email_recipient_mode"))
        if isinstance(prior_meta, Mapping)
        and prior_meta.get("email_recipient_mode") in {"login", "custom"}
        else "login"
    )
    prior_email = (
        str(prior_meta.get("custom_email")).strip()
        if isinstance(prior_meta, Mapping) and isinstance(prior_meta.get("custom_email"), str)
        else ""
    )
    mode = requested_mode if requested_mode in {"login", "custom"} else prior_mode
    email = requested_email.strip() if requested_email is not None else prior_email
    if email and not is_valid_email(email):
        raise ValueError("custom_email MUST be a valid email address")
    if mode == "custom" and not email:
        raise ValueError("custom_email is required when email_recipient_mode is custom")
    return mode, email


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
