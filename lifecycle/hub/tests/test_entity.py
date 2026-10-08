"""Ownership evidence and the managed rule, without a store."""

from __future__ import annotations

from typing import Any

import pytest
from fdai_deployment_cli.lifecycle_configuration import ConfigurationValidationError

from fdai_lifecycle_hub.entity import Entity, EntitySettings, OwnershipEvidence, OwnershipGap

RECEIPT = "sha256:" + "a" * 64
STATE = "sha256:" + "b" * 64
SETTINGS = EntitySettings(overrides=({"versions": ">=1.0.0", "values": {}},))


@pytest.mark.parametrize(
    ("evidence", "gap"),
    [
        (OwnershipEvidence(managed_tag=True), OwnershipGap.TAG_ONLY),
        (OwnershipEvidence(foundation_receipt_digest=RECEIPT), OwnershipGap.UNPROVEN),
        (
            OwnershipEvidence(terraform_state_digest=STATE, managed_tag=True),
            OwnershipGap.UNPROVEN,
        ),
        (
            OwnershipEvidence(
                foundation_receipt_digest=RECEIPT,
                terraform_state_digest=STATE,
            ),
            None,
        ),
    ],
)
def test_ownership_needs_both_a_receipt_and_a_state_identity(
    evidence: OwnershipEvidence, gap: OwnershipGap | None
) -> None:
    assert evidence.gap is gap


@pytest.mark.parametrize(
    "fields",
    [{}, {"foundation_receipt_digest": "a" * 64}, {"terraform_state_digest": "sha256:short"}],
)
def test_malformed_ownership_evidence_is_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        OwnershipEvidence(**fields)


@pytest.mark.parametrize(
    "ownership",
    [
        None,
        OwnershipEvidence(managed_tag=True),
        OwnershipEvidence(foundation_receipt_digest=RECEIPT),
    ],
)
def test_settings_need_proven_ownership(ownership: OwnershipEvidence | None) -> None:
    with pytest.raises(ValueError, match="without proven ownership"):
        Entity(entity_id="core", kind="service", ownership=ownership, settings=SETTINGS)


def test_an_entity_with_settings_is_managed() -> None:
    proven = OwnershipEvidence(foundation_receipt_digest=RECEIPT, terraform_state_digest=STATE)

    assert not Entity(entity_id="core", kind="service", ownership=proven).managed
    assert Entity(entity_id="core", kind="service", ownership=proven, settings=SETTINGS).managed


def test_settings_refuse_a_literal_secret_and_allow_a_key_vault_reference() -> None:
    def settings(value: str) -> EntitySettings:
        return EntitySettings(
            overrides=({"versions": ">=1.0.0", "values": {"client_secret": value}},)
        )

    with pytest.raises(ConfigurationValidationError) as refused:
        settings("hunter2")

    assert refused.value.code == "literal_secret_value"
    assert settings("kv://example-vault/client-secret").overrides
