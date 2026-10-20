from __future__ import annotations

import copy
from dataclasses import dataclass, replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_configuration import ConfigurationValidationError
from fdai_deployment_cli.lifecycle_configuration_document import configuration_object
from fdai_deployment_cli.lifecycle_configuration_entities import (
    EntityConfigurationInput,
    InstallationConfigurationInput,
    InstallationLayerResolution,
)
from fdai_deployment_cli.lifecycle_configuration_package import (
    ConfigurationPackageInput,
    SignedConfigurationPackage,
    build_configuration_package,
    build_installation_configuration_package,
    decrypt_installation_configuration_identifiers,
    verify_configuration_package,
    verify_installation_configuration_package,
)
from fdai_deployment_cli.lifecycle_configuration_sealing import (
    encryption_key_digest,
    read_object,
    seal_identifiers,
)

FIRST = "1" * 64
SECOND = "2" * 64
ENTITIES = frozenset({FIRST, SECOND})


@dataclass
class RevisionCase:
    source: InstallationConfigurationInput
    signing: Ed25519PrivateKey
    recipient: X25519PrivateKey

    def build(
        self,
        source: InstallationConfigurationInput | None = None,
        history: tuple[SignedConfigurationPackage, ...] = (),
    ) -> SignedConfigurationPackage:
        return build_installation_configuration_package(
            source or self.source,
            entity_ids=ENTITIES,
            signing_key=self.signing,
            installation_key=self.recipient.public_key(),
            history=history,
        )

    def verify(
        self,
        package: SignedConfigurationPackage,
        history: tuple[SignedConfigurationPackage, ...] = (),
        source: InstallationConfigurationInput | None = None,
        entity_ids: frozenset[str] = ENTITIES,
    ) -> InstallationLayerResolution:
        expected = source or self.source
        return verify_installation_configuration_package(
            package,
            configuration_key=self.signing.public_key(),
            installation_key_digest=encryption_key_digest(self.recipient.public_key()),
            configuration_schema=expected.configuration_schema,
            sealed_keys=expected.sealed_keys,
            entity_ids=entity_ids,
            release_version=expected.release_version,
            release_digest=expected.release_digest,
            history=history,
        )

    def decrypt(self, package: SignedConfigurationPackage, entity_id: str) -> dict[str, object]:
        return decrypt_installation_configuration_identifiers(
            package,
            entity_id=entity_id,
            configuration_key=self.signing.public_key(),
            installation_key=self.recipient,
            configuration_schema=self.source.configuration_schema,
            sealed_keys=self.source.sealed_keys,
            entity_ids=ENTITIES,
            release_version=self.source.release_version,
            release_digest=self.source.release_digest,
        )

    def resign(self, document: dict[str, object]) -> SignedConfigurationPackage:
        payload = canonical_bytes(document)
        return SignedConfigurationPackage(payload, self.signing.sign(payload))


@pytest.fixture
def revision() -> RevisionCase:
    schema = {
        key: {
            "x-fdai-axis": "deployment-environment",
            "x-fdai-owner": "customer",
            **({"default": default} if default is not None else {}),
        }
        for key, default in (("region", "eastus"), ("replicas", 1), ("credential_ref", None))
    }
    return RevisionCase(
        InstallationConfigurationInput(
            revision_id="a" * 40,
            release_version="1.5.0",
            release_digest="f" * 64,
            configuration_schema=schema,
            environment_config={"region": "koreacentral", "credential_ref": "common-secret"},
            sealed_values={"tenant_id": "00000000-0000-0000-0000-000000000000"},
            sealed_keys=frozenset({"tenant_id", "endpoint"}),
            entities=(
                EntityConfigurationInput(
                    entity_id=SECOND,
                    entity_overrides=({"versions": ">=1.0.0 <2.0.0", "values": {}},),
                    sealed_values={"endpoint": "https://example.com/second-private-identifier"},
                ),
                EntityConfigurationInput(
                    entity_id=FIRST,
                    entity_overrides=(
                        {
                            "versions": ">=1.0.0 <2.0.0",
                            "values": {"replicas": 2, "credential_ref": "first-secret"},
                        },
                        {
                            "versions": ">=1.5.0 <1.6.0",
                            "values": {"replicas": 4, "credential_ref": "first-secret"},
                        },
                    ),
                    sealed_values={"endpoint": "https://example.com/first-private-identifier"},
                ),
            ),
        ),
        Ed25519PrivateKey.generate(),
        X25519PrivateKey.generate(),
    )


def test_full_producer_reader_decryption_and_deterministic_retry(revision: RevisionCase) -> None:
    package = revision.build()
    resolved = revision.verify(package)
    assert resolved.release_version == "1.5.0"
    assert list(resolved.entities) == [FIRST, SECOND]
    assert resolved.entities[FIRST].values == {
        "region": "koreacentral",
        "replicas": 4,
        "credential_ref": "first-secret",
    }
    assert resolved.entities[SECOND].values == {
        "region": "koreacentral",
        "replicas": 1,
        "credential_ref": "common-secret",
    }
    for entity in revision.source.entities:
        assert revision.decrypt(package, entity.entity_id) == {
            **revision.source.sealed_values,
            **entity.sealed_values,
        }
        for value in entity.sealed_values.values():
            assert isinstance(value, str) and value.encode() not in package.payload
    assert b"00000000-0000-0000-0000-000000000000" not in package.payload
    reordered = replace(revision.source, entities=tuple(reversed(revision.source.entities)))
    assert revision.build(reordered, (package,)) == package
    assert revision.verify(package, (package,)) == resolved
    resolved.entities[FIRST].values["region"] = "changed"
    assert revision.verify(package).entities[SECOND].values["region"] == "koreacentral"


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "duplicate",
        "extra",
        "plaintext-id",
        "missing-override",
        "unknown-key",
        "duplicate-range",
        "ambiguous-range",
        "secret",
        "identifier-public",
        "sealed-missing",
        "sealed-extra",
        "sealed-secret",
    ],
)
def test_any_bad_entity_blocks_the_complete_revision(revision: RevisionCase, problem: str) -> None:
    source = copy.deepcopy(revision.source)
    entities = list(source.entities)
    second = entities[0]
    if problem == "missing":
        entities.pop()
    elif problem == "duplicate":
        entities.append(second)
    elif problem == "extra":
        entities.append(replace(second, entity_id="3" * 64))
    elif problem == "plaintext-id":
        entities[0] = replace(second, entity_id="example-customer-resource")
    elif problem == "sealed-missing":
        entities[0] = replace(second, sealed_values={})
    elif problem == "sealed-extra":
        entities[0] = replace(second, sealed_values={**second.sealed_values, "extra": "value"})
    elif problem == "sealed-secret":
        source = replace(source, sealed_keys=source.sealed_keys | {"password"})
        entities[0] = replace(second, sealed_values={**second.sealed_values, "password": "literal"})
    else:
        blocks: tuple[dict[str, object], ...]
        if problem == "missing-override":
            blocks = ({"versions": ">=2.0.0 <3.0.0", "values": {}},)
        elif problem == "duplicate-range":
            blocks = (
                {"versions": ">=1.0.0 <2.0.0", "values": {}},
                {"versions": "<2.0.0 >=1.0.0", "values": {}},
            )
        elif problem == "ambiguous-range":
            blocks = (
                {"versions": ">=1.0.0 <1.6.0", "values": {}},
                {"versions": ">=1.4.0 <2.0.0", "values": {}},
            )
        else:
            key = {"secret": "password", "identifier-public": "endpoint"}.get(problem, "unknown")
            blocks = (
                {"versions": ">=1.0.0 <2.0.0", "values": {}},
                {"versions": ">=2.0.0 <3.0.0", "values": {key: "not-allowed"}},
            )
        entities[0] = replace(second, entity_overrides=blocks)
    with pytest.raises(ValueError):
        revision.build(replace(source, entities=tuple(entities)))


@pytest.mark.parametrize(
    "selection", [frozenset(), frozenset({FIRST}), frozenset({FIRST, "3" * 64})]
)
def test_independent_selection_is_not_taken_from_package(
    revision: RevisionCase, selection: frozenset[str]
) -> None:
    with pytest.raises(ValueError):
        revision.verify(revision.build(), entity_ids=selection)


@pytest.mark.parametrize("problem", ["schema", "version", "release-digest", "classification"])
def test_independent_release_inputs_are_required(revision: RevisionCase, problem: str) -> None:
    package = revision.build()
    source = revision.source
    if problem == "schema":
        source = replace(source, configuration_schema={})
    elif problem == "version":
        source = replace(source, release_version="1.5.1")
    elif problem == "release-digest":
        source = replace(source, release_digest="e" * 64)
    else:
        source = replace(source, sealed_keys=frozenset({"endpoint"}))
    with pytest.raises(ValueError):
        revision.verify(package, source=source)


@pytest.mark.parametrize("problem", ["payload", "signature", "unsigned", "key", "recipient"])
def test_tamper_and_wrong_keys_fail_closed(revision: RevisionCase, problem: str) -> None:
    package = revision.build()
    if problem == "payload":
        package = replace(package, payload=package.payload.replace(b"koreacentral", b"eastus"))
    elif problem == "signature":
        package = replace(package, signature=b"\0" * 64)
    elif problem == "unsigned":
        package = replace(package, signature=b"")
    elif problem == "key":
        revision.signing = Ed25519PrivateKey.generate()
    else:
        revision.recipient = X25519PrivateKey.generate()
    with pytest.raises(ValueError):
        revision.verify(package)


@pytest.mark.parametrize("problem", ["reorder", "duplicate", "substitute", "schema", "extra-field"])
def test_even_resigned_invalid_documents_are_refused(revision: RevisionCase, problem: str) -> None:
    document = read_object(revision.build().payload)
    configuration = configuration_object(document["configuration"])
    entries = configuration["entities"]
    assert isinstance(entries, list)
    if problem == "reorder":
        entries.reverse()
    elif problem == "duplicate":
        entries.append(entries[0])
    elif problem == "substitute":
        entries[0] = {**configuration_object(entries[0]), "entity_id": "3" * 64}
    elif problem == "schema":
        configuration["schema"] = {}
    else:
        document["extra"] = True
    document["configuration"] = configuration
    with pytest.raises(ValueError):
        revision.verify(revision.resign(document))


def test_resigned_cross_entity_ciphertext_context_is_not_reusable(revision: RevisionCase) -> None:
    original = revision.build()
    other_source = replace(
        revision.source,
        revision_id="b" * 40,
        entities=tuple(
            replace(entity, entity_id=SECOND if entity.entity_id == FIRST else FIRST)
            for entity in revision.source.entities
        ),
    )
    other = revision.build(other_source)
    document = read_object(original.payload)
    document["sealed"] = read_object(other.payload)["sealed"]
    with pytest.raises(ValueError, match="authentication"):
        revision.decrypt(revision.resign(document), FIRST)
    with pytest.raises(ValueError, match="not selected"):
        revision.decrypt(original, "3" * 64)


def test_revision_history_forks_replay_and_retry(revision: RevisionCase) -> None:
    first = revision.build()
    next_source = replace(revision.source, revision_id="b" * 40)
    second = revision.build(next_source, (first,))
    third_source = replace(revision.source, revision_id="c" * 40)
    third = revision.build(third_source, (first, second))
    fork = revision.build(third_source, (first,))
    assert revision.verify(third, (first, second))
    assert revision.build(next_source, (first, second)) == second
    with pytest.raises(ValueError):
        revision.build(revision.source, (first, second))
    with pytest.raises(ValueError):
        revision.build(replace(next_source, environment_config={}), (first, second))
    for package, history in (
        (fork, (first, second)),
        (third, (second,)),
        (third, (second, first)),
        (third, ()),
        (first, (first, second)),
        (third, (first, first)),
    ):
        with pytest.raises(ValueError):
            revision.verify(package, history)


def test_legacy_chain_and_readers_remain_explicit(revision: RevisionCase) -> None:
    source = revision.source
    legacy = build_configuration_package(
        ConfigurationPackageInput(
            revision_id="0" * 40,
            release_version=source.release_version,
            configuration_schema=source.configuration_schema,
            environment_config=source.environment_config,
            entity_overrides=source.entities[0].entity_overrides,
            sealed_values={**source.sealed_values, **source.entities[0].sealed_values},
            sealed_keys=source.sealed_keys,
        ),
        signing_key=revision.signing,
        installation_key=revision.recipient.public_key(),
    )
    package = revision.build(history=(legacy,))
    assert revision.verify(package, (legacy,))
    assert (
        verify_configuration_package(
            legacy,
            configuration_key=revision.signing.public_key(),
            installation_key_digest=encryption_key_digest(revision.recipient.public_key()),
            configuration_schema=source.configuration_schema,
            sealed_keys=source.sealed_keys,
        ).values["replicas"]
        == 1
    )
    with pytest.raises(ValueError, match="single-Entity"):
        verify_configuration_package(
            revision.build(),
            configuration_key=revision.signing.public_key(),
            installation_key_digest=encryption_key_digest(revision.recipient.public_key()),
            configuration_schema=source.configuration_schema,
            sealed_keys=source.sealed_keys,
        )
    with pytest.raises(ValueError, match="format"):
        revision.verify(legacy)


@pytest.mark.parametrize(
    "field,value",
    [("release_digest", "invalid"), ("revision_id", "short"), ("release_version", "latest")],
)
def test_invalid_release_and_revision_identity(
    revision: RevisionCase, field: str, value: str
) -> None:
    source = revision.source
    if field == "release_digest":
        source = replace(source, release_digest=value)
    elif field == "revision_id":
        source = replace(source, revision_id=value)
    else:
        source = replace(source, release_version=value)
    with pytest.raises(ValueError):
        revision.build(source)


def test_ambiguity_has_a_stable_reason(revision: RevisionCase) -> None:
    entity = replace(
        revision.source.entities[0],
        entity_overrides=(
            {"versions": ">=1.0.0 <1.6.0", "values": {}},
            {"versions": ">=1.4.0 <2.0.0", "values": {}},
        ),
    )
    with pytest.raises(ConfigurationValidationError) as error:
        revision.build(replace(revision.source, entities=(entity, revision.source.entities[1])))
    assert error.value.code == "ambiguous_override_range"


@pytest.mark.parametrize(
    "problem",
    ["fields", "not-array", "empty", "too-many", "entity-fields", "entity-not-object"],
)
def test_signed_malformed_entity_containers_are_not_admitted(
    revision: RevisionCase, problem: str
) -> None:
    document = read_object(revision.build().payload)
    configuration = configuration_object(document["configuration"])
    if problem == "fields":
        configuration["unexpected"] = None
    elif problem == "not-array":
        configuration["entities"] = {}
    elif problem == "empty":
        configuration["entities"] = []
    elif problem == "too-many":
        configuration["entities"] = [{}] * 257
    elif problem == "entity-fields":
        configuration["entities"] = [{"entity_id": FIRST}]
    else:
        configuration["entities"] = [1]
    document["configuration"] = configuration
    with pytest.raises(ValueError):
        revision.verify(revision.resign(document))


@pytest.mark.parametrize("problem", ["empty", "too-many", "common-extra", "overwritten-secret"])
def test_unused_or_oversized_private_inputs_cannot_bypass_checks(
    revision: RevisionCase, problem: str
) -> None:
    source = revision.source
    if problem == "empty":
        source = replace(source, entities=())
    elif problem == "too-many":
        source = replace(source, entities=tuple(source.entities[0] for _ in range(257)))
    elif problem == "common-extra":
        source = replace(source, sealed_values={**source.sealed_values, "extra": "value"})
    else:
        source = replace(
            source,
            sealed_keys=source.sealed_keys | {"password"},
            sealed_values={**source.sealed_values, "password": "literal"},
            entities=tuple(
                replace(
                    entity, sealed_values={**entity.sealed_values, "password": {"kv_secret": "x"}}
                )
                for entity in source.entities
            ),
        )
    with pytest.raises(ValueError):
        revision.build(source)


def test_history_bound_and_resigned_bad_release_digest(revision: RevisionCase) -> None:
    package = revision.build()
    with pytest.raises(ValueError, match="history exceeds"):
        revision.verify(package, (package,) * 257)
    document = read_object(package.payload)
    document["release_digest"] = "invalid"
    with pytest.raises(ValueError, match="manifest digest"):
        revision.verify(revision.resign(document))


@pytest.mark.parametrize("problem", ["missing-entity", "wrong-keys", "not-object"])
def test_installation_decryption_checks_complete_sealed_entity_mapping(
    revision: RevisionCase, problem: str
) -> None:
    document = read_object(revision.build().payload)
    values: dict[str, object] = {
        entity.entity_id: {**revision.source.sealed_values, **entity.sealed_values}
        for entity in revision.source.entities
    }
    if problem == "missing-entity":
        del values[SECOND]
    elif problem == "wrong-keys":
        values[SECOND] = {}
    else:
        values[SECOND] = 1
    document.pop("sealed")
    inputs = {
        "configuration": document["configuration"],
        "release_version": document["release_version"],
        "release_digest": document["release_digest"],
        "installation_key_digest": document["installation_key_digest"],
        "sealed_keys": document["sealed_keys"],
        "sealed_values": values,
    }
    document["input_digest"] = canonical_digest(inputs)
    document["sealed"] = seal_identifiers(
        values, revision.recipient.public_key(), context=canonical_bytes(document)
    )
    with pytest.raises(ValueError):
        revision.decrypt(revision.resign(document), FIRST)
