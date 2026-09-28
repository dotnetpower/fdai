"""Typed ActionType proposal contracts and reviewed-effect scratch derivation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.assurance_twin import (
    DeclaredPropertyEffect,
    PredictedChangeSet,
    ProposalReviewUnavailableError,
    ProposalWhatIfResult,
    ReviewedActionTypeEffect,
    ReviewedEffectCatalog,
    TypedActionProposal,
    WhatIfStatus,
    build_baseline_projection,
    derive_predicted_change_set,
)
from fdai.core.assurance_twin.proposal_effects import require_assessed_effect
from fdai.core.assurance_twin.typed_proposal import WHAT_IF_SOURCE_AUTHORITY
from fdai.core.quality_gate.deterministic_evidence import (
    DeterministicEvidenceKind,
    expected_evidence_authority,
)
from fdai.shared.providers.projection import ResourceRef

_NOW = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
_REVISION = "sha256:" + "a" * 64
_TARGET = ResourceRef("object-storage", "storage-a")
_OTHER = ResourceRef("object-storage", "storage-b")


def _proposal(**parameters: object) -> TypedActionProposal:
    return TypedActionProposal.create(
        action_type="ops.set-public-access",
        action_type_version="1.0.0",
        targets=(_TARGET,),
        parameters=parameters or {"public_access": "disabled"},
    )


def _effect(**overrides: object) -> ReviewedActionTypeEffect:
    values: dict[str, object] = {
        "action_type": "ops.set-public-access",
        "action_type_version": "1.0.0",
        "target_resource_types": ("object-storage",),
        "property_effects": (DeclaredPropertyEffect("public_access", parameter="public_access"),),
        "review_ref": "effect-review:ops.set-public-access@1.0.0",
    }
    values.update(overrides)
    return ReviewedActionTypeEffect(**values)  # type: ignore[arg-type]


def _what_if(proposal: TypedActionProposal, **overrides: object) -> ProposalWhatIfResult:
    values: dict[str, object] = {
        "proposal_digest": proposal.proposal_digest,
        "status": WhatIfStatus.PASSED,
        "complete": True,
        "synthetic": False,
        "source_authority": WHAT_IF_SOURCE_AUTHORITY,
        "producer_id": "what-if-producer",
        "observed_at": _NOW - timedelta(minutes=1),
        "expires_at": _NOW + timedelta(minutes=10),
        "affected_targets": proposal.targets,
        "evidence_refs": ("what-if-receipt:1",),
    }
    values.update(overrides)
    return ProposalWhatIfResult(**values)  # type: ignore[arg-type]


def _projection() -> object:
    return build_baseline_projection(
        (
            (_TARGET, {"public_access": "enabled", "tier": "hot"}),
            (_OTHER, {"public_access": "enabled"}),
        )
    )


def test_what_if_authority_matches_the_quality_gate_what_if_family() -> None:
    assert WHAT_IF_SOURCE_AUTHORITY == expected_evidence_authority(
        DeterministicEvidenceKind.WHAT_IF
    )


def test_proposal_is_content_addressed_and_forgery_fails_closed() -> None:
    proposal = _proposal()
    assert proposal.proposal_ref == "action-proposal:" + proposal.proposal_digest[7:]
    assert proposal == _proposal()
    assert proposal.proposal_digest != _proposal(public_access="enabled").proposal_digest
    with pytest.raises(ValueError, match="digest does not match"):
        replace(proposal, proposal_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="parameters digest"):
        replace(proposal, parameters_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="canonical JSON"):
        replace(proposal, parameters_json='{"public_access": "disabled"}')
    with pytest.raises(ValueError, match="targets"):
        TypedActionProposal.create(
            action_type="ops.set-public-access",
            action_type_version="1.0.0",
            targets=(_TARGET, _TARGET),
            parameters={},
        )
    with pytest.raises(ValueError, match="ActionType id"):
        TypedActionProposal.create(
            action_type="Ops Set Access",
            action_type_version="1.0.0",
            targets=(_TARGET,),
            parameters={},
        )


def test_reviewed_effect_derives_exact_scratch_change_for_targets_only() -> None:
    proposal = _proposal()
    what_if = _what_if(proposal)
    change = derive_predicted_change_set(
        proposal=proposal,
        what_if=what_if,
        effect=_effect(),
        projection=_projection(),  # type: ignore[arg-type]
        inventory_revision=_REVISION,
        now=_NOW,
    )

    assert [diff.target for diff in change.diffs] == [_TARGET]
    assert change.diffs[0].kind == "update"
    assert change.scratch.resources.keys() == {_TARGET}
    assert change.scratch.properties(_TARGET) == {"public_access": "disabled", "tier": "hot"}
    replay = derive_predicted_change_set(
        proposal=proposal,
        what_if=what_if,
        effect=_effect(),
        projection=_projection(),  # type: ignore[arg-type]
        inventory_revision=_REVISION,
        now=_NOW + timedelta(minutes=1),
    )
    assert replay.change_digest == change.change_digest
    other_revision = derive_predicted_change_set(
        proposal=proposal,
        what_if=what_if,
        effect=_effect(),
        projection=_projection(),  # type: ignore[arg-type]
        inventory_revision="sha256:" + "b" * 64,
        now=_NOW,
    )
    assert other_revision.change_digest != change.change_digest


def _case(name: str) -> tuple[dict[str, object], str]:
    proposal = _proposal()
    other = _proposal(public_access="enabled")
    cases: dict[str, tuple[dict[str, object], str]] = {
        "unsupported_action_type": ({"effect": None}, "effect_model_unavailable"),
        "other_version": (
            {"effect": _effect(action_type_version="2.0.0")},
            "effect_model_mismatch",
        ),
        "missing_what_if": ({"what_if": None}, "what_if_missing"),
        "other_proposal": ({"what_if": _what_if(other)}, "what_if_conflict"),
        "other_targets": (
            {"what_if": _what_if(proposal, affected_targets=(_OTHER,))},
            "what_if_conflict",
        ),
        "status_conflict": (
            {"what_if": _what_if(proposal, status=WhatIfStatus.CONFLICT)},
            "what_if_conflict",
        ),
        "failed": ({"what_if": _what_if(proposal, status=WhatIfStatus.FAILED)}, "what_if_failed"),
        "unavailable": (
            {"what_if": _what_if(proposal, status=WhatIfStatus.UNAVAILABLE)},
            "what_if_unavailable",
        ),
        "incomplete": ({"what_if": _what_if(proposal, complete=False)}, "what_if_incomplete"),
        "no_receipts": ({"what_if": _what_if(proposal, evidence_refs=())}, "what_if_incomplete"),
        "synthetic": ({"what_if": _what_if(proposal, synthetic=True)}, "what_if_synthetic"),
        "foreign_authority": (
            {"what_if": _what_if(proposal, source_authority="security_scanner")},
            "what_if_authority_mismatch",
        ),
        "stale": (
            {"what_if": _what_if(proposal, expires_at=_NOW - timedelta(seconds=1))},
            "what_if_stale",
        ),
        "unbounded_window": (
            {"what_if": _what_if(proposal, observed_at=_NOW - timedelta(minutes=40))},
            "what_if_stale",
        ),
        "future": (
            {"what_if": _what_if(proposal, observed_at=_NOW + timedelta(seconds=1))},
            "what_if_from_future",
        ),
        "cross_revision_target": (
            {"projection": build_baseline_projection(((_OTHER, {}),))},
            "target_outside_revision",
        ),
        "unsupported_target_type": (
            {"effect": _effect(target_resource_types=("sql-database",))},
            "target_type_unsupported",
        ),
        "missing_parameter": (
            {
                "effect": _effect(
                    property_effects=(DeclaredPropertyEffect("tier", parameter="tier"),),
                    inert_parameters=("public_access",),
                )
            },
            "parameter_missing",
        ),
        "undeclared_parameter": (
            {
                "effect": _effect(
                    property_effects=(
                        DeclaredPropertyEffect("public_access", constant_json='"disabled"'),
                    )
                )
            },
            "parameter_undeclared",
        ),
    }
    return cases[name]


@pytest.mark.parametrize(
    "name",
    [
        "unsupported_action_type",
        "other_version",
        "missing_what_if",
        "other_proposal",
        "other_targets",
        "status_conflict",
        "failed",
        "unavailable",
        "incomplete",
        "no_receipts",
        "synthetic",
        "foreign_authority",
        "stale",
        "unbounded_window",
        "future",
        "cross_revision_target",
        "unsupported_target_type",
        "missing_parameter",
        "undeclared_parameter",
    ],
)
def test_every_evidence_gap_is_an_explicit_unavailable_reason(name: str) -> None:
    proposal = _proposal()
    overrides, reason = _case(name)
    arguments: dict[str, object] = {
        "proposal": proposal,
        "what_if": _what_if(proposal),
        "effect": _effect(),
        "projection": _projection(),
        "inventory_revision": _REVISION,
        "now": _NOW,
    }
    arguments.update(overrides)
    with pytest.raises(ProposalReviewUnavailableError) as raised:
        derive_predicted_change_set(**arguments)  # type: ignore[arg-type]
    assert raised.value.reason_code == reason


def test_effect_declarations_and_catalog_reject_ambiguity() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        DeclaredPropertyEffect("public_access")
    with pytest.raises(ValueError, match="top-level"):
        DeclaredPropertyEffect("network.public_access", constant_json='"disabled"')
    with pytest.raises(ValueError, match="canonical JSON"):
        DeclaredPropertyEffect("public_access", constant_json='"disabled" ')
    with pytest.raises(ValueError, match="review"):
        _effect(review_ref=" ")
    with pytest.raises(ValueError, match="disjoint"):
        _effect(inert_parameters=("public_access",))
    with pytest.raises(ValueError, match="ambiguous"):
        ReviewedEffectCatalog((_effect(), _effect(review_ref="effect-review:duplicate")))
    catalog = ReviewedEffectCatalog((_effect(),))
    assert catalog.effect_for("ops.set-public-access", "1.0.0") == _effect()
    assert catalog.effect_for("ops.set-public-access", "1.0.1") is None
    assert _effect().effect_digest != _effect(review_ref="effect-review:other").effect_digest


@pytest.mark.parametrize(
    ("declared", "assessed"),
    [
        (("public_access",), True),
        (("public_access.mode",), False),
        (("tier", "public_access"), True),
        (("public",), False),
        (("public_access_mode",), False),
        (("tier",), False),
        ((), False),
    ],
)
def test_every_written_property_needs_a_declared_rule_input(
    declared: tuple[str, ...], assessed: bool
) -> None:
    proposal = _proposal()
    change = derive_predicted_change_set(
        proposal=proposal,
        what_if=_what_if(proposal),
        effect=_effect(),
        projection=_projection(),  # type: ignore[arg-type]
        inventory_revision=_REVISION,
        now=_NOW,
    )

    if assessed:
        require_assessed_effect(change, ((_TARGET, declared),))
        return
    with pytest.raises(ProposalReviewUnavailableError) as raised:
        require_assessed_effect(change, ((_TARGET, declared),))
    assert raised.value.reason_code == "effect_unassessed"


def test_inputs_declared_only_for_another_resource_do_not_assess_the_target() -> None:
    proposal = _proposal()
    change = derive_predicted_change_set(
        proposal=proposal,
        what_if=_what_if(proposal),
        effect=_effect(),
        projection=_projection(),  # type: ignore[arg-type]
        inventory_revision=_REVISION,
        now=_NOW,
    )

    with pytest.raises(ProposalReviewUnavailableError, match="effect_unassessed"):
        require_assessed_effect(change, ((_OTHER, ("public_access",)),))


def _network_change(current: object, predicted: object) -> PredictedChangeSet:
    proposal = TypedActionProposal.create(
        action_type="ops.set-network-acls",
        action_type_version="1.0.0",
        targets=(_TARGET,),
        parameters={"network_acls": predicted},
    )
    return derive_predicted_change_set(
        proposal=proposal,
        what_if=_what_if(proposal),
        effect=_effect(
            action_type="ops.set-network-acls",
            property_effects=(DeclaredPropertyEffect("network_acls", parameter="network_acls"),),
            review_ref="effect-review:ops.set-network-acls@1.0.0",
        ),
        projection=build_baseline_projection(((_TARGET, {"network_acls": current}),)),
        inventory_revision=_REVISION,
        now=_NOW,
    )


@pytest.mark.parametrize(
    ("current", "predicted", "declared", "assessed"),
    [
        (
            {"default_action": "Allow"},
            {"default_action": "Deny", "ip_rules": ["0.0.0.0/0"]},
            ("network_acls.default_action",),
            False,
        ),
        (
            {"default_action": "Allow"},
            {"default_action": "Deny", "ip_rules": ["0.0.0.0/0"]},
            ("network_acls",),
            True,
        ),
        (
            {"default_action": "Allow", "ip_rules": []},
            {"default_action": "Deny", "ip_rules": []},
            ("network_acls.default_action",),
            True,
        ),
        (
            {"default_action": "Allow", "ip_rules": []},
            {"default_action": "Deny", "ip_rules": []},
            ("network_acls.ip_rules",),
            False,
        ),
        (
            {"default_action": "Allow", "bypass": "AzureServices"},
            {"default_action": "Allow"},
            ("network_acls.default_action",),
            False,
        ),
        (
            {"default_action": "Allow", "bypass": "AzureServices"},
            {"default_action": "Allow"},
            ("network_acls.bypass",),
            True,
        ),
        ({"default_action": "Allow"}, "Deny", ("network_acls.default_action",), False),
        ({"default_action": "Allow"}, "Deny", ("network_acls",), True),
        ({"default_action": "Allow"}, {"default_action": "Allow"}, (), True),
    ],
)
def test_every_changed_leaf_needs_a_covering_rule_input(
    current: object, predicted: object, declared: tuple[str, ...], assessed: bool
) -> None:
    change = _network_change(current, predicted)

    if assessed:
        require_assessed_effect(change, ((_TARGET, declared),))
        return
    with pytest.raises(ProposalReviewUnavailableError, match="effect_unassessed"):
        require_assessed_effect(change, ((_TARGET, declared),))
