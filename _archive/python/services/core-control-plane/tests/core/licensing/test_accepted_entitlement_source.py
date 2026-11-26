from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.core.licensing.entitlement import (
    Entitlement,
    EntitlementSourceUnavailableError,
    LicenseEntitlementAuthority,
    LicenseStatus,
)
from fdai.core.licensing.entitlement_source import admitted_installation_entitlement
from fdai.core.licensing.token import LicenseTokenError
from fdai.delivery.trust import Ed25519LicenseVerifier
from tests.core.licensing.test_installation_entitlement import (
    _BOUND,
    _NOW,
    _catalog,
    _claims,
    _token,
)


def signed_authority() -> tuple[LicenseEntitlementAuthority, str, Ed25519PrivateKey]:
    key = Ed25519PrivateKey.generate()
    verifier = Ed25519LicenseVerifier(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    document = _claims().canonical_document()
    token = _token(document, key.sign(document))
    return (
        LicenseEntitlementAuthority(
            catalog=_catalog(), token=None, verifier=verifier, binding=_BOUND
        ),
        token,
        key,
    )


class Source:
    def __init__(self, token: str | None) -> None:
        self.token = token
        self.calls = 0

    def read(self) -> str | None:
        self.calls += 1
        return self.token


def test_every_resolution_reads_and_reverifies_current_original_bytes() -> None:
    authority, token, _key = signed_authority()
    source = Source(token)
    bound = replace(authority, token_source=source)
    assert bound.resolve(now=_NOW).status is LicenseStatus.ACTIVE
    source.token = token[:-2] + "aa"
    assert bound.resolve(now=_NOW).status is LicenseStatus.UNTRUSTED
    assert source.calls == 2


def test_missing_record_does_not_create_a_trial_or_grant() -> None:
    authority, _token_value, _key = signed_authority()
    bound = replace(authority, token_source=Source(None))
    assert bound.resolve(now=_NOW).status is LicenseStatus.ABSENT
    assert "operations.typed-mutation" not in bound.resolve(now=_NOW).available_capability_ids


def test_failed_source_does_not_fall_back_to_a_trial() -> None:
    class Failed(Source):
        def read(self) -> str | None:
            raise EntitlementSourceUnavailableError("unavailable")

    authority, _token_value, _key = signed_authority()

    class Trial:
        def resolve(self, *, now):
            pytest.fail("untrusted accepted storage must not obtain a Trial fallback")

    result = replace(authority, token_source=Failed(None), trial=Trial()).resolve(now=_NOW)
    assert result.status is LicenseStatus.UNTRUSTED
    assert "operations.typed-mutation" not in result.available_capability_ids


def test_absent_accepted_record_can_only_use_an_already_authoritative_trial() -> None:
    authority, _token_value, _key = signed_authority()

    class Trial:
        def resolve(self, *, now):
            return Entitlement(
                status=LicenseStatus.ACTIVE,
                available_capability_ids=frozenset({"operations.typed-mutation"}),
                reason="synthetic existing Trial observation",
            )

    assert (
        replace(authority, token_source=Source(None), trial=Trial()).resolve(now=_NOW).status
        is LicenseStatus.ACTIVE
    )


def test_legacy_and_accepted_sources_cannot_compete() -> None:
    authority, token, _key = signed_authority()
    with pytest.raises(ValueError, match="exclusive"):
        replace(authority, token=token, token_source=Source(token))


def test_acceptance_disables_local_issuer_and_trial_shortcuts() -> None:
    authority, token, key = signed_authority()
    bypass = replace(authority, issuer_workstation=True)
    assert admitted_installation_entitlement(token, authority=bypass, now=_NOW) == _claims()
    document = _claims(deployment_binding="f" * 64).canonical_document()
    wrong = _token(document, key.sign(document))
    with pytest.raises(LicenseTokenError, match="misbound"):
        admitted_installation_entitlement(wrong, authority=bypass, now=_NOW)


def test_acceptance_rejects_a_forged_full_grant() -> None:
    authority, _token_value, _key = signed_authority()
    document = _claims().canonical_document()
    wrong_key = Ed25519PrivateKey.generate()
    with pytest.raises(LicenseTokenError, match="untrusted"):
        admitted_installation_entitlement(
            _token(document, wrong_key.sign(document)), authority=authority, now=_NOW
        )
