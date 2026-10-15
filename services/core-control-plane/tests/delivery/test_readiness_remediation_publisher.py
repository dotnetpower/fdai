from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fdai.core.executor.action_builder import ActionBuilder
from fdai.delivery.readiness_remediation import EventBusReadinessRemediationPublisher
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import Event, Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.event_bus import EventEnvelope, PublishReceipt
from fdai.shared.providers.readiness import RemediationProposalBinding
from fdai_service_contracts.readiness_remediation import (
    READINESS_REMEDIATION_REQUEST_TOPIC,
    ReadinessRemediationRequest,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


class _Bus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, Mapping[str, Any]]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        self.published.append((topic, key, payload))
        return PublishReceipt(topic=topic, partition=0, offset=1)

    def subscribe(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        raise AssertionError("publisher MUST NOT subscribe")

    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        raise AssertionError("publisher MUST NOT dead-letter")


def _rule(*, remediates: str = "remediate.tag-add") -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": "readiness.owner-tag.required",
            "version": "1.0.0",
            "source": "custom",
            "severity": "high",
            "category": "config_drift",
            "resource_type": "storage-account",
            "check_logic": {"kind": "expression", "reference": "owner-tag-required"},
            "remediation": {"template_ref": "owner-tag"},
            "remediates": remediates,
            "parameters": {},
            "provenance": {
                "source_url": "https://fdai.dev/operational-readiness",
                "resolved_ref": "runtime-v1",
                "content_hash": "sha256:runtime-owner-tag-v1",
                "license": "LicenseRef-runtime",
                "redistribution": "embeddable",
                "retrieved_at": "2026-10-15T00:00:00Z",
            },
        }
    )


def _proposal() -> dict[str, object]:
    return {
        "kind": "operational_readiness.remediation_proposal",
        "action_type": "remediate.tag-add",
        "resource_ref": "resource:storage/account/example",
        "scope": "rg-example",
        "target_environment": "prod",
        "submitter": "handoff-owner",
        "approver": "operations-approver",
        "approved_at": "2026-10-15T00:00:00+00:00",
        "evidence": "readiness.owner-tag.required",
        "severity": "high",
        "blocking": True,
        "idempotency_key": "orr-remediation:" + "a" * 32,
        "transfer_id": "corr-orr-remediation",
        "dimension": "identity_rbac",
        "control_id": None,
        "mode": "shadow",
    }


async def test_publisher_emits_action_builder_accepted_typed_request() -> None:
    action_type = next(
        item
        for item in load_action_type_catalog(
            REPO_ROOT / "rule-catalog" / "action-types",
            schema_registry=PackageResourceSchemaRegistry(),
        )
        if item.name == "remediate.tag-add"
    )
    release = build_ontology_release(action_types=(action_type,))
    rule = _rule()
    bus = _Bus()
    publisher = EventBusReadinessRemediationPublisher(
        event_bus=bus,
        target_revision=release.digest,
        rules_by_id={rule.id: rule},
        clock=lambda: datetime(2026, 10, 15, tzinfo=UTC),
    )

    await publisher.publish_remediation_proposal(_proposal())

    topic, key, payload = bus.published[0]
    assert topic == READINESS_REMEDIATION_REQUEST_TOPIC
    assert key == "resource:storage/account/example"
    event = Event.model_validate(payload)
    request = ReadinessRemediationRequest.model_validate(
        event.payload["readiness_remediation_request"]
    )
    assert request.target_revision == release.digest
    assert request.citing_rule_ids == (rule.id,)
    assert request.execution_authority is False
    action, _ = ActionBuilder(
        action_types_by_name={action_type.name: action_type},
        ontology_release=release,
        rules_by_id={rule.id: rule},
    ).build_from_readiness_remediation(event=event)
    assert action.idempotency_key == request.request_id


async def test_publisher_rejects_unknown_or_mismatched_rule() -> None:
    proposal = _proposal()
    bus = _Bus()
    publisher = EventBusReadinessRemediationPublisher(
        event_bus=bus,
        target_revision="sha256:" + "a" * 64,
        rules_by_id={},
    )

    with pytest.raises(ValueError, match="unknown rule"):
        await publisher.publish_remediation_proposal(proposal)

    wrong_rule = _rule(remediates="remediate.tag-remove")
    publisher = EventBusReadinessRemediationPublisher(
        event_bus=bus,
        target_revision="sha256:" + "a" * 64,
        rules_by_id={wrong_rule.id: wrong_rule},
    )
    with pytest.raises(ValueError, match="does not remediate"):
        await publisher.publish_remediation_proposal(proposal)
    assert bus.published == []


async def test_publisher_rejects_non_proposal_payload_and_invalid_revision() -> None:
    rule = _rule()
    bus = _Bus()
    publisher = EventBusReadinessRemediationPublisher(
        event_bus=bus,
        target_revision="not-a-release",
        rules_by_id={rule.id: rule},
    )
    wrong_kind = _proposal()
    wrong_kind["kind"] = "example"

    with pytest.raises(ValueError, match="kind is invalid"):
        await publisher.publish_remediation_proposal(wrong_kind)
    with pytest.raises(ValueError, match="target revision MUST be a SHA-256 digest"):
        await publisher.publish_remediation_proposal(_proposal())
    assert bus.published == []


def test_binding_rejects_empty_lever_map() -> None:
    with pytest.raises(ValueError, match="MUST carry at least one lever"):
        RemediationProposalBinding(
            publisher=EventBusReadinessRemediationPublisher(
                event_bus=_Bus(),
                target_revision="sha256:" + "a" * 64,
                rules_by_id={},
            ),
            levers={},
        )
