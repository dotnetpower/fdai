"""Capability license token and entitlement resolution tests."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.capability_catalog import (
    Capability,
    CapabilityCatalog,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.core.licensing import (
    DeploymentBinding,
    LicenseClaims,
    LicenseStatus,
    LicenseTokenError,
    encode_license_token,
    parse_license_token,
    resolve_entitlement,
)

_NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
_SIGNATURE = b"s" * 64


class _AcceptAll:
    def verify(self, document: bytes, signature: bytes) -> bool:
        return True


class _RejectAll:
    def verify(self, document: bytes, signature: bytes) -> bool:
        return False


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog(
        [
            Capability(
                capability_id="cost.metering",
                name="Cost metering",
                category=CapabilityCategory.COST,
                summary="Read cost rollups.",
                side_effect_class=SideEffectClass.READ,
            ),
            Capability(
                capability_id="incident.restart",
                name="Restart",
                category=CapabilityCategory.INCIDENT,
                summary="Restart a target.",
                side_effect_class=SideEffectClass.EXECUTE,
            ),
            Capability(
                capability_id="chaos.run-experiment",
                name="Run experiment",
                category=CapabilityCategory.CHAOS,
                summary="Run a resilience experiment.",
                side_effect_class=SideEffectClass.SIMULATE,
            ),
        ]
    )


def _claims(**overrides: object) -> LicenseClaims:
    values: dict[str, object] = {
        "license_id": "lic-0001",
        "distribution_id": "example-distribution",
        "capability_ids": ("cost.metering", "incident.restart"),
        "not_before": _NOW - timedelta(days=1),
        "not_after": _NOW + timedelta(days=30),
    }
    values.update(overrides)
    return LicenseClaims(**values)  # type: ignore[arg-type]


def _token(claims: LicenseClaims) -> str:
    return encode_license_token(claims.canonical_document(), _SIGNATURE)


def test_token_round_trips_without_loss() -> None:
    claims = _claims(image_digest="a" * 64, tenant_binding="b" * 64)

    parsed, document, signature = parse_license_token(_token(claims))

    assert parsed == claims
    assert document == claims.canonical_document()
    assert signature == _SIGNATURE


def test_canonical_document_is_stable_across_capability_order() -> None:
    """The signed bytes MUST NOT depend on how the issuer ordered claims."""
    forward = _claims(capability_ids=("cost.metering", "incident.restart"))
    reversed_order = _claims(capability_ids=("incident.restart", "cost.metering"))

    assert forward.canonical_document() == reversed_order.canonical_document()


def test_document_never_carries_a_raw_tenant_identifier() -> None:
    """Only digests may bind a license, so no customer value can leak."""
    with pytest.raises(LicenseTokenError, match="tenant_binding"):
        _claims(tenant_binding="contoso.onmicrosoft.com")


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-token",
        "a.b.c",
        "!!!.###",
    ],
)
def test_malformed_tokens_are_rejected(token: str) -> None:
    with pytest.raises(LicenseTokenError):
        parse_license_token(token)


@pytest.mark.parametrize("filler", [" ", "\n", "\t", "\r\n"])
def test_outer_whitespace_is_not_a_second_spelling_of_the_same_token(filler: str) -> None:
    token = _token(_claims())

    for variant in (f"{filler}{token}", f"{token}{filler}"):
        with pytest.raises(LicenseTokenError, match="base64url"):
            parse_license_token(variant)


def test_semantically_equivalent_document_must_use_canonical_json_bytes() -> None:
    document = json.dumps(json.loads(_claims().canonical_document()), indent=2).encode("utf-8")

    with pytest.raises(LicenseTokenError, match="document is not canonically encoded"):
        parse_license_token(encode_license_token(document, _SIGNATURE))


def test_unknown_document_fields_are_rejected() -> None:
    """An unknown field could carry an entitlement the runtime ignores."""
    document = json.loads(_claims().canonical_document())
    document["autonomy_mode"] = "enforce"
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")

    with pytest.raises(LicenseTokenError, match="unknown fields"):
        parse_license_token(encode_license_token(payload, _SIGNATURE))


def test_short_signature_is_rejected() -> None:
    segment = base64.urlsafe_b64encode(_claims().canonical_document()).decode().rstrip("=")
    truncated = base64.urlsafe_b64encode(b"short").decode().rstrip("=")

    with pytest.raises(LicenseTokenError, match="64 bytes"):
        parse_license_token(f"{segment}.{truncated}")


@pytest.mark.parametrize("filler", ["\n\n\n\n", "    ", "\t\t\t\t", "\r\n\r\n"])
def test_one_license_cannot_be_presented_as_a_second_token_string(filler: str) -> None:
    """Base64 decoding drops non-alphabet characters, so a padded-out segment
    would decode to the same signed bytes and stay valid. Accepting those would
    give one license unlimited distinct token strings, and every control keyed
    on the token - revocation, reuse detection, audit correlation - would be
    evaded by adding whitespace.
    """
    document, signature = _token(_claims()).split(".")
    midpoint = len(document) // 2

    for variant in (
        f"{document[:midpoint]}{filler}{document[midpoint:]}.{signature}",
        f"{document}.{signature[:30]}{filler}{signature[30:]}",
    ):
        with pytest.raises(LicenseTokenError, match="base64url"):
            parse_license_token(variant)


def test_a_padded_segment_is_not_a_second_spelling_of_the_same_token() -> None:
    document, signature = _token(_claims()).split(".")

    with pytest.raises(LicenseTokenError, match="base64url"):
        parse_license_token(f"{document}==.{signature}")


def test_a_final_group_with_dirty_unused_bits_is_rejected() -> None:
    """Two encodings can decode to the same bytes when the last group's unused
    bits are not zero. Only the encoding this codec emits is accepted.
    """
    document, signature = _token(_claims()).split(".")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    dirty = alphabet[alphabet.index(signature[-1]) + 1]
    variant = f"{document}.{signature[:-1]}{dirty}"

    assert variant != f"{document}.{signature}"
    with pytest.raises(LicenseTokenError, match="canonically encoded"):
        parse_license_token(variant)


def test_expired_window_is_rejected_at_construction() -> None:
    with pytest.raises(LicenseTokenError, match="not_after MUST be later"):
        _claims(not_after=_NOW - timedelta(days=2))


def test_active_license_grants_only_listed_catalog_capabilities() -> None:
    entitlement = resolve_entitlement(
        catalog=_catalog(),
        token=_token(_claims()),
        verifier=_AcceptAll(),
        now=_NOW,
    )

    assert entitlement.status is LicenseStatus.ACTIVE
    assert entitlement.available_capability_ids == {"cost.metering", "incident.restart"}
    assert entitlement.license_id == "lic-0001"


def test_a_license_cannot_invent_a_capability() -> None:
    """Entitlement is an intersection, so a token cannot widen the catalog."""
    entitlement = resolve_entitlement(
        catalog=_catalog(),
        token=_token(_claims(capability_ids=("cost.metering", "not.in.catalog"))),
        verifier=_AcceptAll(),
        now=_NOW,
    )

    assert entitlement.available_capability_ids == {"cost.metering"}


def test_untrusted_signature_degrades_to_read_only() -> None:
    entitlement = resolve_entitlement(
        catalog=_catalog(),
        token=_token(_claims()),
        verifier=_RejectAll(),
        now=_NOW,
    )

    assert entitlement.status is LicenseStatus.UNTRUSTED
    assert entitlement.available_capability_ids == {"cost.metering"}


def test_expired_license_keeps_observation_and_drops_action() -> None:
    entitlement = resolve_entitlement(
        catalog=_catalog(),
        token=_token(_claims()),
        verifier=_AcceptAll(),
        now=_NOW + timedelta(days=31),
    )

    assert entitlement.status is LicenseStatus.EXPIRED
    assert entitlement.available_capability_ids == {"cost.metering"}
    assert entitlement.license_id == "lic-0001"


def test_license_before_its_window_is_not_yet_valid() -> None:
    entitlement = resolve_entitlement(
        catalog=_catalog(),
        token=_token(_claims()),
        verifier=_AcceptAll(),
        now=_NOW - timedelta(days=2),
    )

    assert entitlement.status is LicenseStatus.NOT_YET_VALID


def test_binding_mismatch_blocks_a_copied_license() -> None:
    """A token lifted from another deployment MUST NOT act here."""
    entitlement = resolve_entitlement(
        catalog=_catalog(),
        token=_token(_claims(image_digest="a" * 64)),
        verifier=_AcceptAll(),
        now=_NOW,
        binding=DeploymentBinding(image_digest="c" * 64),
    )

    assert entitlement.status is LicenseStatus.MISBOUND
    assert entitlement.available_capability_ids == {"cost.metering"}


def test_matching_binding_is_accepted() -> None:
    entitlement = resolve_entitlement(
        catalog=_catalog(),
        token=_token(_claims(image_digest="a" * 64, tenant_binding="b" * 64)),
        verifier=_AcceptAll(),
        now=_NOW,
        binding=DeploymentBinding(image_digest="a" * 64, tenant_binding="b" * 64),
    )

    assert entitlement.status is LicenseStatus.ACTIVE


def test_unlicensed_upstream_keeps_the_full_catalog() -> None:
    """This repository ships unlicensed; development MUST NOT be gated."""
    entitlement = resolve_entitlement(
        catalog=_catalog(),
        token=None,
        verifier=_RejectAll(),
        now=_NOW,
    )

    assert entitlement.status is LicenseStatus.ABSENT
    assert entitlement.available_capability_ids == {
        "cost.metering",
        "incident.restart",
        "chaos.run-experiment",
    }


def test_a_distribution_can_require_a_license() -> None:
    entitlement = resolve_entitlement(
        catalog=_catalog(),
        token=None,
        verifier=_RejectAll(),
        now=_NOW,
        require_license=True,
    )

    assert entitlement.status is LicenseStatus.ABSENT
    assert entitlement.available_capability_ids == {"cost.metering"}


def test_resolution_requires_an_explicit_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_entitlement(
            catalog=_catalog(),
            token=None,
            verifier=_AcceptAll(),
            now=datetime(2026, 7, 27, 12, 0),  # noqa: DTZ001 - the rejected input
        )


class _FailingVerifier:
    """A verifier holding a corrupt public key, which is how a bad key behaves."""

    def verify(self, document: bytes, signature: bytes) -> bool:
        raise ValueError("backend diagnostic must not escape")


def test_a_verifier_that_cannot_run_degrades_instead_of_crashing() -> None:
    """A corrupt packaged key would otherwise take the whole runtime down, which
    costs an operator the observability they need most while diagnosing it.
    """
    entitlement = resolve_entitlement(
        catalog=_catalog(),
        token=_token(_claims()),
        verifier=_FailingVerifier(),
        now=_NOW,
    )

    assert entitlement.status is LicenseStatus.UNTRUSTED
    assert entitlement.available_capability_ids == {"cost.metering"}
    assert entitlement.reason is not None
    assert entitlement.reason == "license signature could not be checked"
    assert "backend diagnostic" not in entitlement.reason


def test_a_valid_license_never_sees_less_than_an_expired_one() -> None:
    """Read-only capabilities are unlicensed, so omitting them from a license
    must not withdraw them. Otherwise renewing a license would remove an
    operator's dashboards.
    """
    acting_only = _claims(capability_ids=("incident.restart",))
    expired = _claims(
        capability_ids=("incident.restart",),
        not_before=_NOW - timedelta(days=30),
        not_after=_NOW - timedelta(days=1),
    )

    active = resolve_entitlement(
        catalog=_catalog(), token=_token(acting_only), verifier=_AcceptAll(), now=_NOW
    )
    lapsed = resolve_entitlement(
        catalog=_catalog(), token=_token(expired), verifier=_AcceptAll(), now=_NOW
    )

    assert active.status is LicenseStatus.ACTIVE
    assert lapsed.status is LicenseStatus.EXPIRED
    assert lapsed.available_capability_ids <= active.available_capability_ids
    assert active.available_capability_ids == {"cost.metering", "incident.restart"}


def test_a_license_still_cannot_grant_a_capability_the_catalog_lacks() -> None:
    unlisted = _claims(capability_ids=("incident.restart", "network.rewrite-routes"))

    entitlement = resolve_entitlement(
        catalog=_catalog(), token=_token(unlisted), verifier=_AcceptAll(), now=_NOW
    )

    assert "network.rewrite-routes" not in entitlement.available_capability_ids
