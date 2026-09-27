"""Adversarial coverage for the full-authority development contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.shared.contracts.development_authority import (
    development_authority_audit,
    evaluate_development_authority,
    revalidate_development_authority,
)
from fdai.shared.contracts.models.development_authority import (
    DevelopmentActionBinding,
    DevelopmentActionConfirmation,
    DevelopmentActionSafeguards,
    DevelopmentAuthorityScope,
    DevelopmentBindingVerification,
    FullAuthorityDevelopmentProfile,
    RegisteredDevelopmentAction,
    authority_text_digest,
    canonical_authority_digest,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingRequest,
    resolve_development_binding,
)
from jsonschema import Draft202012Validator

NOW = datetime(2026, 9, 27, 3, 55, tzinfo=UTC)
SOURCE_REVISION = "a" * 40


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _profile(
    *,
    now: datetime = NOW,
    resource_groups: tuple[str, ...] = (_digest("3"),),
    action_type: str = "ops.restart-service",
    action_type_version: str = "1.0.0",
    action_type_digest: str = _digest("4"),
) -> FullAuthorityDevelopmentProfile:
    return FullAuthorityDevelopmentProfile(
        profile_id="dev.full-authority",
        scope=DevelopmentAuthorityScope(
            tenant_digest=_digest("1"),
            subscription_digest=_digest("2"),
            resource_group_digests=resource_groups,
        ),
        classification="disposable_development",
        owner_principal="human:owner",
        executor_principal="identity:thor-executor",
        valid_from=now - timedelta(hours=1),
        valid_until=now + timedelta(hours=1),
        source_revision=SOURCE_REVISION,
        catalog_revision="catalog@1.0.0",
        policy_revision="risk-policy@1.0.0",
        registered_actions=(
            RegisteredDevelopmentAction(
                action_type=action_type,
                version=action_type_version,
                action_type_digest=action_type_digest,
            ),
        ),
    )


def _binding(
    profile: FullAuthorityDevelopmentProfile,
    *,
    action_id: str = "action:one",
    target: str = "resource:one",
    params: dict[str, object] | None = None,
    scope: DevelopmentAuthorityScope | None = None,
    source_revision: str | None = None,
    dry_run_digest: str | None = None,
    observer: str = "identity:heimdall-observer",
    action_type: str = "ops.restart-service",
    action_type_version: str = "1.0.0",
    action_type_digest: str = _digest("4"),
    target_revision: str = "target-revision@1",
    idempotency_key: str = "stable-action-one",
    rollback_contract: str = "scripted",
) -> DevelopmentActionBinding:
    target_digest = authority_text_digest(target)
    action_params = {"restart": True} if params is None else params
    return DevelopmentActionBinding.build(
        action_type=action_type,
        action_type_version=action_type_version,
        action_type_digest=action_type_digest,
        action_id=action_id,
        target_digest=target_digest,
        target_revision=target_revision,
        scope=scope or profile.scope,
        source_revision=source_revision or profile.source_revision,
        catalog_revision=profile.catalog_revision,
        policy_revision=profile.policy_revision,
        params_digest=canonical_authority_digest(action_params),
        dry_run_digest=dry_run_digest or _digest("5"),
        requester_principal=profile.owner_principal,
        executor_principal=profile.executor_principal,
        safeguards=DevelopmentActionSafeguards(
            stop_condition_digest=_digest("6"),
            rollback_contract_digest=authority_text_digest(rollback_contract),
            rollback_test_digest=_digest("7"),
            blast_radius_digest=_digest("8"),
            logical_target_lock_digest=target_digest,
            idempotency_key=idempotency_key,
            two_phase_audit=True,
            audit_contract_digest=_digest("9"),
            observer_principal=observer,
            observer_source_digest=_digest("b"),
        ),
    )


def _confirmation(
    profile: FullAuthorityDevelopmentProfile,
    binding: DevelopmentActionBinding,
    *,
    authenticated_at: datetime | None = None,
    confirmed_at: datetime | None = None,
) -> DevelopmentActionConfirmation:
    confirmed = confirmed_at or NOW - timedelta(seconds=30)
    return DevelopmentActionConfirmation(
        confirmation_id="confirm.action-one",
        profile_digest=profile.digest,
        binding=binding,
        authenticated_principal=profile.owner_principal,
        authenticated_role="Owner",
        authentication_evidence_digest=_digest("c"),
        authenticated_at=authenticated_at or confirmed - timedelta(seconds=30),
        confirmed_by=profile.owner_principal,
        confirmed_at=confirmed,
        expires_at=max(
            confirmed + timedelta(minutes=4),
            NOW + timedelta(minutes=1),
        ),
        explicit_confirmation=True,
    )


def _verification(
    binding: DevelopmentActionBinding,
    *,
    now: datetime = NOW,
) -> DevelopmentBindingVerification:
    return DevelopmentBindingVerification(
        binding=binding,
        source_id="deployment.authority-source",
        source_revision="authority-source@1",
        verification_receipt_digest=_digest("d"),
        verified_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=5),
        authoritative=True,
    )


class _BindingSource:
    def __init__(self, verification: DevelopmentBindingVerification) -> None:
        self.verification = verification
        self.requests: list[DevelopmentAuthorityBindingRequest] = []

    def verify(
        self,
        request: DevelopmentAuthorityBindingRequest,
        *,
        now: datetime,
    ) -> DevelopmentBindingVerification:
        del now
        self.requests.append(request)
        return self.verification


def _binding_request(
    *,
    action_type: str = "ops.restart-service",
    action_id: str = "action:one",
    target: str = "resource:one",
    params: dict[str, object] | None = None,
    requester: str = "human:owner",
    executor: str = "identity:thor-executor",
    idempotency_key: str = "stable-action-one",
    rollback_contract: str = "scripted",
) -> DevelopmentAuthorityBindingRequest:
    return DevelopmentAuthorityBindingRequest.from_action(
        action_type=action_type,
        action_id=action_id,
        target_ref=target,
        params={"restart": True} if params is None else params,
        requester_principal=requester,
        executor_principal=executor,
        idempotency_key=idempotency_key,
        rollback_contract=rollback_contract,
    )


def test_exact_owner_confirmation_derives_one_effective_quorum() -> None:
    profile = _profile()
    binding = _binding(profile)
    confirmation = _confirmation(profile, binding)
    verification = _verification(binding)

    decision = evaluate_development_authority(
        profile,
        confirmation,
        verification,
        now=NOW,
        original_quorum=2,
    )

    assert decision.eligible
    assert decision.grant is not None
    assert decision.grant.original_quorum == 2
    assert decision.grant.effective_quorum == 1
    audit = development_authority_audit(decision)
    assert audit["owner_principal"] == "human:owner"
    assert audit["executor_principal"] == "identity:thor-executor"
    assert "approvers" not in audit

    schema = PackageResourceSchemaRegistry().get("authority/full-authority-development")
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        {
            "schema_version": "1.0.0",
            "confirmation": confirmation.model_dump(mode="json"),
            "binding_verification": verification.model_dump(mode="json"),
            "grant": decision.grant.model_dump(mode="json"),
        }
    )


def test_trusted_source_is_required_and_must_match_actual_operation() -> None:
    profile = _profile()
    binding = _binding(profile)
    source = _BindingSource(_verification(binding))
    request = _binding_request()

    assert resolve_development_binding(source, request, now=NOW).binding == binding
    with pytest.raises(ValueError, match="source is unavailable"):
        resolve_development_binding(None, request, now=NOW)
    with pytest.raises(ValueError, match="current operation"):
        resolve_development_binding(
            source,
            _binding_request(target="resource:changed"),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("profile_present", "confirmation_present", "reason"),
    [
        (False, False, "profile_absent"),
        (True, False, "confirmation_absent"),
    ],
)
def test_absent_authority_fails_closed(
    profile_present: bool,
    confirmation_present: bool,
    reason: str,
) -> None:
    profile = _profile()
    binding = _binding(profile)
    confirmation = _confirmation(profile, binding)
    decision = evaluate_development_authority(
        profile if profile_present else None,
        confirmation if confirmation_present else None,
        _verification(binding),
        now=NOW,
        original_quorum=1,
    )
    assert not decision.eligible
    assert decision.reason_code == reason


def test_expired_and_scope_escaping_evidence_fails_closed() -> None:
    profile = _profile()
    binding = _binding(profile)
    confirmation = _confirmation(profile, binding)
    expired = profile.model_copy(update={"valid_until": NOW})
    assert (
        evaluate_development_authority(
            expired,
            confirmation,
            _verification(binding),
            now=NOW,
            original_quorum=1,
        ).reason_code
        == "profile_expired"
    )

    escaping_scope = DevelopmentAuthorityScope(
        tenant_digest=profile.scope.tenant_digest,
        subscription_digest=profile.scope.subscription_digest,
        resource_group_digests=(_digest("d"),),
    )
    escaped = _binding(profile, scope=escaping_scope)
    escaped_confirmation = _confirmation(profile, escaped)
    assert (
        evaluate_development_authority(
            profile,
            escaped_confirmation,
            _verification(escaped),
            now=NOW,
            original_quorum=1,
        ).reason_code
        == "scope_escape"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"classification": "production"},
        {"owner_principal": "identity:thor-executor"},
        {"registered_actions": []},
    ],
)
def test_malformed_non_disposable_or_identity_profile_is_rejected(
    mutation: dict[str, object],
) -> None:
    raw = _profile().model_dump(mode="json")
    raw.update(mutation)
    decision = evaluate_development_authority(
        raw,
        _confirmation(_profile(), _binding(_profile())),
        _verification(_binding(_profile())),
        now=NOW,
        original_quorum=1,
    )
    assert not decision.eligible
    assert decision.reason_code == "authority_evidence_malformed"


@pytest.mark.parametrize(
    ("authenticated_delta", "confirmed_delta", "reason"),
    [
        (timedelta(minutes=11), timedelta(minutes=4), "authentication_stale"),
        (timedelta(minutes=7), timedelta(minutes=6), "confirmation_stale"),
    ],
)
def test_stale_authentication_or_confirmation_fails_closed(
    authenticated_delta: timedelta,
    confirmed_delta: timedelta,
    reason: str,
) -> None:
    profile = _profile()
    binding = _binding(profile)
    confirmation = _confirmation(
        profile,
        binding,
        authenticated_at=NOW - authenticated_delta,
        confirmed_at=NOW - confirmed_delta,
    )
    decision = evaluate_development_authority(
        profile,
        confirmation,
        _verification(binding),
        now=NOW,
        original_quorum=1,
    )
    assert not decision.eligible
    assert decision.reason_code == reason


@pytest.mark.parametrize(
    "changed",
    [
        "action_type",
        "action",
        "action_digest",
        "target",
        "revision",
        "scope",
        "params",
        "dry_run",
    ],
)
def test_changed_exact_binding_cannot_reuse_confirmation(changed: str) -> None:
    profile = _profile(resource_groups=())
    original = _binding(profile)
    confirmation = _confirmation(profile, original)
    values: dict[str, object] = {}
    if changed == "action_type":
        changed_binding = original.model_copy(update={"action_type": "ops.other"})
    elif changed == "action_digest":
        changed_binding = original.model_copy(update={"action_digest": _digest("f")})
    elif changed == "action":
        values["action_id"] = "action:two"
    elif changed == "target":
        values["target"] = "resource:two"
    elif changed == "revision":
        values["source_revision"] = "b" * 40
    elif changed == "scope":
        values["scope"] = DevelopmentAuthorityScope(
            tenant_digest=profile.scope.tenant_digest,
            subscription_digest=profile.scope.subscription_digest,
            resource_group_digests=(_digest("d"),),
        )
    elif changed == "params":
        values["params"] = {"restart": False}
    else:
        values["dry_run_digest"] = _digest("e")
    if changed not in {"action_type", "action_digest"}:
        changed_binding = _binding(profile, **values)
    verification: DevelopmentBindingVerification | dict[str, object]
    if changed in {"action_type", "action_digest"}:
        verification = {
            **_verification(original).model_dump(mode="json"),
            "binding": changed_binding.model_dump(mode="json"),
        }
    else:
        verification = _verification(changed_binding)
    decision = evaluate_development_authority(
        profile,
        confirmation,
        verification,
        now=NOW,
        original_quorum=2,
    )
    assert not decision.eligible
    assert decision.reason_code == (
        "authority_evidence_malformed"
        if changed in {"action_type", "action_digest"}
        else "action_binding_mismatch"
    )


@pytest.mark.parametrize(
    "missing",
    [
        "stop_condition_digest",
        "rollback_test_digest",
        "blast_radius_digest",
        "logical_target_lock_digest",
        "idempotency_key",
        "two_phase_audit",
        "audit_contract_digest",
        "observer_principal",
    ],
)
def test_missing_safeguard_is_malformed(missing: str) -> None:
    profile = _profile()
    binding = _binding(profile)
    raw = binding.model_dump(mode="json")
    del raw["safeguards"][missing]
    decision = evaluate_development_authority(
        profile,
        _confirmation(profile, binding),
        {
            **_verification(binding).model_dump(mode="json"),
            "binding": raw,
        },
        now=NOW,
        original_quorum=1,
    )
    assert not decision.eligible
    assert decision.reason_code == "authority_evidence_malformed"


def test_executor_cannot_be_observer_and_grant_cannot_be_substituted() -> None:
    profile = _profile()
    with pytest.raises(ValueError, match="observer and executor"):
        _binding(profile, observer=profile.executor_principal)
    with pytest.raises(ValueError, match="observer and requester"):
        _binding(profile, observer=profile.owner_principal)
    raw = _binding(profile).model_dump(mode="json")
    raw["safeguards"]["logical_target_lock_digest"] = _digest("e")
    with pytest.raises(ValueError, match="logical target lock"):
        DevelopmentActionBinding.model_validate(raw)

    binding = _binding(profile)
    confirmation = _confirmation(profile, binding)
    decision = evaluate_development_authority(
        profile,
        confirmation,
        _verification(binding),
        now=NOW,
        original_quorum=2,
    )
    assert decision.grant is not None
    substituted = decision.grant.model_copy(update={"action_binding_digest": _digest("f")})
    replay = revalidate_development_authority(
        profile,
        confirmation,
        _verification(binding),
        substituted,
        now=NOW,
        original_quorum=2,
    )
    assert not replay.eligible
    assert replay.reason_code == "grant_mismatch"
