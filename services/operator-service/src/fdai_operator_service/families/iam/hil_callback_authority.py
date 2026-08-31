"""Server-owned Entra authority for Teams and Slack approval callbacks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final, Protocol

from fdai_operator_service.auth import AuthenticationError, OperatorAuthenticator
from fdai_operator_service.families.iam.capabilities import IamCapability, has_capability
from fdai_operator_service.families.iam.hil_callback_audit import actor_identity_reference
from fdai_service_contracts import OperatorPrincipalKind, OperatorRole

TEAMS_APPLICATION_ID_ENV: Final = "FDAI_TEAMS_APPLICATION_ID"
TEAMS_PRINCIPAL_MAP_ENV: Final = "FDAI_TEAMS_PRINCIPAL_MAP_JSON"
TEAMS_APPROVAL_TEAM_ID_ENV: Final = "FDAI_TEAMS_APPROVAL_TEAM_ID"
TEAMS_APPROVAL_CHANNEL_ID_ENV: Final = "FDAI_TEAMS_APPROVAL_CHANNEL_ID"
SLACK_PRINCIPAL_MAP_ENV: Final = "FDAI_SLACK_PRINCIPAL_MAP_JSON"
SLACK_TEAM_ID_ENV: Final = "FDAI_SLACK_TEAM_ID"
_MAX_MAPPINGS: Final = 1_000


class HilCallbackChannel(StrEnum):
    """Supported A1 callback channels."""

    TEAMS = "teams"
    SLACK = "slack"


class HilCallbackAuthorityError(ValueError):
    """A callback lacks current server-owned approval authority."""

    def __init__(self, message: str, *, status_code: int, kind: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind


class HilCallbackAuthority(Protocol):
    """Authenticate one provider callback through current Entra authority.

    ``authorization`` carries the delegated (OBO) user token the transport
    authenticated. For Teams that token arrives inside the verified Bot
    activity, not in the HTTP ``Authorization`` header, so the seam takes the
    token value rather than the request.
    """

    async def authenticate(
        self,
        *,
        authorization: str | None,
        channel: HilCallbackChannel,
        provider_actor_id: str,
        audience: str,
    ) -> HilCallbackActor: ...


@dataclass(frozen=True, slots=True)
class HilCallbackActor:
    """Authenticated human identity and sanitized authority evidence."""

    oid: str
    identity_ref: str
    roles: frozenset[OperatorRole]
    authority_basis: str


@dataclass(frozen=True, slots=True)
class HilCallbackAuthorityConfig:
    """Resolve A1 audience and provider mappings from deployment inputs."""

    teams_application_id: str | None
    teams_approval_audience: str | None
    slack_approval_audience: str | None
    teams_principal_by_sender_id: Mapping[str, str]
    slack_principal_by_sender_id: Mapping[str, str]

    @classmethod
    def from_environment(
        cls,
        values: Mapping[str, str],
        *,
        group_ids: Mapping[OperatorRole, str],
    ) -> HilCallbackAuthorityConfig:
        """Derive channel audiences independently from the five RBAC group slots."""
        expected_roles = frozenset(OperatorRole)
        if frozenset(group_ids) != expected_roles or any(
            not group_ids[role].strip() for role in expected_roles
        ):
            raise ValueError("HIL callback authority requires all five Entra group slots")
        teams_application_id = values.get(TEAMS_APPLICATION_ID_ENV, "").strip()
        teams_team_id = values.get(TEAMS_APPROVAL_TEAM_ID_ENV, "").strip()
        teams_channel_id = values.get(TEAMS_APPROVAL_CHANNEL_ID_ENV, "").strip()
        teams_principal_map = values.get(TEAMS_PRINCIPAL_MAP_ENV, "").strip()
        teams_values = (
            teams_application_id,
            teams_team_id,
            teams_channel_id,
            teams_principal_map,
        )
        if any(teams_values) and not all(teams_values):
            raise ValueError(
                "Teams A1 requires application, approval team, approval channel, and principal map"
            )

        slack_team_id = values.get(SLACK_TEAM_ID_ENV, "").strip()
        slack_principal_map = values.get(SLACK_PRINCIPAL_MAP_ENV, "").strip()
        if bool(slack_team_id) != bool(slack_principal_map):
            raise ValueError("Slack A1 requires both team id and principal map")

        return cls(
            teams_application_id=teams_application_id or None,
            teams_approval_audience=(
                f"teams:{teams_team_id}:{teams_channel_id}" if teams_team_id else None
            ),
            slack_approval_audience=f"slack:{slack_team_id}" if slack_team_id else None,
            teams_principal_by_sender_id=MappingProxyType(
                _principal_map(teams_principal_map, allow_empty=not teams_principal_map)
            ),
            slack_principal_by_sender_id=MappingProxyType(
                _principal_map(slack_principal_map, allow_empty=not slack_principal_map)
            ),
        )

    @property
    def teams_a1_enabled(self) -> bool:
        """Report whether Teams A1 has one complete audience and actor mapping."""
        return self.teams_approval_audience is not None

    @property
    def slack_a1_enabled(self) -> bool:
        """Report whether Slack A1 has at least one explicit Entra mapping."""
        return self.slack_approval_audience is not None


@dataclass(frozen=True, slots=True)
class EntraHilCallbackAuthority:
    """Authenticate an OBO/API bearer and re-resolve current approver authority."""

    authenticator: OperatorAuthenticator
    config: HilCallbackAuthorityConfig

    async def authenticate(
        self,
        *,
        authorization: str | None,
        channel: HilCallbackChannel,
        provider_actor_id: str,
        audience: str,
    ) -> HilCallbackActor:
        """Bind provider identity, token client, audience, and current App Roles."""
        expected_audience = (
            self.config.teams_approval_audience
            if channel is HilCallbackChannel.TEAMS
            else self.config.slack_approval_audience
        )
        if channel is HilCallbackChannel.TEAMS and not self.config.teams_a1_enabled:
            raise HilCallbackAuthorityError(
                "Teams A1 is disabled until its approval team and channel are configured",
                status_code=503,
                kind="teams_a1_disabled",
            )
        if channel is HilCallbackChannel.SLACK and not self.config.slack_a1_enabled:
            raise HilCallbackAuthorityError(
                "Slack A1 is disabled until its team and Entra mapping are configured",
                status_code=503,
                kind="slack_a1_disabled",
            )
        if audience != expected_audience:
            raise HilCallbackAuthorityError(
                "approval callback audience does not match the configured channel destination",
                status_code=403,
                kind="wrong_audience",
            )
        mapping = (
            self.config.teams_principal_by_sender_id
            if channel is HilCallbackChannel.TEAMS
            else self.config.slack_principal_by_sender_id
        )
        mapped_oid = mapping.get(provider_actor_id)
        if mapped_oid is None:
            raise HilCallbackAuthorityError(
                "callback provider identity has no Entra mapping",
                status_code=403,
                kind="actor_mapping_missing",
            )
        try:
            verified = self.authenticator.authenticate_identity(authorization)
        except AuthenticationError as exc:
            raise HilCallbackAuthorityError(
                "approval callback bearer authentication failed",
                status_code=401,
                kind="unauthorized",
            ) from exc
        principal = verified.principal
        if principal.principal_kind is not OperatorPrincipalKind.HUMAN:
            raise HilCallbackAuthorityError(
                "approval callback actor MUST be a human principal",
                status_code=403,
                kind="principal_forbidden",
            )
        if principal.subject_id.strip().casefold() != mapped_oid.strip().casefold():
            raise HilCallbackAuthorityError(
                "approval callback actor does not match the provider identity mapping",
                status_code=403,
                kind="wrong_actor",
            )
        if channel is HilCallbackChannel.TEAMS:
            expected_client = self.config.teams_application_id
            if expected_client is None:
                raise HilCallbackAuthorityError(
                    "Teams SSO OBO authority is not configured",
                    status_code=503,
                    kind="authority_unavailable",
                )
            if verified.authorized_party != expected_client:
                raise HilCallbackAuthorityError(
                    "Teams callback token was not issued to the configured approval bot",
                    status_code=403,
                    kind="wrong_client",
                )
            authority_basis = "teams_sso_obo+entra_app_role"
        else:
            authority_basis = "slack_mapping+entra_browser_reauthentication"
        if not has_capability(principal.roles, IamCapability.APPROVE_RUNTIME_HIL):
            raise HilCallbackAuthorityError(
                "approver lacks current runtime approval authority",
                status_code=403,
                kind="capability_forbidden",
            )
        return HilCallbackActor(
            oid=principal.subject_id.strip().casefold(),
            identity_ref=actor_identity_reference(principal.subject_id),
            # BreakGlass is emergency access, never approval authority, so it
            # never reaches a workflow role comparison or an audit basis.
            roles=principal.roles - {OperatorRole.BREAK_GLASS},
            authority_basis=authority_basis,
        )


def meets_role(roles: frozenset[OperatorRole], required_role: str) -> bool:
    """Return whether ordinary roles satisfy one configured minimum role."""
    rank = {
        OperatorRole.READER: 0,
        OperatorRole.CONTRIBUTOR: 1,
        OperatorRole.APPROVER: 2,
        OperatorRole.OWNER: 3,
    }
    try:
        required = OperatorRole(required_role)
    except ValueError:
        return False
    if required not in rank:
        return False
    return any(rank.get(role, -1) >= rank[required] for role in roles)


def _principal_map(value: str, *, allow_empty: bool) -> dict[str, str]:
    if not value.strip():
        return {} if allow_empty else _invalid_map()
    try:
        raw = json.loads(value, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("approval principal mapping MUST be valid JSON") from exc
    if not isinstance(raw, dict) or (not raw and not allow_empty) or len(raw) > _MAX_MAPPINGS:
        raise ValueError("approval principal mapping has an invalid entry count")
    result: dict[str, str] = {}
    for sender, oid in raw.items():
        if (
            not isinstance(sender, str)
            or not isinstance(oid, str)
            or not sender.strip()
            or not oid.strip()
            or len(sender) > 200
            or len(oid) > 256
        ):
            raise ValueError("approval principal mapping entries MUST be bounded text")
        result[sender.strip()] = oid.strip().casefold()
    return result


def _invalid_map() -> dict[str, str]:
    raise ValueError("approval principal mapping MUST be non-empty")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate approval principal mapping key")
        value[key] = item
    return value


__all__ = [
    "EntraHilCallbackAuthority",
    "HilCallbackActor",
    "HilCallbackAuthority",
    "HilCallbackAuthorityConfig",
    "HilCallbackAuthorityError",
    "HilCallbackChannel",
    "SLACK_TEAM_ID_ENV",
    "SLACK_PRINCIPAL_MAP_ENV",
    "TEAMS_APPROVAL_CHANNEL_ID_ENV",
    "TEAMS_APPROVAL_TEAM_ID_ENV",
    "TEAMS_APPLICATION_ID_ENV",
    "TEAMS_PRINCIPAL_MAP_ENV",
    "meets_role",
]
