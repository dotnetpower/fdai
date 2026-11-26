"""Focused tests for Operator skill-source projection and authority-free proposal bridge."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai_operator_service.families.workflow.contracts import (
    WorkflowOperation,
    WorkflowProposal,
    WorkflowReadRequest,
)
from fdai_operator_service.skill_source_projection import (
    SKILL_SOURCE_PROPOSAL_TOPIC,
    SkillCandidateProjectionRecord,
    SkillSourceProjectionError,
    SkillSourceProjectionRecord,
    SkillSourceProposalEvent,
    SkillSourceWorkflowBridge,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "src/fdai_operator_service/skill_source_projection.py"
)


class _RecordingEventSink:
    def __init__(self) -> None:
        self.events: list[SkillSourceProposalEvent] = []

    async def publish_proposal_event(self, event: SkillSourceProposalEvent) -> None:
        self.events.append(event)


def _source() -> SkillSourceProjectionRecord:
    return SkillSourceProjectionRecord(
        source_id="operations-skills",
        kind="github_repository",
        location="example-org/skills",
        trust_tier="organization_approved",
        owner="platform-team",
        allowed_path="skills/example",
        refresh_policy="scheduled",
        refresh_interval_seconds=3600,
        enabled=True,
    )


def _candidate() -> SkillCandidateProjectionRecord:
    return SkillCandidateProjectionRecord(
        candidate_id="skill-update-1",
        source_id="operations-skills",
        quarantine_id="skill-quarantine-1",
        artifact_digest="a" * 64,
        prior_installed_digest=None,
        created_at="2026-11-01T12:00:00Z",
    )


def test_projection_module_never_imports_fdai_core() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
    assert not any(name == "fdai" or name.startswith("fdai.") for name in imported)


async def test_sources_register_disabled_by_default_and_reads_require_reader_role() -> None:
    bridge = SkillSourceWorkflowBridge()
    registered = bridge.register_source(_source())
    assert registered.enabled is False
    bridge.put_candidate(_candidate())

    with pytest.raises(SkillSourceProjectionError) as unauth:
        await bridge.read(
            WorkflowReadRequest(
                operation=WorkflowOperation.SKILL_SOURCE_BROWSE,
                principal_id="",
                query={},
                path_parameters={},
            ),
            roles=frozenset({"reader"}),
        )
    assert unauth.value.status_code == 401

    with pytest.raises(SkillSourceProjectionError) as forbidden:
        await bridge.read(
            WorkflowReadRequest(
                operation=WorkflowOperation.SKILL_SOURCE_BROWSE,
                principal_id="operator-1",
                query={},
                path_parameters={},
            ),
            roles=frozenset({"guest"}),
        )
    assert forbidden.value.status_code == 403

    browse = await bridge.read(
        WorkflowReadRequest(
            operation=WorkflowOperation.SKILL_SOURCE_BROWSE,
            principal_id="operator-1",
            query={},
            path_parameters={},
        ),
        roles=frozenset({"reader"}),
    )
    assert browse.payload["read_only"] is True
    assert browse.payload["execution_authority"] == "none"
    assert browse.payload["source_count"] == 1
    assert browse.payload["candidate_count"] == 1
    sources = browse.payload["sources"]
    assert isinstance(sources, list) and sources[0]["enabled"] is False


async def test_proposals_are_role_gated_idempotent_authority_free_and_replayable() -> None:
    sink = _RecordingEventSink()
    bridge = SkillSourceWorkflowBridge(event_sink=sink)
    bridge.register_source(_source())
    bridge.put_candidate(_candidate())

    with pytest.raises(SkillSourceProjectionError) as reader_denied:
        await bridge.submit_proposal(
            WorkflowProposal(
                operation=WorkflowOperation.SKILL_SOURCE_APPROVAL_PROPOSAL,
                principal_id="reader-user",
                idempotency_key="idem-approve-1",
                expected_revision="rev-1",
                request_source="operator-http:approve",
                path_parameters={"source_id": "operations-skills"},
                payload={"candidate_id": "skill-update-1", "mode": "shadow"},
                principal_roles=("reader",),
            ),
            now=NOW,
        )
    assert reader_denied.value.status_code == 403

    first = await bridge.submit_proposal(
        WorkflowProposal(
            operation=WorkflowOperation.SKILL_SOURCE_APPROVAL_PROPOSAL,
            principal_id="approver-user",
            idempotency_key="idem-approve-1",
            expected_revision="rev-1",
            request_source="operator-http:approve",
            path_parameters={"source_id": "operations-skills"},
            payload={"candidate_id": "skill-update-1", "mode": "shadow"},
            principal_roles=("approver",),
        ),
        now=NOW,
    )
    assert first["duplicate"] is False
    assert first["execution_authority"] == "none"
    assert first["target_remains_disabled"] is True
    assert first["event_topic"] == SKILL_SOURCE_PROPOSAL_TOPIC
    assert len(sink.events) == 1

    duplicate = await bridge.submit_proposal(
        WorkflowProposal(
            operation=WorkflowOperation.SKILL_SOURCE_APPROVAL_PROPOSAL,
            principal_id="approver-user",
            idempotency_key="idem-approve-1",
            expected_revision="rev-1",
            request_source="operator-http:approve",
            path_parameters={"source_id": "operations-skills"},
            payload={"candidate_id": "skill-update-1", "mode": "shadow"},
            principal_roles=("approver",),
        ),
        now=NOW,
    )
    assert duplicate["duplicate"] is True
    assert duplicate["proposal_id"] == first["proposal_id"]
    assert len(sink.events) == 1

    with pytest.raises(SkillSourceProjectionError) as conflict:
        await bridge.submit_proposal(
            WorkflowProposal(
                operation=WorkflowOperation.SKILL_SOURCE_APPROVAL_PROPOSAL,
                principal_id="approver-user",
                idempotency_key="idem-approve-1",
                expected_revision="rev-2",
                request_source="operator-http:approve",
                path_parameters={"source_id": "operations-skills"},
                payload={"candidate_id": "skill-update-1", "mode": "shadow"},
                principal_roles=("approver",),
            ),
            now=NOW,
        )
    assert conflict.value.status_code == 409

    with pytest.raises(SkillSourceProjectionError) as approver_revoke_denied:
        await bridge.submit_proposal(
            WorkflowProposal(
                operation=WorkflowOperation.SKILL_SOURCE_REVOCATION_PROPOSAL,
                principal_id="approver-user",
                idempotency_key="idem-revoke-1",
                expected_revision="rev-1",
                request_source="operator-http:revoke",
                path_parameters={"source_id": "operations-skills"},
                payload={"reason": "Compromised upstream key.", "mode": "shadow"},
                principal_roles=("approver",),
            ),
            now=NOW,
        )
    assert approver_revoke_denied.value.status_code == 403

    revoke = await bridge.submit_proposal(
        WorkflowProposal(
            operation=WorkflowOperation.SKILL_SOURCE_REVOCATION_PROPOSAL,
            principal_id="owner-user",
            idempotency_key="idem-revoke-1",
            expected_revision="rev-1",
            request_source="operator-http:revoke",
            path_parameters={"source_id": "operations-skills"},
            payload={"reason": "Compromised upstream key.", "mode": "shadow"},
            principal_roles=("owner",),
        ),
        now=NOW,
    )
    assert revoke["execution_authority"] == "none"
    replayed = bridge.replay_proposals(after_sequence=0)
    assert len(replayed) == 2
    assert [item.operation for item in replayed] == [
        "skill-source.approval-proposal",
        "skill-source.revocation-proposal",
    ]


async def test_proposals_reject_nested_secret_keys_and_control_characters() -> None:
    bridge = SkillSourceWorkflowBridge()
    bridge.register_source(_source())
    bridge.put_candidate(_candidate())

    for nested_payload in (
        {"candidate_id": "skill-update-1", "meta": {"private_key": "x"}},
        {"candidate_id": "skill-update-1", "items": [{"access_token": "x"}]},
    ):
        with pytest.raises(SkillSourceProjectionError) as secret_exc:
            await bridge.submit_proposal(
                WorkflowProposal(
                    operation=WorkflowOperation.SKILL_SOURCE_APPROVAL_PROPOSAL,
                    principal_id="approver-user",
                    idempotency_key="idem-sec-1",
                    expected_revision="rev-1",
                    request_source="operator-http:approve",
                    path_parameters={"source_id": "operations-skills"},
                    payload=nested_payload,
                    principal_roles=("approver",),
                ),
                now=NOW,
            )
        assert secret_exc.value.code == "forbidden_secret_field"

    with pytest.raises(SkillSourceProjectionError) as bad_cid:
        await bridge.submit_proposal(
            WorkflowProposal(
                operation=WorkflowOperation.SKILL_SOURCE_APPROVAL_PROPOSAL,
                principal_id="approver-user",
                idempotency_key="idem-ctrl-1",
                expected_revision="rev-1",
                request_source="operator-http:approve",
                path_parameters={"source_id": "operations-skills"},
                payload={"candidate_id": "skill-update-\x001"},
                principal_roles=("approver",),
            ),
            now=NOW,
        )
    assert bad_cid.value.code == "invalid_candidate_id"

    with pytest.raises(SkillSourceProjectionError) as bad_reason:
        await bridge.submit_proposal(
            WorkflowProposal(
                operation=WorkflowOperation.SKILL_SOURCE_REVOCATION_PROPOSAL,
                principal_id="owner-user",
                idempotency_key="idem-ctrl-2",
                expected_revision="rev-1",
                request_source="operator-http:revoke",
                path_parameters={"source_id": "operations-skills"},
                payload={"reason": "Compromised\nkey"},
                principal_roles=("owner",),
            ),
            now=NOW,
        )
    assert bad_reason.value.code == "invalid_reason"

    with pytest.raises(SkillSourceProjectionError) as missing_cand:
        await bridge.submit_proposal(
            WorkflowProposal(
                operation=WorkflowOperation.SKILL_SOURCE_APPROVAL_PROPOSAL,
                principal_id="approver-user",
                idempotency_key="idem-missing-cand",
                expected_revision="rev-1",
                request_source="operator-http:approve",
                path_parameters={"source_id": "operations-skills"},
                payload={"candidate_id": "nonexistent-candidate"},
                principal_roles=("approver",),
            ),
            now=NOW,
        )
    assert missing_cand.value.status_code == 404
    assert missing_cand.value.code == "candidate_not_found"
