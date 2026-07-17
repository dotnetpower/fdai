"""Time-boxed, fail-closed break-glass console tool."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.conversation._write_audit import AuditWriter
from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import SideEffectClass, ToolResult
from fdai.shared.providers.break_glass_pager import BreakGlassPager, BreakGlassPagerError

_SECRET_PATTERNS: tuple[str, ...] = (
    "AccountKey=",
    "SharedAccessKey=",
    "AKIA",
    "-----BEGIN",
    "ghp_",
    "xox",
)


def _redact_secrets(text: str) -> str:
    """Replace any line containing a known secret marker."""
    if not text:
        return text
    return "\n".join(
        "[REDACTED-SUSPECTED-SECRET]"
        if any(pattern in line for pattern in _SECRET_PATTERNS)
        else line
        for line in text.splitlines()
    )


class ActivateBreakGlassTool:
    """Request explicit, session-scoped BreakGlass elevation."""

    name = "activate_break_glass"
    description = (
        "Request session-scoped BreakGlass elevation. Time-boxed (<=4h), "
        "explicit reason required, fail-closed on pager delivery. Always "
        "audited whether granted or refused."
    )
    rbac_floor: Role = Role.READER
    side_effect_class: SideEffectClass = "breakglass"
    _DEFAULT_MAX_TTL_SECONDS: int = 14400
    _DEFAULT_MIN_REASON_LENGTH: int = 20

    def __init__(
        self,
        *,
        pager: BreakGlassPager,
        audit_writer: AuditWriter,
        max_ttl_seconds: int = _DEFAULT_MAX_TTL_SECONDS,
        min_reason_length: int = _DEFAULT_MIN_REASON_LENGTH,
        clock: Any = None,
    ) -> None:
        if max_ttl_seconds > self._DEFAULT_MAX_TTL_SECONDS:
            raise ValueError(
                "max_ttl_seconds MUST NOT exceed the shipped ceiling "
                f"{self._DEFAULT_MAX_TTL_SECONDS} (chat invariant 7); "
                f"got {max_ttl_seconds}"
            )
        if max_ttl_seconds < 60:
            raise ValueError("max_ttl_seconds MUST be at least 60")
        if min_reason_length < 1:
            raise ValueError("min_reason_length MUST be at least 1")
        self._pager = pager
        self._audit_writer = audit_writer
        self._max_ttl_seconds = max_ttl_seconds
        self._min_reason_length = min_reason_length
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        import asyncio

        raw_reason = str(arguments.get("reason", ""))
        raw_expiry = arguments.get("expiry_seconds", self._max_ttl_seconds)
        reason_redacted = _redact_secrets(raw_reason).strip()
        if len(reason_redacted) < self._min_reason_length:
            return self._refuse(
                principal=principal,
                reason_redacted=reason_redacted,
                refusal_kind="short_reason",
                preview=(
                    f"activate_break_glass: reason MUST be >= "
                    f"{self._min_reason_length} chars after redaction"
                ),
            )
        try:
            expiry_seconds = int(raw_expiry)
        except (TypeError, ValueError):
            return self._refuse(
                principal=principal,
                reason_redacted=reason_redacted,
                refusal_kind="invalid_expiry",
                preview="activate_break_glass 'expiry_seconds' MUST be an integer",
            )
        if expiry_seconds < 60:
            return self._refuse(
                principal=principal,
                reason_redacted=reason_redacted,
                refusal_kind="expiry_below_minimum",
                preview="activate_break_glass 'expiry_seconds' MUST be >= 60",
            )
        if expiry_seconds > self._max_ttl_seconds:
            return self._refuse(
                principal=principal,
                reason_redacted=reason_redacted,
                refusal_kind="expiry_above_ceiling",
                preview=(
                    "activate_break_glass 'expiry_seconds' exceeds the shipped "
                    f"ceiling {self._max_ttl_seconds}"
                ),
            )
        activated_at = self._clock()
        expires_at = activated_at + timedelta(seconds=expiry_seconds)
        try:
            pager_receipt = asyncio.run(
                self._pager.notify_owners(
                    actor_oid=principal.id,
                    actor_display=principal.display_name or principal.id,
                    reason_redacted=reason_redacted,
                    activated_at=activated_at,
                    expires_at=expires_at,
                )
            )
        except BreakGlassPagerError as exc:
            audit_id = self._audit_writer.write_break_glass_entry(
                principal=principal,
                outcome="error",
                reason_redacted=reason_redacted,
                activated_at=activated_at,
                expires_at=expires_at,
                pager_receipt="",
                refusal_kind=f"pager_{exc.kind}",
            )
            return ToolResult(
                status="error",
                data={"audit_id": audit_id, "refusal_kind": f"pager_{exc.kind}"},
                preview=f"activate_break_glass refused: pager delivery failed ({exc.kind})",
                evidence_refs=(f"audit:{audit_id}",),
            )
        audit_id = self._audit_writer.write_break_glass_entry(
            principal=principal,
            outcome="ok",
            reason_redacted=reason_redacted,
            activated_at=activated_at,
            expires_at=expires_at,
            pager_receipt=pager_receipt,
            refusal_kind=None,
        )
        return ToolResult(
            status="ok",
            data={
                "audit_id": audit_id,
                "activated_at": activated_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "pager_receipt": pager_receipt,
                "reason_redacted": reason_redacted,
            },
            preview=(
                f"activate_break_glass: granted (expires {expires_at.isoformat()}); "
                f"pager={pager_receipt}"
            ),
            evidence_refs=(f"audit:{audit_id}", f"pager:{pager_receipt}"),
        )

    def _refuse(
        self,
        *,
        principal: Principal,
        reason_redacted: str,
        refusal_kind: str,
        preview: str,
    ) -> ToolResult:
        audit_id = self._audit_writer.write_break_glass_entry(
            principal=principal,
            outcome="error",
            reason_redacted=reason_redacted,
            activated_at=None,
            expires_at=None,
            pager_receipt="",
            refusal_kind=refusal_kind,
        )
        return ToolResult(
            status="error",
            data={"audit_id": audit_id, "refusal_kind": refusal_kind},
            preview=preview,
            evidence_refs=(f"audit:{audit_id}",),
        )
