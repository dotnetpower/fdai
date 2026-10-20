from __future__ import annotations

import base64
import json
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_configuration import (
    ConfigurationValidationError,
    resolve_configuration_layers,
)
from fdai_deployment_cli.lifecycle_configuration_package import (
    ConfigurationPackageInput,
    SignedConfigurationPackage,
    build_configuration_package,
    decrypt_configuration_identifiers,
    verify_configuration_package,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import (
    encryption_key_digest,
    seal_identifiers,
)


@pytest.fixture
def signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


@pytest.fixture
def installation_key() -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))


@pytest.fixture
def source() -> ConfigurationPackageInput:
    return ConfigurationPackageInput(
        revision_id="a" * 40,
        release_version="1.5.0",
        configuration_schema={
            "region": {
                "default": "eastus",
                "x-fdai-axis": "deployment-environment",
                "x-fdai-owner": "customer",
            },
            "replicas": {
                "default": 1,
                "x-fdai-axis": "deployment-environment",
                "x-fdai-owner": "customer",
            },
            "credential_ref": {
                "x-fdai-axis": "deployment-environment",
                "x-fdai-owner": "customer",
            },
        },
        environment_config={"region": "koreacentral", "credential_ref": "example-secret"},
        entity_overrides=[
            {"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}},
            {"versions": ">=1.5.0 <1.6.0", "values": {"replicas": 4}},
        ],
        sealed_values={
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "endpoint": "https://example.com",
        },
        sealed_keys=frozenset({"tenant_id", "endpoint"}),
    )


def _build(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
    history: tuple[SignedConfigurationPackage, ...] = (),
) -> SignedConfigurationPackage:
    return build_configuration_package(
        source,
        signing_key=signing_key,
        installation_key=installation_key.public_key(),
        history=history,
    )


def _verify(
    package: SignedConfigurationPackage,
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
    history: tuple[SignedConfigurationPackage, ...] = (),
) -> dict[str, object]:
    return verify_configuration_package(
        package,
        configuration_key=signing_key.public_key(),
        installation_key_digest=encryption_key_digest(installation_key.public_key()),
        configuration_schema=source.configuration_schema,
        sealed_keys=source.sealed_keys,
        history=history,
    ).values


def _resign(
    package: SignedConfigurationPackage,
    signing_key: Ed25519PrivateKey,
    **changes: object,
) -> SignedConfigurationPackage:
    document = json.loads(package.payload)
    document.update(changes)
    payload = canonical_bytes(document)
    return SignedConfigurationPackage(payload, signing_key.sign(payload))


def test_real_builder_reader_and_installation_decryption(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    package = _build(source, signing_key, installation_key)
    assert _verify(package, source, signing_key, installation_key) == {
        "region": "koreacentral",
        "replicas": 4,
        "credential_ref": "example-secret",
    }
    # The persisted bytes are exactly the signed package and have no readable identifiers.
    for value in source.sealed_values.values():
        assert isinstance(value, str)
        assert value.encode() not in package.payload
    assert (
        decrypt_configuration_identifiers(
            package,
            configuration_key=signing_key.public_key(),
            installation_key=installation_key,
            configuration_schema=source.configuration_schema,
            sealed_keys=source.sealed_keys,
        )
        == source.sealed_values
    )


def test_linear_chain_and_exact_retry_bytes(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    first = _build(source, signing_key, installation_key)
    second_source = replace(source, revision_id="b" * 40, environment_config={"region": "eastus"})
    second = _build(second_source, signing_key, installation_key, (first,))
    assert json.loads(second.payload)["predecessor_digest"] == first.digest
    assert _verify(second, source, signing_key, installation_key, (first,))["region"] == "eastus"
    assert _build(second_source, signing_key, installation_key, (first, second)) == second
    assert _verify(second, source, signing_key, installation_key, (first, second))


def test_same_revision_cannot_be_repackaged_with_changed_inputs(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    package = _build(source, signing_key, installation_key)
    changed = replace(
        source, sealed_values={**source.sealed_values, "endpoint": "https://example.org"}
    )
    with pytest.raises(ValueError, match="different inputs"):
        _build(changed, signing_key, installation_key, (package,))


def test_unsigned_tampered_and_wrong_signer_packages_are_rejected(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    package = _build(source, signing_key, installation_key)
    other = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
    for invalid in (
        replace(package, signature=b""),
        replace(package, payload=package.payload + b" "),
        replace(package, signature=other.sign(package.payload)),
    ):
        with pytest.raises(ValueError, match="signature"):
            _verify(invalid, source, signing_key, installation_key)


def test_missing_predecessor_fork_reordering_and_old_revision_cannot_be_imported(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    first = _build(source, signing_key, installation_key)
    second = _build(replace(source, revision_id="b" * 40), signing_key, installation_key, (first,))
    fork = _build(replace(source, revision_id="c" * 40), signing_key, installation_key, (first,))
    for candidate, history in (
        (second, ()),
        (fork, (first, second)),
        (first, (first, second)),
        (fork, (second, first)),
    ):
        with pytest.raises(ValueError, match="gap or fork"):
            _verify(candidate, source, signing_key, installation_key, history)
    duplicate = _resign(second, signing_key, revision_id=source.revision_id)
    with pytest.raises(ValueError, match="already imported"):
        _verify(duplicate, source, signing_key, installation_key, (first,))


@pytest.mark.parametrize("location", ["default", "environment", "override", "sealed"])
def test_secret_values_fail_before_sealing_or_signing(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
) -> None:
    def unexpected_sealing(*args: object, **kwargs: object) -> None:
        pytest.fail("secret reached encryption and could then be signed")

    monkeypatch.setattr(
        "fdai_deployment_cli.lifecycle_configuration_package.seal_identifiers", unexpected_sealing
    )
    secret_schema = {
        **source.configuration_schema,
        "password": {
            "x-fdai-axis": "deployment-environment",
            "x-fdai-owner": "customer",
            **({"default": "not-a-real-secret"} if location == "default" else {}),
        },
    }
    changed = replace(source, configuration_schema=secret_schema)
    if location == "environment":
        changed = replace(changed, environment_config={"password": "not-a-real-secret"})
    elif location == "override":
        changed = replace(
            changed,
            entity_overrides=[
                *source.entity_overrides,
                {"versions": ">=3.0.0 <4.0.0", "values": {"password": "not-a-real-secret"}},
            ],
        )
    elif location == "sealed":
        changed = replace(
            changed,
            sealed_values={"password": "not-a-real-secret"},
            sealed_keys=frozenset({"password"}),
        )
    with pytest.raises(ConfigurationValidationError) as error:
        _build(changed, signing_key, installation_key)
    assert error.value.code == "literal_secret_value"


@pytest.mark.parametrize(
    "entry",
    [
        {"x-fdai-axis": "deployment-environment"},
        {"x-fdai-axis": "standing-authority", "x-fdai-owner": "customer"},
    ],
)
def test_builder_calls_axis_and_owner_validator(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
    entry: dict[str, object],
) -> None:
    changed = replace(source, configuration_schema={"region": entry})
    with pytest.raises(ConfigurationValidationError):
        _build(changed, signing_key, installation_key)


def test_builder_holds_release_without_override_coverage(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    with pytest.raises(ConfigurationValidationError) as error:
        _build(replace(source, release_version="2.0.0"), signing_key, installation_key)
    assert error.value.code == "missing_matching_override_block"


def test_reader_does_not_trust_embedded_schema_or_sealed_key_declaration(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    package = _build(source, signing_key, installation_key)
    with pytest.raises(ValueError, match="trusted Release schema"):
        _verify(package, replace(source, configuration_schema={}), signing_key, installation_key)
    with pytest.raises(ValueError, match="trusted Release keys"):
        _verify(package, replace(source, sealed_keys=frozenset()), signing_key, installation_key)
    with pytest.raises(ValueError, match="trusted sealed keys"):
        _build(replace(source, sealed_values={}), signing_key, installation_key)


def test_wrong_installation_and_tampered_ciphertext_cannot_decrypt(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    package = _build(source, signing_key, installation_key)
    wrong_key = X25519PrivateKey.from_private_bytes(b"\x02" * 32)
    with pytest.raises(ValueError, match="another installation"):
        _verify(package, source, signing_key, wrong_key)
    document = json.loads(package.payload)
    ciphertext = base64.b64decode(document["sealed"]["ciphertext"])
    document["sealed"]["ciphertext"] = base64.b64encode(
        bytes([ciphertext[0] ^ 1]) + ciphertext[1:]
    ).decode("ascii")
    changed = _resign(package, signing_key, sealed=document["sealed"])
    with pytest.raises(ValueError, match="authentication failed"):
        decrypt_configuration_identifiers(
            changed,
            configuration_key=signing_key.public_key(),
            installation_key=installation_key,
            configuration_schema=source.configuration_schema,
            sealed_keys=source.sealed_keys,
        )


@pytest.mark.parametrize(
    "payload",
    [
        b'{"format":1,"format":2}',
        b'{"value":NaN}',
        b"[]",
        b"\xff",
    ],
)
def test_reader_rejects_signed_malformed_json_without_echoing_payload(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
    payload: bytes,
) -> None:
    package = SignedConfigurationPackage(payload, signing_key.sign(payload))
    with pytest.raises(ValueError, match="JSON"):
        _verify(package, source, signing_key, installation_key)


def test_builder_rejects_nonfinite_input_before_encryption(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    with pytest.raises(ValueError, match="JSON"):
        _build(
            replace(source, environment_config={"replicas": float("nan")}),
            signing_key,
            installation_key,
        )


def test_sealed_default_cannot_escape_into_resolved_configuration() -> None:
    schema: dict[str, object] = {
        "tenant_id": {
            "default": "00000000-0000-0000-0000-000000000000",
            "x-fdai-axis": "deployment-environment",
            "x-fdai-owner": "customer",
        }
    }
    with pytest.raises(ConfigurationValidationError, match="sealed section"):
        resolve_configuration_layers(
            release_version="1.5.0",
            configuration_schema=schema,
            environment_config={},
            entity_overrides=[{"versions": ">=1.0.0 <2.0.0", "values": {}}],
            sealed_keys={"tenant_id"},
        )


def test_exact_version_with_redundant_bound_remains_most_specific(
    source: ConfigurationPackageInput,
) -> None:
    resolution = resolve_configuration_layers(
        release_version=source.release_version,
        configuration_schema=source.configuration_schema,
        environment_config={},
        entity_overrides=[
            {"versions": "=1.5.0 <2.0.0", "values": {"replicas": 8}},
            {"versions": ">=1.5.0 <1.6.0", "values": {"replicas": 4}},
        ],
    )
    assert resolution.values["replicas"] == 8


def test_equivalent_override_intervals_are_ambiguous(source: ConfigurationPackageInput) -> None:
    with pytest.raises(ConfigurationValidationError) as error:
        resolve_configuration_layers(
            release_version=source.release_version,
            configuration_schema=source.configuration_schema,
            environment_config={},
            entity_overrides=[
                {"versions": ">=1.0.0 <2.0.0", "values": {"replicas": 2}},
                {"versions": "<2.0.0 >=1.0.0", "values": {"replicas": 4}},
            ],
        )
    assert error.value.code == "duplicate_override_range"


@pytest.mark.parametrize(
    "changes",
    [
        {"format": "unsupported"},
        {"revision_id": "short"},
        {"release_version": 1},
        {"input_digest": "invalid"},
        {"predecessor_digest": "invalid"},
        {"sealed_keys": "invalid"},
        {"sealed_keys": ["endpoint", "endpoint"]},
        {"configuration": []},
        {"configuration": {}},
    ],
)
def test_signed_invalid_manifest_is_rejected(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
    changes: dict[str, object],
) -> None:
    package = _build(source, signing_key, installation_key)
    with pytest.raises(ValueError):
        _verify(_resign(package, signing_key, **changes), source, signing_key, installation_key)


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": "unexpected"},
        {"algorithm": "unsupported"},
        {"recipient_digest": "0" * 64},
        {"ephemeral_key": 42},
        {"ephemeral_key": "%%%"},
        {"nonce": ""},
        {"ciphertext": ""},
    ],
)
def test_signed_invalid_sealing_envelope_is_rejected(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
    changes: dict[str, object],
) -> None:
    package = _build(source, signing_key, installation_key)
    envelope = json.loads(package.payload)["sealed"]
    envelope.update(changes)
    with pytest.raises(ValueError, match="sealed identifier"):
        _verify(
            _resign(package, signing_key, sealed=envelope), source, signing_key, installation_key
        )


def test_reader_rejects_noncanonical_signed_json(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    package = _build(source, signing_key, installation_key)
    payload = json.dumps(json.loads(package.payload), indent=2).encode()
    with pytest.raises(ValueError, match="canonical"):
        _verify(
            SignedConfigurationPackage(payload, signing_key.sign(payload)),
            source,
            signing_key,
            installation_key,
        )


def test_package_size_is_bounded_on_build_and_read(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    large = replace(source, sealed_values={**source.sealed_values, "endpoint": "x" * (1024 * 1024)})
    with pytest.raises(ValueError, match="size limit"):
        _build(large, signing_key, installation_key)
    oversized = SignedConfigurationPackage(b" " * (1024 * 1024 + 1), b"x" * 64)
    with pytest.raises(ValueError, match="size limit"):
        _verify(oversized, source, signing_key, installation_key)


@pytest.mark.parametrize(
    "overrides",
    [
        "invalid",
        [{"versions": ">=1.0.0 <2.0.0", "values": {}, "extra": "unexpected"}],
    ],
)
def test_reader_rejects_invalid_override_shapes(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
    overrides: object,
) -> None:
    package = _build(source, signing_key, installation_key)
    configuration = json.loads(package.payload)["configuration"]
    configuration["entity_overrides"] = overrides
    with pytest.raises(ValueError, match="override"):
        _verify(
            _resign(package, signing_key, configuration=configuration),
            source,
            signing_key,
            installation_key,
        )


def test_nested_identifiers_cannot_escape_in_public_layers(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    nested = replace(
        source, environment_config={"region": [{"tenant_id": source.sealed_values["tenant_id"]}]}
    )
    with pytest.raises(ValueError, match="sealed section"):
        _build(nested, signing_key, installation_key)


def test_decryption_rejects_low_order_ephemeral_key(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
) -> None:
    package = _build(source, signing_key, installation_key)
    envelope = json.loads(package.payload)["sealed"]
    envelope["ephemeral_key"] = base64.b64encode(bytes(32)).decode("ascii")
    with pytest.raises(ValueError, match="encryption key"):
        decrypt_configuration_identifiers(
            _resign(package, signing_key, sealed=envelope),
            configuration_key=signing_key.public_key(),
            installation_key=installation_key,
            configuration_schema=source.configuration_schema,
            sealed_keys=source.sealed_keys,
        )


@pytest.mark.parametrize("mismatch", ["keys", "digest"])
def test_decryption_checks_plaintext_keys_and_content_digest(
    source: ConfigurationPackageInput,
    signing_key: Ed25519PrivateKey,
    installation_key: X25519PrivateKey,
    mismatch: str,
) -> None:
    package = _build(source, signing_key, installation_key)
    document = json.loads(package.payload)
    document.pop("sealed")
    values = source.sealed_values
    if mismatch == "keys":
        values = {"unexpected": "example"}
    else:
        document["input_digest"] = "0" * 64
    document["sealed"] = seal_identifiers(
        values, installation_key.public_key(), context=canonical_bytes(document)
    )
    payload = canonical_bytes(document)
    with pytest.raises(ValueError, match="keys do not match|digest does not match"):
        decrypt_configuration_identifiers(
            SignedConfigurationPackage(payload, signing_key.sign(payload)),
            configuration_key=signing_key.public_key(),
            installation_key=installation_key,
            configuration_schema=source.configuration_schema,
            sealed_keys=source.sealed_keys,
        )
