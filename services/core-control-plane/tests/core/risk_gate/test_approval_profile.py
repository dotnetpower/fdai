"""Approval profiles and the never-raising operator policy input (#1825)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.risk_gate.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRefusal,
    ApprovalProfileRevision,
    OperatorPolicyInput,
    OperatorPolicyOutcome,
    apply_operator_policy,
    effective_quorum_for,
    evaluate_profile_approval,
    profile_transition_quorum,
)
from fdai.core.risk_gate.authority import evaluate_execution_authority
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.runtime.approval_profile import (
    PROFILE_JSON_ENV,
    PROFILE_PATH_ENV,
    StateStoreApprovalProfileRevisionReader,
    approval_runtime_bindings,
    load_active_approval_profile,
    load_approval_profile,
)
from fdai.runtime.development_authority import PROFILE_ENV as DEVELOPMENT_PROFILE_ENV
from fdai.shared.contracts.models import (
    ActionBlastRadius,
    ActionInterface,
    BlastRadiusComputation,
    BlastRadiusScope,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Tier,
)
from fdai.shared.providers.testing import InMemoryStateStore
from fdai_service_contracts.approval_profile import (
    approval_profile_from_audit_dict,
    approval_profile_policy_digest,
)
from fdai_service_contracts.policy_administration import (
    ApprovalPolicyContent,
    PolicyKind,
    PolicyRevisionRecord,
    PolicyRevisionSignature,
    PolicyValidationResult,
    policy_content_digest,
)

from .test_authority import _destructive_at, _low_risk_at, _table

_OPERATOR = "00000000-0000-0000-0000-00000000000A"
_EXECUTOR = "thor-executor"
_AT = datetime(2026, 10, 5, tzinfo=UTC)


def _profile_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "revision_id": "approval-profile-r1",
        "approval_profile": "single-operator-production",
        "executor_principal": _EXECUTOR,
        "effective_from": _AT.isoformat(),
        "operator_principal": _OPERATOR,
    }
    payload["policy_digest"] = approval_profile_policy_digest(payload)
    return payload


_DIGEST = str(_profile_payload()["policy_digest"])


def _single() -> ApprovalProfileRevision:
    return ApprovalProfileRevision(
        revision_id="approval-profile-r1",
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal=_EXECUTOR,
        policy_digest=_DIGEST,
        effective_from=_AT,
        operator_principal=_OPERATOR,
    )


def _single_json() -> str:
    return json.dumps(_profile_payload(), separators=(",", ":"), sort_keys=True)


def _profile_payload_with_revision(revision_id: str, operator: str) -> dict[str, object]:
    payload = _profile_payload()
    payload["revision_id"] = revision_id
    payload["operator_principal"] = operator
    payload["policy_digest"] = approval_profile_policy_digest(payload)
    return payload


def _profile_payload_with_effective_from(effective_from: str) -> dict[str, object]:
    payload = _profile_payload()
    payload["effective_from"] = effective_from
    payload["policy_digest"] = approval_profile_policy_digest(payload)
    return payload


_SIGNING_KEY_ID = "https://fdai-example.vault.azure.net/keys/policy-signing/v1"


class _SignatureVerifier:
    async def verify_policy_revision_signature(self, record: PolicyRevisionRecord) -> bool:
        return (
            record.signature is not None
            and record.signature.key_id == _SIGNING_KEY_ID
            and record.signature.signature_base64 == "signature-good"
        )


def _policy_revision(
    payload: dict[str, object],
    *,
    signature_base64: str | None = "signature-good",
) -> PolicyRevisionRecord:
    content = ApprovalPolicyContent(document=payload)
    content_digest = policy_content_digest(content)
    return PolicyRevisionRecord(
        revision_id=_mimir_revision_id(PolicyKind.APPROVAL, content_digest, None),
        policy_kind=PolicyKind.APPROVAL,
        content_digest=content_digest,
        content=content,
        signature_ref="signature:approval-profile",
        signature=(
            PolicyRevisionSignature(
                key_id=_SIGNING_KEY_ID,
                algorithm="RS256",
                signature_base64=signature_base64,
            )
            if signature_base64 is not None
            else None
        ),
        author_principal="policy-admin@example.com",
        reason="Select the reviewed single-operator production approval profile.",
        created_at=_AT,
        validation=PolicyValidationResult(
            rego_valid=False,
            release_maximums_valid=True,
            policy_tests_valid=False,
            validation_digest="sha256:" + "1" * 64,
        ),
        diff_digest="sha256:" + "2" * 64,
    )


def _mimir_revision_id(
    policy_kind: PolicyKind,
    content_digest: str,
    parent_revision_id: str | None,
) -> str:
    seed = f"{policy_kind.value}\0{content_digest}\0{parent_revision_id or ''}"
    return f"{policy_kind.value}:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]}"


async def _activate_profile(
    store: InMemoryStateStore,
    payload: dict[str, object],
    *,
    parent_revision_id: str | None = None,
    signature_base64: str | None = "signature-good",
) -> None:
    record = _policy_revision(payload, signature_base64=signature_base64)
    if parent_revision_id is not None:
        record = PolicyRevisionRecord.model_validate(
            {
                **record.model_dump(mode="json"),
                "revision_id": _mimir_revision_id(
                    PolicyKind.APPROVAL,
                    record.content_digest,
                    parent_revision_id,
                ),
                "parent_revision_id": parent_revision_id,
            }
        )
    await store.write_state(
        f"policy_revision:{PolicyKind.APPROVAL.value}:{record.revision_id}",
        record.model_dump(mode="json"),
    )
    pointer = await store.read_state(f"policy_activation:{PolicyKind.APPROVAL.value}")
    assert (None if pointer is None else pointer.get("revision_id")) == parent_revision_id
    await store.write_state(
        f"policy_activation:{PolicyKind.APPROVAL.value}",
        {
            "revision_id": record.revision_id,
            "policy_digest": record.content_digest,
            "activated_at": _AT.isoformat(),
            "revision": 1 if pointer is None else int(pointer.get("revision", 0)) + 1,
        },
    )
    await store.write_state(
        f"policy_activation_history:{PolicyKind.APPROVAL.value}:{record.revision_id}",
        {
            "revision_id": record.revision_id,
            "policy_digest": record.content_digest,
            "approval_profile_digest": payload["policy_digest"],
            "activated_at": _AT.isoformat(),
        },
    )


def _multi() -> ApprovalProfileRevision:
    return ApprovalProfileRevision(
        revision_id="approval-profile-r0",
        approval_profile=ApprovalProfileKind.MULTI_OPERATOR,
        executor_principal=_EXECUTOR,
        policy_digest=_DIGEST,
        effective_from=_AT,
    )


def _irreversible_at() -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="remediate.purge-backup",
        version="1.0.0",
        operation=Operation.DELETE,
        interfaces=[ActionInterface.CONTROL_PLANE],
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        irreversible=True,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
    )


# --- profile revision invariants -------------------------------------------


def test_single_operator_profile_requires_one_named_operator() -> None:
    with pytest.raises(ValueError, match="MUST name one operator"):
        replace(_single(), operator_principal=None)
    with pytest.raises(ValueError, match="MUST name one operator"):
        replace(_single(), operator_principal="  ")


def test_named_operator_can_never_be_the_executor() -> None:
    with pytest.raises(ValueError, match="MUST NOT be the executor"):
        replace(_single(), operator_principal=_EXECUTOR.upper())


def test_multi_operator_profile_names_no_operator() -> None:
    with pytest.raises(ValueError, match="MUST NOT name an operator"):
        replace(_multi(), operator_principal=_OPERATOR)


def test_profile_revision_pins_a_digest_and_aware_time() -> None:
    with pytest.raises(ValueError, match="sha256"):
        replace(_single(), policy_digest="sha256:XYZ")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_single(), effective_from=datetime(2026, 10, 5))


def test_missing_approval_profile_config_selects_multi_operator_default() -> None:
    assert load_approval_profile({}) is None
    assert approval_runtime_bindings({}) is None


def test_approval_profile_loads_from_json_and_path(tmp_path: Path) -> None:
    loaded = load_approval_profile({PROFILE_JSON_ENV: _single_json()}, clock=lambda: _AT)
    assert loaded == _single()
    path = tmp_path / "approval-profile.json"
    path.write_text(_single_json(), encoding="utf-8")
    assert load_approval_profile({PROFILE_PATH_ENV: str(path)}, clock=lambda: _AT) == _single()


@pytest.mark.parametrize(
    "effective_from", ["2026-10-05T00:00:00Z", "2026-10-05T00:00:00.000+00:00"]
)
def test_approval_profile_rejects_noncanonical_effective_from(effective_from: str) -> None:
    payload = _profile_payload_with_effective_from(effective_from)

    with pytest.raises(RuntimeError, match="canonical"):
        load_approval_profile({PROFILE_JSON_ENV: json.dumps(payload)}, clock=lambda: _AT)

    with pytest.raises(ValueError, match="canonical"):
        ApprovalPolicyContent(document=payload)


def test_active_policy_pointer_wins_over_bootstrap_profile_and_audits_mismatch() -> None:
    store = InMemoryStateStore()
    active_payload = _profile_payload_with_revision("approval-profile-r2", "active@example.com")
    bootstrap_payload = _profile_payload_with_revision(
        "approval-profile-bootstrap",
        "bootstrap@example.com",
    )
    asyncio.run(_activate_profile(store, active_payload))

    loaded = asyncio.run(
        load_active_approval_profile(
            {PROFILE_JSON_ENV: json.dumps(bootstrap_payload)},
            reader=StateStoreApprovalProfileRevisionReader(
                store,
                signature_verifier=_SignatureVerifier(),
            ),
            audit_store=store,
            clock=lambda: _AT,
        )
    )

    assert loaded is not None
    assert loaded.revision_id == "approval-profile-r2"
    assert loaded.operator_principal == "active@example.com"
    assert any(
        entry.get("entry", {}).get("event_type") == "approval_profile_bootstrap_mismatch"
        for entry in store.audit_entries
    )


def test_active_policy_pointer_digest_mismatch_fails_closed() -> None:
    store = InMemoryStateStore()
    payload = _profile_payload_with_revision("approval-profile-r2", "active@example.com")
    record = _policy_revision(payload).model_dump(mode="json")
    record["content"]["document"]["policy_digest"] = "sha256:" + "3" * 64
    asyncio.run(
        store.write_state(
            f"policy_revision:{PolicyKind.APPROVAL.value}:approval-profile-r2",
            record,
        )
    )
    asyncio.run(
        store.write_state(
            f"policy_activation:{PolicyKind.APPROVAL.value}",
            {"revision_id": "approval-profile-r2"},
        )
    )

    with pytest.raises(RuntimeError, match="active approval profile revision is invalid"):
        asyncio.run(
            load_active_approval_profile(
                {},
                reader=StateStoreApprovalProfileRevisionReader(
                    store,
                    signature_verifier=_SignatureVerifier(),
                ),
                clock=lambda: _AT,
            )
        )


@pytest.mark.parametrize(
    ("signature_base64", "verifier"),
    [
        (None, _SignatureVerifier()),
        ("signature-tampered", _SignatureVerifier()),
        ("signature-good", None),
    ],
)
def test_active_policy_pointer_without_verified_signature_fails_closed_instead_of_env_fallback(
    signature_base64: str | None,
    verifier: _SignatureVerifier | None,
) -> None:
    store = InMemoryStateStore()
    payload = _profile_payload_with_revision("approval-profile-r2", "active@example.com")
    asyncio.run(_activate_profile(store, payload, signature_base64=signature_base64))

    with pytest.raises(RuntimeError, match="active approval profile revision is invalid"):
        asyncio.run(
            load_active_approval_profile(
                {PROFILE_JSON_ENV: _single_json()},
                reader=StateStoreApprovalProfileRevisionReader(
                    store,
                    signature_verifier=verifier,
                ),
                clock=lambda: _AT,
            )
        )


def test_active_policy_document_swapped_under_valid_signature_fails_closed() -> None:
    store = InMemoryStateStore()
    payload = _profile_payload_with_revision("approval-profile-r2", "active@example.com")
    asyncio.run(_activate_profile(store, payload))
    pointer = asyncio.run(store.read_state(f"policy_activation:{PolicyKind.APPROVAL.value}"))
    assert pointer is not None
    key = f"policy_revision:{PolicyKind.APPROVAL.value}:{pointer['revision_id']}"
    stored = asyncio.run(store.read_state(key))
    assert stored is not None
    stored["content"]["document"] = _profile_payload_with_revision(
        "approval-profile-r2",
        "attacker@example.com",
    )
    asyncio.run(store.write_state(key, stored))

    with pytest.raises(RuntimeError, match="active approval profile revision is invalid"):
        asyncio.run(
            load_active_approval_profile(
                {},
                reader=StateStoreApprovalProfileRevisionReader(
                    store,
                    signature_verifier=_SignatureVerifier(),
                ),
                clock=lambda: _AT,
            )
        )


def test_missing_policy_pointer_keeps_bootstrap_profile_without_verifier() -> None:
    loaded = asyncio.run(
        load_active_approval_profile(
            {PROFILE_JSON_ENV: _single_json()},
            reader=StateStoreApprovalProfileRevisionReader(InMemoryStateStore()),
            clock=lambda: _AT,
        )
    )

    assert loaded is not None
    assert loaded.as_audit_dict() == _single().as_audit_dict()


@pytest.mark.parametrize("activation", [{}, {"revision_id": ""}, {"revision_id": 123}])
def test_malformed_active_policy_pointer_fails_closed_instead_of_env_fallback(
    activation: dict[str, object],
) -> None:
    store = InMemoryStateStore()
    asyncio.run(store.write_state(f"policy_activation:{PolicyKind.APPROVAL.value}", activation))

    with pytest.raises(RuntimeError, match="active approval profile revision is invalid"):
        asyncio.run(
            load_active_approval_profile(
                {PROFILE_JSON_ENV: _single_json()},
                reader=StateStoreApprovalProfileRevisionReader(store),
                clock=lambda: _AT,
            )
        )


def test_parked_profile_digest_mismatch_is_malformed() -> None:
    payload = _single().as_audit_dict()
    payload["policy_digest"] = "sha256:" + "4" * 64

    with pytest.raises(ValueError, match="digest"):
        approval_profile_from_audit_dict(payload)


@pytest.mark.parametrize(
    "environment",
    [
        {PROFILE_JSON_ENV: "{not json"},
        {PROFILE_JSON_ENV: "[]"},
        {
            PROFILE_JSON_ENV: _single_json().replace(_DIGEST, "latest"),
        },
        {
            PROFILE_JSON_ENV: json.dumps({**_profile_payload(), "unknown": True}),
        },
        {
            PROFILE_JSON_ENV: json.dumps(
                {
                    **_profile_payload(),
                    "effective_from": (_AT + timedelta(days=1)).isoformat(),
                    "policy_digest": approval_profile_policy_digest(
                        {
                            **_profile_payload(),
                            "effective_from": (_AT + timedelta(days=1)).isoformat(),
                        }
                    ),
                }
            ),
        },
        {
            PROFILE_JSON_ENV: _single_json(),
            PROFILE_PATH_ENV: "profile.json",
        },
        {
            PROFILE_JSON_ENV: _single_json(),
            DEVELOPMENT_PROFILE_ENV: '{"profile_id":"dev"}',
        },
    ],
)
def test_malformed_or_conflicting_approval_profile_config_fails_closed(
    environment: dict[str, str],
) -> None:
    with pytest.raises(RuntimeError):
        load_approval_profile(environment, clock=lambda: _AT)


# --- approval decisions -----------------------------------------------------


def test_named_operator_satisfies_quorum_of_two_with_effective_quorum_of_one() -> None:
    decision = evaluate_profile_approval(
        _single(),
        approver=_OPERATOR.lower(),
        requester=_OPERATOR,
        original_quorum=2,
        executor_principal=_EXECUTOR,
    )
    assert decision.allowed is True
    assert decision.original_quorum == 2
    assert decision.effective_quorum == 1
    assert decision.self_review is True
    audit = decision.as_audit_dict()
    assert audit["approval_profile"] == "single-operator-production"
    assert audit["original_quorum"] == 2
    assert audit["effective_quorum"] == 1
    assert audit["operator_principal"] == _OPERATOR


def test_operator_may_approve_a_system_request() -> None:
    decision = evaluate_profile_approval(
        _single(), approver=_OPERATOR, requester="fdai-core", original_quorum=1
    )
    assert decision.allowed is True
    assert decision.self_review is False


def test_unnamed_principal_is_refused_under_single_operator() -> None:
    decision = evaluate_profile_approval(
        _single(), approver="someone-else", requester=_OPERATOR, original_quorum=2
    )
    assert decision.allowed is False
    assert decision.refusal is ApprovalProfileRefusal.UNNAMED_PRINCIPAL


@pytest.mark.parametrize("profile", [_single(), _multi(), None])
def test_var_approver_and_thor_executor_stay_distinct(
    profile: ApprovalProfileRevision | None,
) -> None:
    decision = evaluate_profile_approval(
        profile,
        approver="runtime-executor",
        requester="fdai-core",
        original_quorum=1,
        executor_principal="RUNTIME-EXECUTOR",
    )
    assert decision.allowed is False
    assert decision.refusal is ApprovalProfileRefusal.APPROVER_IS_EXECUTOR
    revision_executor = evaluate_profile_approval(
        profile, approver=_EXECUTOR, requester="fdai-core", original_quorum=1
    )
    if profile is not None:
        assert revision_executor.refusal is ApprovalProfileRefusal.APPROVER_IS_EXECUTOR


@pytest.mark.parametrize("profile", [_multi(), None])
def test_multi_operator_keeps_the_original_quorum_and_refuses_self_approval(
    profile: ApprovalProfileRevision | None,
) -> None:
    allowed = evaluate_profile_approval(
        profile, approver="approver-b", requester="requester-a", original_quorum=2
    )
    assert allowed.allowed is True
    assert allowed.effective_quorum == 2
    assert allowed.approval_profile is ApprovalProfileKind.MULTI_OPERATOR
    refused = evaluate_profile_approval(
        profile, approver="Requester-A", requester="requester-a", original_quorum=2
    )
    assert refused.refusal is ApprovalProfileRefusal.SELF_APPROVAL


@pytest.mark.parametrize(
    ("approver", "requester", "refusal"),
    [
        (" ", "fdai-core", ApprovalProfileRefusal.BLANK_APPROVER),
        (_OPERATOR, "", ApprovalProfileRefusal.UNKNOWN_REQUESTER),
    ],
)
def test_unverifiable_identities_fail_closed(
    approver: str, requester: str, refusal: ApprovalProfileRefusal
) -> None:
    decision = evaluate_profile_approval(
        _single(), approver=approver, requester=requester, original_quorum=1
    )
    assert decision.refusal is refusal


@pytest.mark.parametrize("quorum", [0, -1, True])
def test_malformed_original_quorum_is_rejected(quorum: int) -> None:
    with pytest.raises(ValueError, match="quorum"):
        effective_quorum_for(_single(), quorum)


# --- profile transitions ----------------------------------------------------


def test_entering_single_operator_needs_the_multi_operator_governance_quorum() -> None:
    assert profile_transition_quorum(_multi(), _single(), governance_quorum=2) == 2
    assert profile_transition_quorum(None, _single(), governance_quorum=3) == 3


def test_single_operator_can_return_to_multi_operator_alone() -> None:
    assert profile_transition_quorum(_single(), _multi(), governance_quorum=2) == 1


def test_governance_quorum_never_below_two() -> None:
    with pytest.raises(ValueError, match=">= 2"):
        profile_transition_quorum(_multi(), _single(), governance_quorum=1)


# --- execution authority integration ----------------------------------------


def test_single_operator_reduces_irreversible_quorum_but_keeps_hil() -> None:
    baseline = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_irreversible_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=10.0,
    )
    assert baseline.decision == "hil"
    assert baseline.quorum == 2
    decision = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_irreversible_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=10.0,
        approval_profile=_single(),
    )
    assert decision.decision == "hil"
    assert decision.original_quorum == 2
    assert decision.quorum == 1
    audit = decision.as_audit_dict()
    assert audit["original_quorum"] == 2
    assert audit["effective_quorum"] == 1
    assert audit["approval_profile"]["approval_profile"] == "single-operator-production"
    assert audit["approval_profile"]["operator_principal"] == _OPERATOR


def test_multi_operator_profile_keeps_irreversible_quorum_of_two() -> None:
    decision = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_irreversible_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=10.0,
        approval_profile=_multi(),
    )
    assert decision.decision == "hil"
    assert decision.quorum == 2


def test_single_operator_never_raises_a_denial_or_shadow_cap() -> None:
    denied = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        policy_violation=True,
        approval_profile=_single(),
    )
    assert denied.decision == "deny"
    capped = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_destructive_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=10.0,
        kill_switch_engaged=True,
        approval_profile=_single(),
    )
    assert capped.decision == "shadow"


def test_single_operator_leaves_auto_decisions_unchanged() -> None:
    decision = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
        approval_profile=_single(),
    )
    assert decision.decision == "auto"
    assert decision.quorum == decision.original_quorum


def test_approval_profile_and_development_profile_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="MUST NOT both"):
        evaluate_execution_authority(
            tier=Tier.T0,
            action_type=_low_risk_at(),
            table=_table(),
            principal_role=None,
            environment="non-prod",
            approval_profile=_single(),
            development_profile={"profile_id": "unused"},
        )


# --- operator policy never raises past hard constraints ---------------------


def _allow_all() -> OperatorPolicyInput:
    return OperatorPolicyInput(
        revision_id="admission-r7",
        policy_digest="sha256:" + "b" * 64,
        outcome=OperatorPolicyOutcome.ALLOW,
    )


@pytest.mark.parametrize("level", list(AxisLevel))
@pytest.mark.parametrize("outcome", list(OperatorPolicyOutcome))
def test_operator_policy_combination_never_raises(
    level: AxisLevel, outcome: OperatorPolicyOutcome
) -> None:
    policy = replace(_allow_all(), outcome=outcome)
    assert apply_operator_policy(level, policy) <= level
    assert apply_operator_policy(level, None) is level


def test_operator_revision_allowing_a_hard_constraint_violation_still_denies() -> None:
    decision = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        policy_violation=True,
        operator_policy=_allow_all(),
        approval_profile=_single(),
    )
    assert decision.decision == "deny"
    assert decision.as_audit_dict()["operator_policy"] == {
        "revision_id": "admission-r7",
        "policy_digest": "sha256:" + "b" * 64,
        "outcome": "allow",
    }


def test_operator_allow_cannot_lift_irreversible_hil_to_auto() -> None:
    decision = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_irreversible_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=10.0,
        operator_policy=_allow_all(),
    )
    assert decision.decision == "hil"


def test_operator_policy_can_tighten_an_auto_decision() -> None:
    decision = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
        operator_policy=replace(_allow_all(), outcome=OperatorPolicyOutcome.REQUIRE_APPROVAL),
    )
    assert decision.decision == "hil"
    denied = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
        operator_policy=replace(_allow_all(), outcome=OperatorPolicyOutcome.DENY),
    )
    assert denied.decision == "deny"


def test_operator_policy_requires_a_pinned_digest() -> None:
    with pytest.raises(ValueError, match="sha256"):
        OperatorPolicyInput(
            revision_id="r", policy_digest="latest", outcome=OperatorPolicyOutcome.ALLOW
        )
