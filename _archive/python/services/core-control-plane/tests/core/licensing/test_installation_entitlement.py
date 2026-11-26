"""Installation entitlement contract and resolution tests.

The entitlement has no validity window, so its exact bindings and its domain
separation from the v1 token and the integrity manifest are its only limits.
"""

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
    INSTALLATION_ENTITLEMENT_SCHEMA,
    DeploymentBinding,
    Entitlement,
    InstallationEntitlementClaims,
    LicenseClaims,
    LicenseEntitlementAuthority,
    LicenseStatus,
    LicenseTokenError,
    encode_license_token,
    parse_installation_entitlement,
    parse_license_token,
    resolve_entitlement,
)

_NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
_INSTALLATION = "1" * 64
_DEPLOYMENT = "2" * 64
_SIGNATURE = b"s" * 64
_BOUND = DeploymentBinding(
    distribution_id="fdai-upstream",
    tenant_binding=_DEPLOYMENT,
    installation_binding=_INSTALLATION,
)


class _ExactSignature:
    def verify(self, document: bytes, signature: bytes) -> bool:
        return signature == _SIGNATURE


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog(
        (
            Capability(
                capability_id="observability.resource-discovery",
                name="Resource discovery",
                category=CapabilityCategory.DETECTION,
                summary="Read resources.",
                side_effect_class=SideEffectClass.READ,
            ),
            Capability(
                capability_id="operations.typed-mutation",
                name="Typed mutation",
                category=CapabilityCategory.REMEDIATION,
                summary="Run governed changes.",
                side_effect_class=SideEffectClass.EXECUTE,
            ),
        )
    )


def _claims(**overrides: object) -> InstallationEntitlementClaims:
    values: dict[str, object] = {
        "entitlement_id": "ent-0001",
        "distribution_id": "fdai-upstream",
        "installation_binding": _INSTALLATION,
        "deployment_binding": _DEPLOYMENT,
        "issued_at": _NOW,
    }
    values.update(overrides)
    return InstallationEntitlementClaims(**values)  # type: ignore[arg-type]


def _token(document: bytes, signature: bytes = _SIGNATURE) -> str:
    return encode_license_token(document, signature)


def _resolve(token: str, binding: DeploymentBinding = _BOUND, now: datetime = _NOW) -> Entitlement:
    return resolve_entitlement(
        catalog=_catalog(),
        token=token,
        verifier=_ExactSignature(),
        now=now,
        binding=binding,
        require_license=True,
    )


def test_a_canonical_entitlement_round_trips() -> None:
    claims = _claims()

    parsed, document, signature = parse_installation_entitlement(
        _token(claims.canonical_document())
    )

    assert parsed == claims
    assert document == claims.canonical_document()
    assert signature == _SIGNATURE
    assert json.loads(document)["schema_version"] == INSTALLATION_ENTITLEMENT_SCHEMA
    assert json.loads(document)["issued_at"] == "2026-10-01T09:00:00Z"


@pytest.mark.parametrize(
    "overrides",
    [
        {"entitlement_id": "ENT"},
        {"distribution_id": ""},
        {"installation_binding": "A" * 64},
        {"deployment_binding": "2" * 63},
        {"issued_at": datetime(2026, 10, 1, 9, 0)},
    ],
)
def test_invalid_claims_are_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(LicenseTokenError):
        _claims(**overrides)


def _document(**changes: object) -> bytes:
    payload = json.loads(_claims().canonical_document())
    payload.update(changes)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


@pytest.mark.parametrize(
    "document",
    [
        _document(not_after="2026-10-31T09:00:00Z"),
        _document(image_digest=None),
        _document(capability_ids=["operations.typed-mutation"]),
        json.dumps(json.loads(_claims().canonical_document()), sort_keys=True).encode(),
        _document(issued_at="2026-10-01T18:00:00+09:00"),
        _document(schema_version="fdai.installation-entitlement.v2"),
    ],
)
def test_noncanonical_or_extended_documents_are_refused(document: bytes) -> None:
    with pytest.raises(LicenseTokenError):
        parse_installation_entitlement(_token(document))


def test_each_signed_domain_is_refused_by_the_other_parser() -> None:
    v1 = LicenseClaims(
        license_id="lic-0001",
        distribution_id="fdai-upstream",
        capability_ids=("operations.typed-mutation",),
        not_before=_NOW - timedelta(days=1),
        not_after=_NOW + timedelta(days=1),
    )
    manifest = json.dumps(
        {"version": 1, "algorithm": "sha256", "file_count": 0, "files": {}},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    with pytest.raises(LicenseTokenError):
        parse_installation_entitlement(_token(v1.canonical_document()))
    with pytest.raises(LicenseTokenError):
        parse_installation_entitlement(_token(manifest))
    with pytest.raises(LicenseTokenError):
        parse_license_token(_token(_claims().canonical_document()))


def test_an_exactly_bound_entitlement_grants_the_catalog_without_expiry() -> None:
    token = _token(_claims().canonical_document())

    for moment in (_NOW, _NOW + timedelta(days=31), _NOW + timedelta(days=3650)):
        entitlement = _resolve(token, now=moment)
        assert entitlement.status is LicenseStatus.ACTIVE
        assert entitlement.available_capability_ids == {
            "observability.resource-discovery",
            "operations.typed-mutation",
        }
        assert entitlement.license_id == "ent-0001"
        assert entitlement.not_after is None


@pytest.mark.parametrize(
    ("binding", "reason"),
    [
        (DeploymentBinding("other-distro", None, _DEPLOYMENT, _INSTALLATION), "distribution"),
        (DeploymentBinding("fdai-upstream", None, _DEPLOYMENT, "3" * 64), "installation"),
        (DeploymentBinding("fdai-upstream", None, _DEPLOYMENT, None), "installation"),
        (DeploymentBinding("fdai-upstream", None, "4" * 64, _INSTALLATION), "deployment"),
        (DeploymentBinding("fdai-upstream", None, None, _INSTALLATION), "deployment"),
    ],
)
def test_any_binding_mismatch_is_misbound_and_read_only(
    binding: DeploymentBinding, reason: str
) -> None:
    entitlement = _resolve(_token(_claims().canonical_document()), binding=binding)

    assert entitlement.status is LicenseStatus.MISBOUND
    assert entitlement.available_capability_ids == {"observability.resource-discovery"}
    assert entitlement.reason is not None and reason in entitlement.reason


def test_an_unverified_or_malformed_entitlement_is_untrusted() -> None:
    document = _claims().canonical_document()

    forged = _resolve(_token(document, b"x" * 64))
    malformed = _resolve(
        f"{base64.urlsafe_b64encode(_document(extra='x')).rstrip(b'=').decode()}."
        f"{base64.urlsafe_b64encode(_SIGNATURE).rstrip(b'=').decode()}"
    )

    for entitlement in (forged, malformed):
        assert entitlement.status is LicenseStatus.UNTRUSTED
        assert entitlement.available_capability_ids == {"observability.resource-discovery"}


class _TrialMustNotBeConsulted:
    def resolve(self, *, now: datetime) -> Entitlement:
        raise AssertionError("an entitlement decision consulted the Trial")


@pytest.mark.parametrize(
    ("binding", "status"),
    [(_BOUND, LicenseStatus.ACTIVE), (DeploymentBinding("fdai-upstream"), LicenseStatus.MISBOUND)],
)
def test_the_trial_never_overrides_an_entitlement_decision(
    binding: DeploymentBinding, status: LicenseStatus
) -> None:
    authority = LicenseEntitlementAuthority(
        catalog=_catalog(),
        token=_token(_claims().canonical_document()),
        verifier=_ExactSignature(),
        binding=binding,
        trial=_TrialMustNotBeConsulted(),
    )

    assert authority.resolve(now=_NOW).status is status
