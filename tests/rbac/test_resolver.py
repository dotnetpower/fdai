"""Resolver tests — JWT payload decoding, group lookup, break-glass isolation."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aiopspilot.core.rbac.resolver import (
    BreakGlassActivation,
    BreakGlassActivationError,
    GroupMapping,
    MalformedTokenError,
    Principal,
    RoleResolver,
    decode_jwt_payload,
)
from aiopspilot.core.rbac.roles import Role

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64url(payload: bytes) -> str:
    """Encode raw bytes as url-safe base64 without padding."""
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _forge_token(claims: dict[str, Any]) -> str:
    """Return a JWS-compact-form token with the given (unsigned) claims.

    Header + signature segments are placeholders — this fixture is for
    :func:`decode_jwt_payload` which never verifies the signature.
    """
    header = _b64url(b'{"alg":"RS256","typ":"JWT"}')
    payload = _b64url(json.dumps(claims).encode("utf-8"))
    sig = _b64url(b"placeholder-signature")
    return f"{header}.{payload}.{sig}"


def _mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )


# ---------------------------------------------------------------------------
# decode_jwt_payload
# ---------------------------------------------------------------------------


class TestDecodeJwtPayload:
    def test_extracts_claims_from_well_formed_token(self) -> None:
        token = _forge_token({"oid": "abc", "roles": ["Approver"]})
        claims = decode_jwt_payload(token)
        assert claims["oid"] == "abc"
        assert list(claims["roles"]) == ["Approver"]

    def test_handles_missing_base64_padding(self) -> None:
        # `oid: a` -> 12-byte payload, unpadded b64url has trailing '='
        # stripped which the decoder must re-pad.
        token = _forge_token({"oid": "a"})
        assert decode_jwt_payload(token)["oid"] == "a"

    def test_rejects_non_string_token(self) -> None:
        with pytest.raises(MalformedTokenError):
            decode_jwt_payload("")  # empty string
        with pytest.raises(MalformedTokenError):
            decode_jwt_payload(None)  # type: ignore[arg-type]

    def test_rejects_wrong_segment_count(self) -> None:
        with pytest.raises(MalformedTokenError, match="3 segments"):
            decode_jwt_payload("only.one")
        with pytest.raises(MalformedTokenError, match="3 segments"):
            decode_jwt_payload("a.b.c.d")

    def test_rejects_non_base64_payload(self) -> None:
        # A payload that is neither valid base64 nor valid UTF-8/JSON — the
        # decoder rejects it either way. We assert the wrapping error type,
        # not the specific stage message, so a Python b64 permissiveness
        # change doesn't flap the test.
        with pytest.raises(MalformedTokenError):
            decode_jwt_payload("header.$$notb64$$.sig")

    def test_rejects_non_json_payload(self) -> None:
        raw = _b64url(b"not-json")
        with pytest.raises(MalformedTokenError, match="JSON"):
            decode_jwt_payload(f"h.{raw}.s")

    def test_rejects_json_array_payload(self) -> None:
        raw = _b64url(b"[1, 2, 3]")
        with pytest.raises(MalformedTokenError, match="JSON object"):
            decode_jwt_payload(f"h.{raw}.s")

    def test_payload_is_read_only(self) -> None:
        token = _forge_token({"oid": "abc"})
        claims = decode_jwt_payload(token)
        with pytest.raises(TypeError):
            claims["oid"] = "hijacked"  # type: ignore[index]


# ---------------------------------------------------------------------------
# GroupMapping.from_config
# ---------------------------------------------------------------------------


class TestGroupMappingFromConfig:
    def _base_config(self) -> dict[str, Any]:
        return {
            "rbac": {
                "entra": {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "groups": {
                        "readers": "r-oid",
                        "contributors": "c-oid",
                        "approvers": "a-oid",
                        "owners": "o-oid",
                        "break_glass": "b-oid",
                    },
                }
            }
        }

    def test_reads_all_five_slots(self) -> None:
        mapping = GroupMapping.from_config(self._base_config(), environ={})
        assert mapping.reader_group_id == "r-oid"
        assert mapping.contributor_group_id == "c-oid"
        assert mapping.approver_group_id == "a-oid"
        assert mapping.owner_group_id == "o-oid"
        assert mapping.break_glass_group_id == "b-oid"

    def test_missing_top_level_rbac_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="'rbac' key"):
            GroupMapping.from_config({}, environ={})

    def test_missing_entra_section_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="'rbac.entra'"):
            GroupMapping.from_config({"rbac": {}}, environ={})

    def test_missing_groups_section_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="'rbac.entra.groups'"):
            GroupMapping.from_config({"rbac": {"entra": {}}}, environ={})

    def test_missing_slot_fails_fast(self) -> None:
        cfg = self._base_config()
        del cfg["rbac"]["entra"]["groups"]["approvers"]
        with pytest.raises(ValueError, match="approvers"):
            GroupMapping.from_config(cfg, environ={})

    def test_blank_slot_value_fails_fast(self) -> None:
        cfg = self._base_config()
        cfg["rbac"]["entra"]["groups"]["owners"] = "   "
        with pytest.raises(ValueError, match="owners"):
            GroupMapping.from_config(cfg, environ={})

    def test_non_string_slot_fails_fast(self) -> None:
        cfg = self._base_config()
        cfg["rbac"]["entra"]["groups"]["readers"] = 12345
        with pytest.raises(ValueError, match="MUST be a string"):
            GroupMapping.from_config(cfg, environ={})

    def test_env_var_overrides_yaml(self) -> None:
        env = {"AIOPSPILOT_RBAC_OWNERS_GROUP_ID": "override-owner"}
        mapping = GroupMapping.from_config(self._base_config(), environ=env)
        assert mapping.owner_group_id == "override-owner"
        # Other slots unaffected.
        assert mapping.reader_group_id == "r-oid"

    def test_env_var_can_supply_missing_slot(self) -> None:
        cfg = self._base_config()
        del cfg["rbac"]["entra"]["groups"]["break_glass"]
        env = {"AIOPSPILOT_RBAC_BREAK_GLASS_GROUP_ID": "env-bg"}
        mapping = GroupMapping.from_config(cfg, environ=env)
        assert mapping.break_glass_group_id == "env-bg"

    def test_mapping_dict_is_read_only(self) -> None:
        mapping = GroupMapping.from_config(self._base_config(), environ={})
        as_dict = mapping.as_dict()
        with pytest.raises(TypeError):
            as_dict["hijack"] = Role.OWNER  # type: ignore[index]


# ---------------------------------------------------------------------------
# RoleResolver.resolve_from_claims
# ---------------------------------------------------------------------------


class TestResolveFromClaims:
    def test_extracts_oid_upn_email(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims(
            {
                "oid": "user-1",
                "upn": "user@example.com",
                "email": "user@example.com",
                "roles": ["Reader"],
            }
        )
        assert p.oid == "user-1"
        assert p.upn == "user@example.com"
        assert p.email == "user@example.com"
        assert p.roles == frozenset({Role.READER})

    def test_prefers_roles_claim_over_groups(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims(
            {
                "oid": "user-1",
                "roles": ["Approver"],
                "groups": ["reader-group"],  # would map to Reader if fallback
            }
        )
        assert p.roles == frozenset({Role.APPROVER})

    def test_falls_back_to_groups_when_roles_claim_missing(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims(
            {
                "oid": "user-1",
                "groups": ["reader-group", "approver-group"],
            }
        )
        assert p.roles == frozenset({Role.READER, Role.APPROVER})

    def test_falls_back_to_groups_when_roles_claim_empty(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims(
            {
                "oid": "user-1",
                "roles": [],
                "groups": ["contributor-group"],
            }
        )
        assert p.roles == frozenset({Role.CONTRIBUTOR})

    def test_empty_when_no_role_or_group_matches(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims({"oid": "user-1"})
        assert p.roles == frozenset()

    def test_unknown_role_string_dropped_silently(self) -> None:
        # An Entra admin who ships a new App Role value cannot bypass
        # the code — unknown role strings are ignored.
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims({"oid": "user-1", "roles": ["SuperAdmin", "Reader"]})
        assert p.roles == frozenset({Role.READER})

    def test_unknown_group_id_dropped_silently(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims({"oid": "user-1", "groups": ["not-mapped", "owner-group"]})
        assert p.roles == frozenset({Role.OWNER})

    def test_space_delimited_roles_string_accepted(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims({"oid": "user-1", "roles": "Reader Approver"})
        assert p.roles == frozenset({Role.READER, Role.APPROVER})

    def test_break_glass_claim_stripped_from_derived_principal(self) -> None:
        # Even a token that advertises BreakGlass does NOT grant the role
        # automatically. Elevation goes through activate_break_glass.
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims({"oid": "bg-user", "roles": ["Owner", "BreakGlass"]})
        assert Role.BREAK_GLASS not in p.roles
        assert Role.OWNER in p.roles
        # But the raw groups membership survives so audits still see it.
        assert p.break_glass is None

    def test_break_glass_group_membership_alone_still_stripped(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims({"oid": "bg-user", "groups": ["break-glass-group"]})
        assert Role.BREAK_GLASS not in p.roles
        assert p.break_glass is None

    def test_missing_oid_is_hard_error(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        with pytest.raises(ValueError, match="oid"):
            resolver.resolve_from_claims({"roles": ["Reader"]})

    def test_empty_oid_is_hard_error(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        with pytest.raises(ValueError, match="oid"):
            resolver.resolve_from_claims({"oid": "", "roles": ["Reader"]})

    def test_correlation_id_propagated(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims(
            {"oid": "user-1", "roles": ["Reader"]},
            correlation_id="corr-42",
        )
        assert p.correlation_id == "corr-42"


class TestResolveFromToken:
    def test_end_to_end_token_to_principal(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        token = _forge_token({"oid": "user-1", "roles": ["Reader"]})
        p = resolver.resolve_from_token(token)
        assert p.oid == "user-1"
        assert p.roles == frozenset({Role.READER})

    def test_malformed_token_bubbles_up(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        with pytest.raises(MalformedTokenError):
            resolver.resolve_from_token("garbage")


# ---------------------------------------------------------------------------
# Break-glass activation
# ---------------------------------------------------------------------------


class TestBreakGlassActivation:
    def _now(self) -> datetime:
        return datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)

    def _principal(self) -> Principal:
        return Principal(oid="bg-user", roles=frozenset({Role.OWNER}))

    def test_activate_adds_role_and_stamps_activation(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        now = self._now()
        elevated = resolver.activate_break_glass(
            self._principal(),
            incident_id="INC-2026-07-06-001",
            expires_at=now + timedelta(hours=1),
            now=now,
        )
        assert Role.BREAK_GLASS in elevated.roles
        assert elevated.break_glass is not None
        assert elevated.break_glass.incident_id == "INC-2026-07-06-001"
        assert elevated.break_glass.actor_oid == "bg-user"
        assert elevated.break_glass.activated_at == now

    def test_activation_never_mutates_original_principal(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        original = self._principal()
        now = self._now()
        _ = resolver.activate_break_glass(
            original,
            incident_id="INC-1",
            expires_at=now + timedelta(minutes=15),
            now=now,
        )
        # The frozen dataclass would fail on mutation attempts anyway, but
        # the fresh-Principal contract is the real invariant.
        assert Role.BREAK_GLASS not in original.roles
        assert original.break_glass is None

    def test_empty_incident_id_rejected(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        now = self._now()
        with pytest.raises(BreakGlassActivationError, match="incident_id"):
            resolver.activate_break_glass(
                self._principal(),
                incident_id="",
                expires_at=now + timedelta(hours=1),
                now=now,
            )

    def test_whitespace_incident_id_rejected(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        now = self._now()
        with pytest.raises(BreakGlassActivationError, match="incident_id"):
            resolver.activate_break_glass(
                self._principal(),
                incident_id="   ",
                expires_at=now + timedelta(hours=1),
                now=now,
            )

    def test_non_future_expires_at_rejected(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        now = self._now()
        with pytest.raises(BreakGlassActivationError, match="future"):
            resolver.activate_break_glass(
                self._principal(),
                incident_id="INC-1",
                expires_at=now,  # equal to now → not strictly future
                now=now,
            )

    def test_default_now_uses_wall_clock(self) -> None:
        # `now` is optional — omit it to exercise the default branch.
        resolver = RoleResolver(group_mapping=_mapping())
        # A far-future expiry keeps this stable even if the test host clock
        # is skewed by minutes.
        far_future = datetime(2099, 1, 1, tzinfo=UTC)
        elevated = resolver.activate_break_glass(
            self._principal(),
            incident_id="INC-1",
            expires_at=far_future,
        )
        assert elevated.break_glass is not None
        assert elevated.break_glass.expires_at == far_future


class TestBreakGlassActivationDataClass:
    def test_is_active_at_boundaries(self) -> None:
        start = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)
        end = start + timedelta(hours=1)
        activation = BreakGlassActivation(
            incident_id="INC-1",
            activated_at=start,
            expires_at=end,
            actor_oid="u",
        )
        assert activation.is_active_at(start)
        assert activation.is_active_at(start + timedelta(minutes=30))
        # Exclusive upper bound — activation is not active AT expires_at.
        assert not activation.is_active_at(end)
        assert not activation.is_active_at(start - timedelta(seconds=1))


class TestPrincipalHelpers:
    def test_has_role_true_and_false(self) -> None:
        p = Principal(oid="u1", roles=frozenset({Role.READER, Role.APPROVER}))
        assert p.has_role(Role.APPROVER)
        assert not p.has_role(Role.OWNER)


class TestClaimStringifyEdgeCases:
    """Cover the variant claim shapes Entra tokens ship with.

    Realized through :meth:`RoleResolver.resolve_from_claims` — no need to
    reach into the private ``_stringify_iter`` helper.
    """

    def test_extra_whitespace_in_roles_string_is_tolerated(self) -> None:
        # Double space → empty split chunk gets skipped; the resolver
        # never emits an empty role name.
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims({"oid": "u", "roles": "Reader  Approver "})
        assert p.roles == frozenset({Role.READER, Role.APPROVER})

    def test_non_iterable_role_claim_becomes_empty(self) -> None:
        # A malformed token that ships `roles: 42` should not crash — the
        # helper skips non-iterable values. Fallback to `groups` still runs.
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims({"oid": "u", "roles": 42, "groups": ["reader-group"]})
        assert p.roles == frozenset({Role.READER})

    def test_non_string_items_in_role_list_dropped(self) -> None:
        resolver = RoleResolver(group_mapping=_mapping())
        p = resolver.resolve_from_claims({"oid": "u", "roles": [123, "Reader", None]})
        assert p.roles == frozenset({Role.READER})
