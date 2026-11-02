"""Microsoft Entra ID operator session and workstation account discovery for Release Hub."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_PRINCIPAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._%+@:-]{1,118}\Z", re.ASCII)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z",
    re.ASCII,
)


@dataclass(frozen=True, slots=True)
class EntraAccountCandidate:
    """Non-secret Microsoft Entra ID account metadata discovered on the operator workstation."""

    principal: str
    tenant_id: str
    tenant_label: str
    is_default: bool


@dataclass(frozen=True, slots=True)
class ActiveEntraSession:
    """Active Microsoft Entra ID operator session bound to the Release Hub instance."""

    principal: str
    display_name: str
    tenant_id: str
    auth_method: Literal["entra-workstation", "entra-msal-pkce", "entra-remote-jwt"]
    signed_in_at: str

    @property
    def actor_id(self) -> str:
        raw = f"entra:{self.principal}"
        return raw[:160]


class EntraLoginRequest(BaseModel):
    """Request payload to establish an operator Microsoft Entra ID session."""

    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["workstation", "msal_account"] = "workstation"
    principal: str = Field(default="", max_length=120)
    display_name: str = Field(default="", max_length=120)
    tenant_id: str = Field(default="", max_length=64)
    client_id: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def _validate_fields(self) -> EntraLoginRequest:
        cleaned_principal = self.principal.strip()
        if cleaned_principal and _PRINCIPAL_RE.fullmatch(cleaned_principal) is None:
            raise ValueError("Entra principal must be a valid UPN, email, or object identifier.")
        cleaned_tenant = self.tenant_id.strip().lower()
        if cleaned_tenant and _UUID_RE.fullmatch(cleaned_tenant) is None:
            raise ValueError("Entra tenant_id must be a canonical UUID.")
        return self


def detect_workstation_entra_accounts(
    profile_path: Path | None = None,
) -> list[EntraAccountCandidate]:
    """Read non-secret account & tenant identifiers from ~/.azure/azureProfile.json."""

    target = profile_path or (Path.home() / ".azure" / "azureProfile.json")
    try:
        if not target.is_file():
            return []
        raw = target.read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            return []
        doc = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(doc, dict):
            return []
        subs = doc.get("subscriptions")
        if not isinstance(subs, list):
            return []
        seen: dict[tuple[str, str], EntraAccountCandidate] = {}
        for sub in subs:
            if not isinstance(sub, dict):
                continue
            user = sub.get("user")
            if not isinstance(user, dict):
                continue
            name = str(user.get("name", "")).strip()
            tenant_id = str(sub.get("tenantId", "")).strip().lower()
            if (
                not name
                or _PRINCIPAL_RE.fullmatch(name) is None
                or _UUID_RE.fullmatch(tenant_id) is None
            ):
                continue
            tenant_label = str(
                sub.get("tenantDisplayName") or sub.get("name") or "Microsoft Entra Tenant"
            ).strip()[:80]
            is_def = bool(sub.get("isDefault"))
            key = (name.lower(), tenant_id)
            existing = seen.get(key)
            if existing is None or (is_def and not existing.is_default):
                seen[key] = EntraAccountCandidate(
                    principal=name,
                    tenant_id=tenant_id,
                    tenant_label=tenant_label,
                    is_default=is_def,
                )
        return sorted(
            seen.values(),
            key=lambda item: (not item.is_default, item.principal.lower()),
        )
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return []


class EntraSessionManager:
    """Thread-safe Microsoft Entra ID session store for Release Hub operator attribution."""

    def __init__(self, *, profile_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._session: ActiveEntraSession | None = None
        self._profile_path = profile_path

    @property
    def current_actor(self) -> str:
        with self._lock:
            return self._session.actor_id if self._session is not None else "local-operator"

    def status_payload(self, *, remote_principal: str | None = None) -> dict[str, Any]:
        candidates = detect_workstation_entra_accounts(self._profile_path)
        with self._lock:
            active = self._session
        if remote_principal:
            active = ActiveEntraSession(
                principal=remote_principal,
                display_name=remote_principal,
                tenant_id="remote-entra-tenant",
                auth_method="entra-remote-jwt",
                signed_in_at=datetime.now(UTC).isoformat(),
            )
        return {
            "authenticated": active is not None,
            "actor": active.actor_id if active is not None else "local-operator",
            "session": (
                {
                    "principal": active.principal,
                    "display_name": active.display_name,
                    "tenant_id": active.tenant_id,
                    "auth_method": active.auth_method,
                    "signed_in_at": active.signed_in_at,
                }
                if active is not None
                else None
            ),
            "detected_accounts": [
                {
                    "principal": c.principal,
                    "tenant_id": c.tenant_id,
                    "tenant_label": c.tenant_label,
                    "is_default": c.is_default,
                }
                for c in candidates
            ],
        }

    def sign_in(self, request: EntraLoginRequest) -> dict[str, Any]:
        candidates = detect_workstation_entra_accounts(self._profile_path)
        now = datetime.now(UTC).isoformat()
        principal = request.principal.strip()
        tenant_id = request.tenant_id.strip().lower()
        display_name = request.display_name.strip()

        if request.mode == "workstation":
            matched = None
            if principal:
                matched = next(
                    (c for c in candidates if c.principal.lower() == principal.lower()),
                    None,
                )
            elif candidates:
                matched = candidates[0]

            if matched is not None:
                principal = matched.principal
                tenant_id = matched.tenant_id
                display_name = display_name or f"{matched.principal} ({matched.tenant_label})"
            elif not principal:
                raise ValueError(
                    "No workstation Entra ID account detected. Provide UPN and Tenant ID."
                )
            else:
                tenant_id = tenant_id or "00000000-0000-0000-0000-000000000000"
                display_name = display_name or principal
            method: Literal["entra-workstation", "entra-msal-pkce"] = "entra-workstation"
        else:
            if not principal or not tenant_id:
                raise ValueError("MSAL sign-in requires both principal and tenant_id.")
            display_name = display_name or principal
            method = "entra-msal-pkce"

        session = ActiveEntraSession(
            principal=principal,
            display_name=display_name,
            tenant_id=tenant_id,
            auth_method=method,
            signed_in_at=now,
        )
        with self._lock:
            self._session = session
        return self.status_payload()

    def sign_out(self) -> dict[str, Any]:
        with self._lock:
            self._session = None
        return self.status_payload()
