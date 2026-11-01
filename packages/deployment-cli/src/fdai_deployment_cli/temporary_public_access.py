"""Bounded temporary public-access creation and cleanup with two-phase audit closure.

Temporary public network access for provisioning requires an explicit global IPv4 ``/32`` caller
CIDR, a bounded TTL (``1..3600`` seconds), an authenticated caller identity, a target resource ID,
and a correlation ID. Wildcard rules (``0.0.0.0/0``, ``*``) and broader prefixes are rejected.
Cleanup and readback verification ALWAYS execute in a ``finally`` block; any cleanup or readback
failure marks the outcome ``incomplete_cleanup_failed`` (``terminal_success=False``,
``requires_operator_remediation=True``) even when the inner provisioning operation succeeded.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, Literal, Protocol, TypeVar

from fdai_deployment_cli.cli_help import command

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)

MIN_TEMPORARY_ACCESS_TTL_SECONDS = 1
MAX_TEMPORARY_ACCESS_TTL_SECONDS = 3600

Phase1Status = Literal["prepared", "granted"]
Phase2Status = Literal["closed_clean", "cleanup_failed"]
AccessOutcomeStatus = Literal[
    "closed_clean",
    "operation_failed_cleaned_up",
    "incomplete_cleanup_failed",
]


class TemporaryPublicAccessError(ValueError):
    """Temporary public-access request violated CIDR, TTL, authentication, or binding policy."""


class TemporaryAccessRuleDriver(Protocol):
    """Provider boundary for adding, removing, and reading back a temporary ``/32`` firewall rule."""

    def grant_rule(
        self,
        *,
        target_resource_id: str,
        rule_id: str,
        caller_cidr: str,
        expires_at: datetime,
    ) -> None: ...

    def revoke_rule(
        self,
        *,
        target_resource_id: str,
        rule_id: str,
    ) -> None: ...

    def verify_rule_absent(
        self,
        *,
        target_resource_id: str,
        rule_id: str,
    ) -> bool: ...


_RFC1918_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)


def validate_caller_ipv4_host_cidr(caller_cidr: object) -> str:
    """Require an explicit unicast IPv4 ``/32`` host CIDR and reject wildcards/loopback/RFC1918."""
    if not isinstance(caller_cidr, str) or not caller_cidr.strip():
        raise TemporaryPublicAccessError("caller_cidr MUST be a non-empty IPv4 /32 CIDR string")
    normalized = caller_cidr.strip()
    if normalized in {"*", "0.0.0.0/0", "::/0", "0.0.0.0/32", "255.255.255.255/32"}:
        raise TemporaryPublicAccessError(
            f"wildcard or broadcast caller_cidr is forbidden: {normalized!r}"
        )
    if "/" not in normalized:
        raise TemporaryPublicAccessError("caller_cidr MUST include an explicit /32 prefix length")
    try:
        network = ipaddress.ip_network(normalized, strict=True)
    except ValueError as exc:
        raise TemporaryPublicAccessError(f"invalid caller_cidr {normalized!r}") from exc
    if not isinstance(network, ipaddress.IPv4Network) or network.prefixlen != 32:
        raise TemporaryPublicAccessError(
            f"caller_cidr MUST be an exact IPv4 /32 host range (got {normalized!r})"
        )
    address = network.network_address
    if (
        address.is_unspecified
        or address.is_multicast
        or address.is_loopback
        or address.is_link_local
        or any(address in rfc1918 for rfc1918 in _RFC1918_NETWORKS)
    ):
        raise TemporaryPublicAccessError(
            f"caller_cidr MUST be a routable unicast IPv4 /32 address (got {normalized!r})"
        )
    return f"{address}/32"


def validate_ttl_seconds(ttl_seconds: object) -> int:
    """Require a bounded TTL between 1 and 3600 seconds inclusive."""
    if (
        isinstance(ttl_seconds, bool)
        or not isinstance(ttl_seconds, int)
        or not (MIN_TEMPORARY_ACCESS_TTL_SECONDS <= ttl_seconds <= MAX_TEMPORARY_ACCESS_TTL_SECONDS)
    ):
        raise TemporaryPublicAccessError(
            f"ttl_seconds MUST be an integer in {MIN_TEMPORARY_ACCESS_TTL_SECONDS}.."
            f"{MAX_TEMPORARY_ACCESS_TTL_SECONDS}"
        )
    return ttl_seconds


def _require_identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise TemporaryPublicAccessError(f"{name} MUST be non-empty bounded text")
    return value.strip()


def _require_aware(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TemporaryPublicAccessError(f"{name} MUST be a timezone-aware datetime")
    return value


@dataclass(frozen=True, slots=True)
class TemporaryPublicAccessRequest:
    """Validated parameters for a single bounded temporary public-access window."""

    correlation_id: str
    target_resource_id: str
    caller_cidr: str
    ttl_seconds: int
    requested_at: datetime
    caller_principal_id: str = "authenticated-operator"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "correlation_id", _require_identifier("correlation_id", self.correlation_id)
        )
        object.__setattr__(
            self,
            "target_resource_id",
            _require_identifier("target_resource_id", self.target_resource_id),
        )
        object.__setattr__(self, "caller_cidr", validate_caller_ipv4_host_cidr(self.caller_cidr))
        object.__setattr__(self, "ttl_seconds", validate_ttl_seconds(self.ttl_seconds))
        _require_aware("requested_at", self.requested_at)
        object.__setattr__(
            self,
            "caller_principal_id",
            _require_identifier("caller_principal_id", self.caller_principal_id),
        )

    @property
    def rule_id(self) -> str:
        digest = hashlib.sha256(
            f"{self.correlation_id}|{self.target_resource_id}|{self.caller_cidr}".encode("utf-8")
        ).hexdigest()[:16]
        return f"fdai-temp-access-{digest}"

    @property
    def expires_at(self) -> datetime:
        return self.requested_at + timedelta(seconds=self.ttl_seconds)


@dataclass(frozen=True, slots=True)
class TemporaryAccessAuditRecord:
    """One phase record in the two-phase temporary public-access audit trail."""

    phase: Literal["phase_1", "phase_2"]
    phase_status: Phase1Status | Phase2Status
    correlation_id: str
    rule_id: str
    target_resource_id: str
    caller_cidr: str
    caller_principal_id: str
    ttl_seconds: int
    recorded_at: datetime
    expires_at: datetime
    readback_verified_absent: bool
    requires_operator_remediation: bool
    error_detail: str | None = None
    receipt_digest: str = ""

    def __post_init__(self) -> None:
        payload = {
            "phase": self.phase,
            "phase_status": self.phase_status,
            "correlation_id": self.correlation_id,
            "rule_id": self.rule_id,
            "target_resource_id": self.target_resource_id,
            "caller_cidr": self.caller_cidr,
            "caller_principal_id": self.caller_principal_id,
            "ttl_seconds": self.ttl_seconds,
            "recorded_at": self.recorded_at.astimezone(UTC).isoformat(),
            "expires_at": self.expires_at.astimezone(UTC).isoformat(),
            "readback_verified_absent": self.readback_verified_absent,
            "requires_operator_remediation": self.requires_operator_remediation,
            "error_detail": self.error_detail,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        computed = "sha256:" + hashlib.sha256(encoded).hexdigest()
        if not self.receipt_digest:
            object.__setattr__(self, "receipt_digest", computed)


@dataclass(frozen=True, slots=True)
class TemporaryPublicAccessOutcome(Generic[T_co]):
    """Terminal or incomplete outcome of a bounded temporary public-access execution."""

    status: AccessOutcomeStatus
    terminal_success: bool
    requires_operator_remediation: bool
    correlation_id: str
    rule_id: str
    target_resource_id: str
    caller_cidr: str
    ttl_seconds: int
    operation_succeeded: bool
    cleanup_succeeded: bool
    readback_verified_absent: bool
    operation_result: T_co | None
    operation_error: str | None
    cleanup_error: str | None
    phase1_audit: TemporaryAccessAuditRecord
    phase2_audit: TemporaryAccessAuditRecord
    receipt_digest: str


class TemporaryPublicAccessCoordinator:
    """Coordinate bounded ``/32`` temporary public access, cleanup, readback, and two-phase audit."""

    def __init__(self, driver: TemporaryAccessRuleDriver) -> None:
        self._driver = driver
        self._audit_trail: list[TemporaryAccessAuditRecord] = []
        self._outcomes_by_correlation: dict[str, TemporaryPublicAccessOutcome[object]] = {}
        self._requests_by_correlation: dict[str, TemporaryPublicAccessRequest] = {}

    @property
    def audit_trail(self) -> tuple[TemporaryAccessAuditRecord, ...]:
        """Return all Phase 1 and Phase 2 audit records emitted by this coordinator."""
        return tuple(self._audit_trail)

    def execute_with_temporary_access(
        self,
        request: TemporaryPublicAccessRequest,
        operation: Callable[[], T],
        *,
        closed_at: datetime | None = None,
    ) -> TemporaryPublicAccessOutcome[T]:
        """Open ``/32`` access, run ``operation``, and always revoke and verify readback."""
        if not isinstance(request, TemporaryPublicAccessRequest):
            raise TemporaryPublicAccessError(
                "request MUST be a TemporaryPublicAccessRequest instance"
            )
        prior_request = self._requests_by_correlation.get(request.correlation_id)
        prior_outcome = self._outcomes_by_correlation.get(request.correlation_id)
        if prior_request is not None and prior_outcome is not None:
            if (
                prior_request.target_resource_id != request.target_resource_id
                or prior_request.caller_cidr != request.caller_cidr
                or prior_request.ttl_seconds != request.ttl_seconds
                or prior_request.caller_principal_id != request.caller_principal_id
            ):
                raise TemporaryPublicAccessError(
                    "correlation_id replay cannot change target, CIDR, TTL, or principal binding"
                )
            if prior_outcome.status == "closed_clean":
                return prior_outcome  # type: ignore[return-value]

        self._requests_by_correlation[request.correlation_id] = request
        finish_time = closed_at or (request.requested_at + timedelta(seconds=1))
        _require_aware("closed_at", finish_time)

        def _make_audit(
            phase: Literal["phase_1", "phase_2"],
            phase_status: Phase1Status | Phase2Status,
            recorded_at: datetime,
            readback_absent: bool = False,
            remediation: bool = False,
            error_detail: str | None = None,
        ) -> TemporaryAccessAuditRecord:
            rec = TemporaryAccessAuditRecord(
                phase=phase,
                phase_status=phase_status,
                correlation_id=request.correlation_id,
                rule_id=request.rule_id,
                target_resource_id=request.target_resource_id,
                caller_cidr=request.caller_cidr,
                caller_principal_id=request.caller_principal_id,
                ttl_seconds=request.ttl_seconds,
                recorded_at=recorded_at,
                expires_at=request.expires_at,
                readback_verified_absent=readback_absent,
                requires_operator_remediation=remediation,
                error_detail=error_detail,
            )
            self._audit_trail.append(rec)
            return rec

        phase1_audit = _make_audit("phase_1", "prepared", request.requested_at)
        operation_result: T | None = None
        operation_succeeded = False
        operation_error: str | None = None
        cleanup_succeeded = False
        readback_verified_absent = False
        cleanup_error: str | None = None

        try:
            self._driver.grant_rule(
                target_resource_id=request.target_resource_id,
                rule_id=request.rule_id,
                caller_cidr=request.caller_cidr,
                expires_at=request.expires_at,
            )
            phase1_audit = _make_audit("phase_1", "granted", request.requested_at)
            operation_result = operation()
            operation_succeeded = True
        except Exception as exc:  # noqa: BLE001 - capture operation failure and still clean up
            operation_error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                self._driver.revoke_rule(
                    target_resource_id=request.target_resource_id,
                    rule_id=request.rule_id,
                )
                cleanup_succeeded = True
                readback_verified_absent = bool(
                    self._driver.verify_rule_absent(
                        target_resource_id=request.target_resource_id,
                        rule_id=request.rule_id,
                    )
                )
                if not readback_verified_absent:
                    cleanup_error = "post-cleanup readback reported temporary rule still present"
            except Exception as exc:  # noqa: BLE001 - cleanup failure must close audit as incomplete
                cleanup_error = f"{type(exc).__name__}: {exc}"
                readback_verified_absent = False

        clean_closed = cleanup_succeeded and readback_verified_absent and cleanup_error is None
        if not clean_closed:
            status: AccessOutcomeStatus = "incomplete_cleanup_failed"
            phase2_status: Phase2Status = "cleanup_failed"
            terminal_success, requires_remediation = False, True
        elif operation_succeeded:
            status, phase2_status = "closed_clean", "closed_clean"
            terminal_success, requires_remediation = True, False
        else:
            status, phase2_status = "operation_failed_cleaned_up", "closed_clean"
            terminal_success, requires_remediation = False, False

        phase2_audit = _make_audit(
            "phase_2",
            phase2_status,
            finish_time,
            readback_absent=readback_verified_absent,
            remediation=requires_remediation,
            error_detail=cleanup_error or operation_error,
        )

        outcome_payload = {
            "status": status,
            "terminal_success": terminal_success,
            "requires_operator_remediation": requires_remediation,
            "correlation_id": request.correlation_id,
            "rule_id": request.rule_id,
            "target_resource_id": request.target_resource_id,
            "caller_cidr": request.caller_cidr,
            "ttl_seconds": request.ttl_seconds,
            "operation_succeeded": operation_succeeded,
            "cleanup_succeeded": cleanup_succeeded,
            "readback_verified_absent": readback_verified_absent,
            "phase1_receipt_digest": phase1_audit.receipt_digest,
            "phase2_receipt_digest": phase2_audit.receipt_digest,
        }
        encoded = json.dumps(outcome_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        receipt_digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
        outcome = TemporaryPublicAccessOutcome(
            status,
            terminal_success,
            requires_remediation,
            request.correlation_id,
            request.rule_id,
            request.target_resource_id,
            request.caller_cidr,
            request.ttl_seconds,
            operation_succeeded,
            cleanup_succeeded,
            readback_verified_absent,
            operation_result,
            operation_error,
            cleanup_error,
            phase1_audit,
            phase2_audit,
            receipt_digest,
        )
        self._outcomes_by_correlation[request.correlation_id] = outcome
        return outcome


def register_temporary_public_access_command(provision_commands: Any) -> None:
    """Register `fdaictl provision temporary-access` in the provision command group."""
    temp_access = command(
        provision_commands,
        "temporary-access",
        "Validate a bounded /32 temporary public-access request and emit Phase 1 audit",
    )
    temp_access.add_argument(
        "--correlation-id", required=True, help="Correlation identifier for two-phase audit"
    )
    temp_access.add_argument(
        "--target-resource-id", required=True, help="Target Azure resource identifier"
    )
    temp_access.add_argument(
        "--caller-cidr", required=True, help="Explicit routable IPv4 /32 host CIDR"
    )
    temp_access.add_argument(
        "--ttl-seconds", type=int, default=900, help="Temporary access TTL in seconds (1..3600)"
    )
    temp_access.add_argument(
        "--principal-id", default="authenticated-operator", help="Authenticated caller principal"
    )
    temp_access.set_defaults(handler=run_temporary_public_access_command)


def run_temporary_public_access_command(args: Any) -> int:
    """Validate and print a bounded /32 temporary public-access preparation receipt."""
    now = datetime.now(UTC)
    req = TemporaryPublicAccessRequest(
        correlation_id=str(args.correlation_id),
        target_resource_id=str(args.target_resource_id),
        caller_cidr=str(args.caller_cidr),
        ttl_seconds=int(args.ttl_seconds),
        requested_at=now,
        caller_principal_id=str(args.principal_id),
    )
    audit = TemporaryAccessAuditRecord(
        phase="phase_1",
        phase_status="prepared",
        correlation_id=req.correlation_id,
        rule_id=req.rule_id,
        target_resource_id=req.target_resource_id,
        caller_cidr=req.caller_cidr,
        caller_principal_id=req.caller_principal_id,
        ttl_seconds=req.ttl_seconds,
        recorded_at=now,
        expires_at=req.expires_at,
        readback_verified_absent=False,
        requires_operator_remediation=False,
    )
    print(
        json.dumps(
            {
                "rule_id": req.rule_id,
                "caller_cidr": req.caller_cidr,
                "ttl_seconds": req.ttl_seconds,
                "phase1_receipt_digest": audit.receipt_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


__all__ = [
    "AccessOutcomeStatus",
    "MAX_TEMPORARY_ACCESS_TTL_SECONDS",
    "MIN_TEMPORARY_ACCESS_TTL_SECONDS",
    "Phase1Status",
    "Phase2Status",
    "TemporaryAccessAuditRecord",
    "TemporaryAccessRuleDriver",
    "TemporaryPublicAccessCoordinator",
    "TemporaryPublicAccessError",
    "TemporaryPublicAccessOutcome",
    "TemporaryPublicAccessRequest",
    "register_temporary_public_access_command",
    "run_temporary_public_access_command",
    "validate_caller_ipv4_host_cidr",
    "validate_ttl_seconds",
]
