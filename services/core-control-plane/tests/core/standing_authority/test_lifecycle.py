"""A3-E immutable lifecycle, replay, race, and fence tests."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.core.standing_authority.lifecycle import (
    AuthenticatedAuthorizationCommand,
    AuthorizationCommandKind,
    AuthorizationLifecycleCommand,
    AuthorizationLifecycleError,
    AuthorizationRevision,
    AuthorizationSnapshot,
    AuthorizationTransition,
    AuthorizationWriteStatus,
    StandingAuthorizationLifecycleWriter,
    authorization_revision_id,
    fence_matches,
    plan_lifecycle_transition,
    replay_lifecycle,
)
from fdai.core.standing_authority.record import StandingAuthorization

NOW = datetime(2026, 8, 29, 6, 0, tzinfo=UTC)
SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"
AUTHENTICATION = "sha256:" + "f" * 64


def _authorization(**overrides: Any) -> StandingAuthorization:
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": "sa.example-scale-out",
        "authorization_revision": "pending",
        "status": "active",
        "mode": "shadow",
        "requested_by": "human:requester",
        "approvals": [
            {
                "principal": "human:service-owner",
                "role": "service_owner",
                "approved_at": "2026-08-29T05:00:00Z",
            },
            {
                "principal": "human:owner",
                "role": "owner",
                "approved_at": "2026-08-29T05:01:00Z",
            },
        ],
        "quorum_required": 2,
        "valid_from": "2026-08-29T05:00:00Z",
        "valid_until": "2026-08-30T05:00:00Z",
        "service_ref": "service:example",
        "scope": {"level": "resource_group", "value": "scope:example"},
        "pins": {
            "policy_digest": "sha256:policy",
            "target_revision": "target:1",
            "action_type_versions": ["ops.scale-out@1.0.0"],
            "evidence_revisions": ["evidence:1"],
        },
        "envelope": {
            "action_types": ["ops.scale-out"],
            "max_blast_radius": 2,
            "max_duration_seconds": 300,
            "reversible": True,
            "rollback_contract": "scripted",
            "stop_conditions": ["provider-error"],
        },
        "incident_classes": ["capacity"],
        "responders": {
            "primary": "human:primary",
            "backup": "human:backup",
            "confirmed_at": "2026-08-29T05:00:00Z",
        },
        "evidence": {
            "history_reviewed": True,
            "precedent_ref": "case:one",
            "scenario_evidence_ref": None,
        },
    }
    document.update(overrides)
    return StandingAuthorization.from_mapping(document)


def _revision(
    *,
    family_id: str = "family:one",
    predecessor: str | None = None,
    issued_at: datetime = NOW,
    proof_subject: str | None = None,
) -> AuthorizationRevision:
    authorization = _authorization()
    revision_id = authorization_revision_id(
        family_id=family_id,
        predecessor_revision_id=predecessor,
        issued_at=issued_at,
        authorization=authorization,
    )
    suffix = hashlib.sha256(f"{issued_at.isoformat()}:{predecessor}".encode()).hexdigest()
    return AuthorizationRevision.create(
        family_id=family_id,
        predecessor_revision_id=predecessor,
        issued_at=issued_at,
        authorization=authorization,
        approvals_digest="sha256:" + suffix,
        evidence_verification_bundle_digest="sha256:"
        + hashlib.sha256(f"evidence:{suffix}".encode()).hexdigest(),
        proof_subject_revision_id=proof_subject or revision_id,
    )


def _context(command_id: str) -> AuthenticatedAuthorizationCommand:
    return AuthenticatedAuthorizationCommand(
        command_id=command_id,
        actor_ref="human:owner",
        actor_kind="human",
        actor_roles=frozenset({"owner"}),
        authentication_evidence_digest=AUTHENTICATION,
        authenticated_at=NOW,
        correlation_id=f"correlation:{command_id}",
    )


def _admit(revision: AuthorizationRevision, *, command_id: str = "command:admit"):
    return AuthorizationLifecycleCommand(
        kind=AuthorizationCommandKind.ADMIT,
        family_id=revision.family_id,
        context=_context(command_id),
        occurred_at=revision.issued_at,
        expected_revision_id=None,
        expected_fencing_generation=0,
        revision=revision,
    )


def _renew(
    revision: AuthorizationRevision,
    snapshot: AuthorizationSnapshot,
    *,
    command_id: str = "command:renew",
):
    return AuthorizationLifecycleCommand(
        kind=AuthorizationCommandKind.RENEW,
        family_id=revision.family_id,
        context=_context(command_id),
        occurred_at=revision.issued_at,
        expected_revision_id=snapshot.current_revision_id,
        expected_fencing_generation=snapshot.fencing_generation,
        revision=revision,
    )


def _revoke(
    snapshot: AuthorizationSnapshot,
    *,
    command_id: str = "command:revoke",
    whole_family: bool = False,
):
    return AuthorizationLifecycleCommand(
        kind=AuthorizationCommandKind.REVOKE,
        family_id=snapshot.family_id,
        context=_context(command_id),
        occurred_at=NOW + timedelta(minutes=30),
        expected_revision_id=None if whole_family else snapshot.current_revision_id,
        expected_fencing_generation=snapshot.fencing_generation,
        whole_family=whole_family,
    )


def _apply(
    *,
    snapshot: AuthorizationSnapshot | None,
    transitions: list[AuthorizationTransition],
    revisions: dict[str, AuthorizationRevision],
    command: AuthorizationLifecycleCommand,
):
    result = plan_lifecycle_transition(
        snapshot=snapshot,
        transitions=tuple(transitions),
        revisions=revisions,
        command=command,
    )
    if result.status is AuthorizationWriteStatus.APPLIED:
        transitions.append(result.transition)
        if command.revision is not None:
            revisions[command.revision.revision_id] = command.revision
    return result


def test_admit_renew_revoke_redelivery_and_fence() -> None:
    transitions: list[AuthorizationTransition] = []
    revisions: dict[str, AuthorizationRevision] = {}
    first = _revision()
    admitted = _apply(
        snapshot=None,
        transitions=transitions,
        revisions=revisions,
        command=_admit(first),
    )
    assert admitted.status is AuthorizationWriteStatus.APPLIED
    assert fence_matches(admitted.snapshot, admitted.snapshot.fence())

    duplicate = _apply(
        snapshot=admitted.snapshot,
        transitions=transitions,
        revisions=revisions,
        command=_admit(first),
    )
    assert duplicate.status is AuthorizationWriteStatus.DUPLICATE
    assert duplicate.snapshot == admitted.snapshot
    conflicting_redelivery = replace(
        _admit(first),
        revision=replace(
            first,
            proof_bindings=replace(
                first.proof_bindings,
                approvals_digest="sha256:" + "1" * 64,
            ),
        ),
    )
    with pytest.raises(AuthorizationLifecycleError, match="idempotency key payload conflict"):
        _apply(
            snapshot=admitted.snapshot,
            transitions=transitions,
            revisions=revisions,
            command=conflicting_redelivery,
        )

    second = _revision(
        predecessor=first.revision_id,
        issued_at=NOW + timedelta(minutes=10),
    )
    renewed = _apply(
        snapshot=admitted.snapshot,
        transitions=transitions,
        revisions=revisions,
        command=_renew(second, admitted.snapshot),
    )
    assert renewed.snapshot.fencing_generation == 2
    assert not fence_matches(renewed.snapshot, admitted.snapshot.fence())
    duplicate_renew = _apply(
        snapshot=renewed.snapshot,
        transitions=transitions,
        revisions=revisions,
        command=_renew(second, admitted.snapshot),
    )
    assert duplicate_renew.status is AuthorizationWriteStatus.DUPLICATE
    assert duplicate_renew.snapshot == renewed.snapshot

    duplicate_admit_after_renewal = _apply(
        snapshot=renewed.snapshot,
        transitions=transitions,
        revisions=revisions,
        command=_admit(first),
    )
    assert duplicate_admit_after_renewal.snapshot == renewed.snapshot
    with pytest.raises(AuthorizationLifecycleError, match="projection"):
        plan_lifecycle_transition(
            snapshot=admitted.snapshot,
            transitions=tuple(transitions),
            revisions=revisions,
            command=_revoke(renewed.snapshot),
        )

    revoked = _apply(
        snapshot=renewed.snapshot,
        transitions=transitions,
        revisions=revisions,
        command=_revoke(renewed.snapshot),
    )
    assert revoked.snapshot.fencing_generation == 3
    assert not fence_matches(revoked.snapshot, revoked.snapshot.fence())

    duplicate_revoke = _apply(
        snapshot=revoked.snapshot,
        transitions=transitions,
        revisions=revisions,
        command=_revoke(renewed.snapshot),
    )
    assert duplicate_revoke.status is AuthorizationWriteStatus.DUPLICATE


@pytest.mark.parametrize("renew_first", [True, False])
def test_renew_and_family_revoke_races_fail_the_loser(renew_first: bool) -> None:
    transitions: list[AuthorizationTransition] = []
    revisions: dict[str, AuthorizationRevision] = {}
    first = _revision()
    admitted = _apply(
        snapshot=None,
        transitions=transitions,
        revisions=revisions,
        command=_admit(first),
    )
    second = _revision(
        predecessor=first.revision_id,
        issued_at=NOW + timedelta(minutes=10),
    )
    renew = _renew(second, admitted.snapshot)
    revoke = _revoke(admitted.snapshot, whole_family=True)

    winner = renew if renew_first else revoke
    loser = revoke if renew_first else renew
    won = _apply(
        snapshot=admitted.snapshot,
        transitions=transitions,
        revisions=revisions,
        command=winner,
    )
    with pytest.raises(AuthorizationLifecycleError):
        _apply(
            snapshot=won.snapshot,
            transitions=transitions,
            revisions=revisions,
            command=loser,
        )


def test_forged_revision_and_approval_reuse_are_rejected() -> None:
    first = _revision()
    with pytest.raises(AuthorizationLifecycleError, match="proof bindings"):
        _revision(
            predecessor=first.revision_id,
            issued_at=NOW + timedelta(minutes=1),
            proof_subject=first.revision_id,
        )

    forged_revision_id = "sha256:" + "0" * 64
    with pytest.raises(AuthorizationLifecycleError, match="revision digest"):
        replace(
            first,
            revision_id=forged_revision_id,
            proof_bindings=replace(
                first.proof_bindings,
                revision_id=forged_revision_id,
            ),
        )

    issued_at = NOW + timedelta(minutes=2)
    authorization = _authorization()
    reused = AuthorizationRevision.create(
        family_id="family:one",
        predecessor_revision_id=first.revision_id,
        issued_at=issued_at,
        authorization=authorization,
        approvals_digest=first.proof_bindings.approvals_digest,
        evidence_verification_bundle_digest="sha256:" + "9" * 64,
        proof_subject_revision_id=authorization_revision_id(
            family_id="family:one",
            predecessor_revision_id=first.revision_id,
            issued_at=issued_at,
            authorization=authorization,
        ),
    )
    transitions: list[AuthorizationTransition] = []
    revisions: dict[str, AuthorizationRevision] = {}
    admitted = _apply(
        snapshot=None,
        transitions=transitions,
        revisions=revisions,
        command=_admit(first),
    )
    with pytest.raises(AuthorizationLifecycleError, match="MUST NOT be reused"):
        _apply(
            snapshot=admitted.snapshot,
            transitions=transitions,
            revisions=revisions,
            command=_renew(reused, admitted.snapshot),
        )


def test_idempotency_digest_binds_approval_and_evidence_proofs() -> None:
    revision = _revision()
    command = _admit(revision)
    changed = replace(
        command,
        revision=replace(
            revision,
            proof_bindings=replace(
                revision.proof_bindings,
                approvals_digest="sha256:" + "1" * 64,
            ),
        ),
    )

    assert changed.command_digest != command.command_digest


def test_revision_rejects_tampered_approval_and_evidence_claims() -> None:
    revision = _revision()
    document = json.loads(revision.document_json)
    document["approvals"][0]["principal"] = "human:forged"

    with pytest.raises(AuthorizationLifecycleError, match="approval claims"):
        replace(
            revision,
            document_json=json.dumps(
                document,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )


def test_unbounded_replay_and_reordered_or_partial_history_fail_closed() -> None:
    transitions: list[AuthorizationTransition] = []
    revisions: dict[str, AuthorizationRevision] = {}
    revision = _revision()
    result = _apply(
        snapshot=None,
        transitions=transitions,
        revisions=revisions,
        command=_admit(revision),
    )
    for index in range(1, 201):
        revision = _revision(
            predecessor=result.snapshot.current_revision_id,
            issued_at=NOW + timedelta(minutes=index),
        )
        result = _apply(
            snapshot=result.snapshot,
            transitions=transitions,
            revisions=revisions,
            command=_renew(
                revision,
                result.snapshot,
                command_id=f"command:renew:{index}",
            ),
        )

    assert replay_lifecycle(transitions=tuple(transitions), revisions=revisions) == result.snapshot
    with pytest.raises(AuthorizationLifecycleError, match="sequence"):
        replay_lifecycle(
            transitions=(transitions[0], *transitions[2:]),
            revisions=revisions,
        )
    with pytest.raises(AuthorizationLifecycleError):
        replay_lifecycle(
            transitions=(transitions[1], transitions[0], *transitions[2:]),
            revisions=revisions,
        )
    with pytest.raises(AuthorizationLifecycleError, match="projection"):
        plan_lifecycle_transition(
            snapshot=None,
            transitions=tuple(transitions),
            revisions=revisions,
            command=_revoke(result.snapshot),
        )


def test_shadow_lifecycle_and_store_remain_unwired_from_authority_paths() -> None:
    forbidden_prefixes = (
        "fdai.core.standing_authority",
        "fdai.shared.providers.standing_authority",
        "fdai.delivery.persistence.postgres_standing_authority",
    )
    roots = (
        "agents",
        "risk_gate",
        "executor",
        "hil_resume",
        "control_loop",
        "composition.py",
        "composition",
    )
    violations: list[str] = []
    for root in roots:
        path = SOURCE_ROOT / root
        candidates = (path,) if path.is_file() else path.rglob("*.py")
        for candidate in candidates:
            tree = ast.parse(candidate.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    modules = (node.module,)
                if any(
                    module.startswith(prefix) for module in modules for prefix in forbidden_prefixes
                ):
                    violations.append(str(candidate.relative_to(SOURCE_ROOT)))
    assert violations == []


async def test_core_writer_is_the_store_mutation_entrypoint() -> None:
    revision = _revision()
    command = _admit(revision)

    class _Store:
        def __init__(self) -> None:
            self.command = None

        async def apply(self, value):
            self.command = value
            transitions: list[AuthorizationTransition] = []
            revisions: dict[str, AuthorizationRevision] = {}
            return _apply(
                snapshot=None,
                transitions=transitions,
                revisions=revisions,
                command=value,
            )

    store = _Store()
    result = await StandingAuthorizationLifecycleWriter(store).apply(command)

    assert store.command is command
    assert result.status is AuthorizationWriteStatus.APPLIED
