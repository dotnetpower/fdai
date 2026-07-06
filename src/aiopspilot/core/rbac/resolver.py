"""Entra ID token claims → :class:`Principal` resolution.

Boundary contract
-----------------

The API layer is responsible for **cryptographic verification** of the token
before this module sees it: JWKS signature, ``aud``, ``iss``, ``exp``, ``nbf``
(see [`user-rbac-and-identity.md § 10.2`]
(../../../../docs/roadmap/user-rbac-and-identity.md#102-api-token-validation)).
By the time claims reach the :class:`RoleResolver` they are already trusted;
this module never re-hits the network.

:func:`decode_jwt_payload` is a **pure decoder**: it does the URL-safe
base64 unpad on the payload segment and returns the JSON claims. It DOES
NOT verify the signature. Callers MUST NOT feed its output to
:class:`RoleResolver` without an out-of-band signature check first — the
resolver docstrings repeat this to keep the invariant close to the
call site.

Break-Glass isolation
---------------------

Even if a token carries ``"roles": ["BreakGlass"]``, the resolver
returns a :class:`Principal` whose :attr:`Principal.roles` does *not*
include :attr:`Role.BREAK_GLASS`. Elevation happens only through
:meth:`RoleResolver.activate_break_glass`, which requires an incident id
and a timebox and produces a fresh :class:`Principal` with the role
attached. This preserves the "never automatically activated" rule from
the task spec.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Final

from aiopspilot.core.rbac.roles import Role


class MalformedTokenError(ValueError):
    """Raised when a bearer token cannot be split/decoded as a JWS compact JWT.

    Signature validity is out of scope; this error only covers structural
    problems (wrong segment count, invalid base64, non-JSON payload).
    """


class BreakGlassActivationError(RuntimeError):
    """Raised when :meth:`RoleResolver.activate_break_glass` is called with
    an empty ``incident_id`` or a non-future ``expires_at``.

    Kept separate from :class:`~aiopspilot.core.rbac.enforcer.AuthorizationError`
    because it fires *before* any authorization decision — the caller made
    a programmer error, not the principal.
    """


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BreakGlassActivation:
    """Operator-recorded activation for a break-glass session.

    The three fields correspond to the audit requirements in
    [`security-and-identity.md § HIL Approval Integrity`]
    (../../../../docs/roadmap/security-and-identity.md#hil-approval-integrity)
    and [`user-rbac-and-identity.md § 10.7`]
    (../../../../docs/roadmap/user-rbac-and-identity.md#107-break-glass-sign-in):
    every break-glass sign-in must record who, why (incident id), and until when.

    Activation is stateless in this data class — the caller (or the fork's
    audit adapter) is responsible for persisting the entry to the audit log
    before wrapping the principal with :meth:`RoleResolver.activate_break_glass`.
    """

    incident_id: str
    activated_at: datetime
    expires_at: datetime
    actor_oid: str

    def is_active_at(self, now: datetime) -> bool:
        """Return ``True`` iff ``activated_at <= now < expires_at``."""
        return self.activated_at <= now < self.expires_at


@dataclass(frozen=True, slots=True)
class Principal:
    """A resolved human identity.

    ``oid`` is the stable Entra user objectId — the identity used by the
    no-self-approval check and every audit entry. ``upn`` and ``email``
    are informational; audit MUST NOT rely on them for identity because
    they can change.

    ``roles`` is a frozenset (order-independent, hashable) so a
    :class:`Principal` remains fully immutable and can serve as a dict key.
    """

    oid: str
    roles: frozenset[Role] = field(default_factory=frozenset)
    upn: str | None = None
    email: str | None = None
    groups: frozenset[str] = field(default_factory=frozenset)
    correlation_id: str | None = None
    break_glass: BreakGlassActivation | None = None

    def has_role(self, role: Role) -> bool:
        """Return ``True`` iff the principal carries ``role``."""
        return role in self.roles

    def with_break_glass(self, activation: BreakGlassActivation) -> Principal:
        """Return a copy with :attr:`Role.BREAK_GLASS` added and activation stamped.

        Never mutates in place — a fresh :class:`Principal` is returned
        so an audit consumer sees the pre-elevation record when it
        matters.
        """
        new_roles = frozenset(self.roles | {Role.BREAK_GLASS})
        return Principal(
            oid=self.oid,
            roles=new_roles,
            upn=self.upn,
            email=self.email,
            groups=self.groups,
            correlation_id=self.correlation_id,
            break_glass=activation,
        )


# ---------------------------------------------------------------------------
# Config: Entra group objectId → Role mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GroupMapping:
    """Immutable Entra ``objectId`` → :class:`Role` mapping.

    Every role slot is required — a fork that fails to supply an entry
    gets a startup :class:`ValueError` (fail-fast, deny-by-default).
    Object IDs may be an empty-group placeholder in early forks; use the
    upstream default all-zero UUID for that.
    """

    reader_group_id: str
    contributor_group_id: str
    approver_group_id: str
    owner_group_id: str
    break_glass_group_id: str

    def as_dict(self) -> Mapping[str, Role]:
        """Return an ``{objectId: Role}`` mapping (read-only)."""
        return MappingProxyType(
            {
                self.reader_group_id: Role.READER,
                self.contributor_group_id: Role.CONTRIBUTOR,
                self.approver_group_id: Role.APPROVER,
                self.owner_group_id: Role.OWNER,
                self.break_glass_group_id: Role.BREAK_GLASS,
            }
        )

    @classmethod
    def from_config(
        cls, raw: Mapping[str, Any], *, environ: Mapping[str, str] | None = None
    ) -> GroupMapping:
        """Build a :class:`GroupMapping` from a parsed config mapping.

        Layout (matches ``config/rbac-groups.yaml``)::

            rbac:
              entra:
                tenant_id: <uuid>          # informational
                groups:
                  readers: <objectId>
                  contributors: <objectId>
                  approvers: <objectId>
                  owners: <objectId>
                  break_glass: <objectId>

        A missing slot fails fast with :class:`ValueError` — there is no
        "default reader group" that silently opens the read API. Env-var
        overrides let a fork adjust one slot without re-templating YAML::

            AIOPSPILOT_RBAC_READERS_GROUP_ID
            AIOPSPILOT_RBAC_CONTRIBUTORS_GROUP_ID
            AIOPSPILOT_RBAC_APPROVERS_GROUP_ID
            AIOPSPILOT_RBAC_OWNERS_GROUP_ID
            AIOPSPILOT_RBAC_BREAK_GLASS_GROUP_ID
        """
        env = environ if environ is not None else os.environ
        rbac_root = raw.get("rbac")
        if not isinstance(rbac_root, Mapping):
            raise ValueError("rbac-groups config: top-level 'rbac' key missing")
        entra = rbac_root.get("entra")
        if not isinstance(entra, Mapping):
            raise ValueError("rbac-groups config: 'rbac.entra' section missing")
        groups = entra.get("groups")
        if not isinstance(groups, Mapping):
            raise ValueError("rbac-groups config: 'rbac.entra.groups' section missing")

        def _pick(config_key: str, env_key: str) -> str:
            override = env.get(env_key)
            if override is not None:
                value: object = override
            else:
                value = groups.get(config_key)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(
                    f"rbac-groups config: 'rbac.entra.groups.{config_key}' "
                    f"is required (env override: {env_key})"
                )
            if not isinstance(value, str):
                raise ValueError(
                    f"rbac-groups config: 'rbac.entra.groups.{config_key}' "
                    "MUST be a string objectId"
                )
            return value

        return cls(
            reader_group_id=_pick("readers", "AIOPSPILOT_RBAC_READERS_GROUP_ID"),
            contributor_group_id=_pick("contributors", "AIOPSPILOT_RBAC_CONTRIBUTORS_GROUP_ID"),
            approver_group_id=_pick("approvers", "AIOPSPILOT_RBAC_APPROVERS_GROUP_ID"),
            owner_group_id=_pick("owners", "AIOPSPILOT_RBAC_OWNERS_GROUP_ID"),
            break_glass_group_id=_pick("break_glass", "AIOPSPILOT_RBAC_BREAK_GLASS_GROUP_ID"),
        )


# ---------------------------------------------------------------------------
# JWT payload decoding (stdlib-only, no signature verification)
# ---------------------------------------------------------------------------


_JWS_SEGMENTS: Final[int] = 3


def decode_jwt_payload(token: str) -> Mapping[str, Any]:
    """Decode the payload segment of a JWS compact JWT.

    **Does NOT verify the signature.** The API layer MUST validate the
    token against Entra JWKS + audience + issuer + expiry BEFORE the
    resolver acts on the returned claims. This function exists to give
    tests and offline tools a stdlib-only way to look at a token, and to
    give the read-API layer a claim extractor after its verifier has
    already accepted the token.
    """
    if not token or not isinstance(token, str):
        raise MalformedTokenError("token MUST be a non-empty string")
    segments = token.split(".")
    if len(segments) != _JWS_SEGMENTS:
        raise MalformedTokenError(
            f"JWS compact form requires exactly 3 segments, got {len(segments)}"
        )
    payload_b64 = segments[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError) as exc:
        raise MalformedTokenError(f"payload segment is not base64url: {exc}") from exc
    try:
        parsed = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedTokenError(f"payload is not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise MalformedTokenError("payload MUST be a JSON object")
    # Freeze to discourage accidental mutation between decoder and resolver.
    return MappingProxyType(parsed)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class RoleResolver:
    """Map an Entra ID claims dict → :class:`Principal`.

    Preference order for role extraction (matches
    [`user-rbac-and-identity.md § 4.4`]
    (../../../../docs/roadmap/user-rbac-and-identity.md#44-app-roles-token-surface)):

    1. **App Roles** (``roles`` claim) — the API-declared surface. Values
       are matched case-sensitively against :class:`Role` values so an
       unknown role string is dropped, not swallowed.
    2. **Group membership** (``groups`` claim) — mapped via
       :class:`GroupMapping`. Used as a fallback when the ``roles`` claim
       is missing or empty (upgrade path for tenants that have not yet
       assigned App Roles).

    :attr:`Role.BREAK_GLASS` is always stripped from the returned
    :class:`Principal`. Elevate explicitly via :meth:`activate_break_glass`.
    """

    def __init__(self, *, group_mapping: GroupMapping) -> None:
        self._group_mapping = group_mapping
        self._objectid_to_role = group_mapping.as_dict()

    def resolve_from_claims(
        self, claims: Mapping[str, Any], *, correlation_id: str | None = None
    ) -> Principal:
        """Return a :class:`Principal` derived from already-verified claims.

        ``claims`` is expected to have already passed signature, audience,
        issuer, expiry, and nbf checks at the API boundary. The resolver
        never re-hits the network.
        """
        oid = claims.get("oid")
        if not isinstance(oid, str) or not oid:
            raise ValueError("claims MUST carry a non-empty 'oid' — Entra stable user id")

        upn = claims.get("upn") if isinstance(claims.get("upn"), str) else None
        email = claims.get("email") if isinstance(claims.get("email"), str) else None

        raw_roles = claims.get("roles") or ()
        raw_groups = claims.get("groups") or ()

        # Isolate BreakGlass — see module docstring.
        role_set = frozenset(_parse_role_claim(raw_roles) - {Role.BREAK_GLASS})
        if not role_set:
            role_set = frozenset(self._roles_from_groups(raw_groups) - {Role.BREAK_GLASS})

        group_set = frozenset(_stringify_iter(raw_groups))

        return Principal(
            oid=oid,
            roles=role_set,
            upn=upn,
            email=email,
            groups=group_set,
            correlation_id=correlation_id,
            break_glass=None,
        )

    def resolve_from_token(self, token: str, *, correlation_id: str | None = None) -> Principal:
        """Convenience: :func:`decode_jwt_payload` + :meth:`resolve_from_claims`.

        Callers on the API boundary SHOULD prefer :meth:`resolve_from_claims`
        after their JWT verifier already parsed the token, so signature
        checks and claim extraction share one code path.
        """
        payload = decode_jwt_payload(token)
        return self.resolve_from_claims(payload, correlation_id=correlation_id)

    def activate_break_glass(
        self,
        principal: Principal,
        *,
        incident_id: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> Principal:
        """Return a copy of ``principal`` with :attr:`Role.BREAK_GLASS` attached.

        Requires an operator-recorded ``incident_id`` and a strictly-future
        ``expires_at``. The activation is a full :class:`BreakGlassActivation`
        stamp that the caller (audit adapter) MUST also persist to the
        append-only audit log alongside this call.

        The principal MUST already carry the ``BreakGlass`` App Role claim
        in the *token* — the resolver stripped it from the working
        :class:`Principal`, but presence in the raw claims means the
        Entra membership check passed. Passing an OID whose token never
        carried it constitutes an authorization bypass, so this method
        does NOT re-check membership itself; the caller feeds it a
        principal built from claims that included ``BreakGlass``.
        """
        if not incident_id or not incident_id.strip():
            raise BreakGlassActivationError(
                "break-glass activation requires a non-empty incident_id"
            )
        current = now if now is not None else datetime.now(UTC)
        if expires_at <= current:
            raise BreakGlassActivationError("break-glass expires_at MUST be strictly in the future")
        activation = BreakGlassActivation(
            incident_id=incident_id,
            activated_at=current,
            expires_at=expires_at,
            actor_oid=principal.oid,
        )
        return principal.with_break_glass(activation)

    def _roles_from_groups(self, raw_groups: object) -> frozenset[Role]:
        acc: set[Role] = set()
        for gid in _stringify_iter(raw_groups):
            role = self._objectid_to_role.get(gid)
            if role is not None:
                acc.add(role)
        return frozenset(acc)


def _parse_role_claim(raw: object) -> frozenset[Role]:
    """Parse a ``roles`` claim into a frozenset of known :class:`Role` values.

    Unknown strings are dropped silently — the claim is trusted for the
    values it declares, but an Entra admin who invents a new App Role
    value does not gain a runtime capability until this code names it.
    """
    values: set[Role] = set()
    for item in _stringify_iter(raw):
        try:
            values.add(Role(item))
        except ValueError:
            # Unknown role string — drop, do not raise.
            continue
    return frozenset(values)


def _stringify_iter(raw: object) -> Iterable[str]:
    """Yield string items from a claim value, tolerating both str and list forms.

    Entra claim shapes vary: some tokens ship ``roles`` as a JSON array,
    others as a space-delimited string. We accept either and skip
    non-string junk.
    """
    if isinstance(raw, str):
        # str.split() with no argument never yields empty strings, so we
        # trust each chunk directly.
        yield from raw.split()
        return
    if isinstance(raw, Iterable):
        for item in raw:
            if isinstance(item, str) and item:
                yield item


__all__ = [
    "BreakGlassActivation",
    "BreakGlassActivationError",
    "GroupMapping",
    "MalformedTokenError",
    "Principal",
    "RoleResolver",
    "decode_jwt_payload",
]
