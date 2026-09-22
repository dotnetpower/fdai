from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from fdai_operator_service.families.workflow.contracts import (
    WorkflowOperation,
    WorkflowReadRequest,
)
from fdai_operator_service.family_adapters import PostgresWorkflowAdapters
from fdai_operator_service.postgres_family_models import StoredStatePage
from fdai_service_contracts.rule_activation import (
    RuleActivationDelta,
    RuleActivationGeneration,
    RuleActivationMember,
    RuleActivationProposal,
    RuleActivationSource,
    rule_activation_generation_digest,
    rule_activation_proposal_digest,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _generation() -> RuleActivationGeneration:
    members = (
        RuleActivationMember(
            rule_id="rule.alpha",
            rule_version="1.0.0",
            rule_digest="a" * 64,
        ),
    )
    digest = rule_activation_generation_digest(
        profile_id="baseline",
        profile_version="1.0.0",
        catalog_digest="b" * 64,
        members=members,
    )
    return RuleActivationGeneration(
        generation_id=f"rule-activation-{digest[:32]}",
        generation_digest=digest,
        profile_id="baseline",
        profile_version="1.0.0",
        catalog_digest="b" * 64,
        members=members,
        created_at=NOW,
    )


def _proposal() -> RuleActivationProposal:
    changes = (RuleActivationDelta(rule_id="rule.alpha", enabled=False),)
    digest = rule_activation_proposal_digest(
        idempotency_key="disable-alpha",
        expected_generation_digest=_generation().generation_digest,
        source=RuleActivationSource.DIRECT,
        source_ref="operator-proposal:workflow:" + "c" * 64,
        source_digest="d" * 64,
        requested_by="requester",
        requested_at=NOW,
        reason="Disable this reviewed Rule after a confirmed false positive.",
        changes=changes,
    )
    return RuleActivationProposal(
        request_id=f"rule-activation-request-{digest[:32]}",
        idempotency_key="disable-alpha",
        expected_generation_digest=_generation().generation_digest,
        source=RuleActivationSource.DIRECT,
        source_ref="operator-proposal:workflow:" + "c" * 64,
        source_digest="d" * 64,
        requested_by="requester",
        requested_at=NOW,
        reason="Disable this reviewed Rule after a confirmed false positive.",
        changes=changes,
    )


async def test_status_uses_string_revision_and_includes_pending_requests() -> None:
    generation = _generation()
    proposal = _proposal()

    class Store:
        async def read_state(self, key: str) -> dict[str, object] | None:
            if key == "rule-activation:current":
                return {
                    "kind": "rule_activation.current",
                    "revision": 2,
                    "generation_id": generation.generation_id,
                    "generation_digest": generation.generation_digest,
                    "source": "installation",
                    "source_ref": "runtime-artifact:baseline",
                    "requested_by": "release-signer",
                    "approver_ids": ["deployment-approver"],
                    "activated_at": NOW.isoformat(),
                }
            if key == f"rule-activation:generation:{generation.generation_id}":
                return {"generation": generation.model_dump(mode="json")}
            return None

        async def read_state_page(self, *, prefix: str, limit: int) -> StoredStatePage:
            del limit
            if prefix == "rule-activation:request:":
                from fdai_operator_service.postgres_family_models import StoredStateRecord

                return StoredStatePage(
                    records=(
                        StoredStateRecord(
                            key=prefix + proposal.request_id,
                            value={
                                "kind": "rule_activation.request",
                                "operator_proposal_id": "operator-" + "e" * 32,
                                "proposal": proposal.model_dump(mode="json"),
                            },
                            updated_at=NOW,
                        ),
                    ),
                    truncated=False,
                )
            return StoredStatePage(records=(), truncated=False)

    result = await PostgresWorkflowAdapters(cast(Any, Store())).read(
        WorkflowReadRequest(
            operation=WorkflowOperation.RULE_ACTIVATION_STATUS,
            principal_id="reader",
            query={},
            path_parameters={},
        )
    )

    assert len(result.provenance.revision) == 64
    assert result.payload["active_rule_ids"] == ["rule.alpha"]
    pending = cast(list[dict[str, object]], result.payload["pending_requests"])
    assert pending[0]["request_id"] == "operator-" + "e" * 32
    assert pending[0]["proposal_digest"] == proposal.proposal_digest
