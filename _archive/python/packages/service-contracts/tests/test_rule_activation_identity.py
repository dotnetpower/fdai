from __future__ import annotations

import pytest

from fdai_service_contracts.rule_activation_identity import (
    build_rule_activation_identity_context_v2,
    build_rule_activation_identity_transition_v2,
)
from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef


def _member(rule_id: str, digest_char: str) -> RuleRevisionIdentityRef:
    return RuleRevisionIdentityRef(
        rule_id=rule_id,
        rule_version="1.0.0",
        revision_digest="sha256:" + (digest_char * 64),
    )


def test_catalog_growth_does_not_change_active_generation_identity() -> None:
    active = (_member("rule.alpha", "a"),)
    first = build_rule_activation_identity_context_v2(
        catalog_revisions=active,
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=active,
    )
    second = build_rule_activation_identity_context_v2(
        catalog_revisions=(*active, _member("rule.inactive", "b")),
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=active,
    )

    assert first.catalog_manifest.manifest_digest != second.catalog_manifest.manifest_digest
    assert first.generation == second.generation


def test_active_revision_change_requires_profile_and_generation_change() -> None:
    first_member = (_member("rule.alpha", "a"),)
    second_member = (
        RuleRevisionIdentityRef(
            rule_id="rule.alpha",
            rule_version="1.1.0",
            revision_digest="sha256:" + ("b" * 64),
        ),
    )
    first = build_rule_activation_identity_context_v2(
        catalog_revisions=first_member,
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=first_member,
    )
    second = build_rule_activation_identity_context_v2(
        catalog_revisions=(*first_member, *second_member),
        profile_id="baseline",
        profile_version="1.1.0",
        active_members=second_member,
    )

    assert first.profile_snapshot.snapshot_digest != second.profile_snapshot.snapshot_digest
    assert first.generation.generation_digest != second.generation.generation_digest


def test_profile_member_must_exist_exactly_in_catalog() -> None:
    with pytest.raises(ValueError, match="absent from the catalog"):
        build_rule_activation_identity_context_v2(
            catalog_revisions=(_member("rule.alpha", "a"),),
            profile_id="baseline",
            profile_version="1.0.0",
            active_members=(_member("rule.other", "b"),),
        )


def test_profile_cannot_activate_two_revisions_of_one_rule() -> None:
    first = _member("rule.alpha", "a")
    second = RuleRevisionIdentityRef(
        rule_id=first.rule_id,
        rule_version="1.1.0",
        revision_digest="sha256:" + ("b" * 64),
    )

    with pytest.raises(ValueError, match="unique Rule ids"):
        build_rule_activation_identity_context_v2(
            catalog_revisions=(first, second),
            profile_id="baseline",
            profile_version="1.1.0",
            active_members=(first, second),
        )


def test_revision_change_requires_a_profile_version_bump() -> None:
    first_member = (_member("rule.alpha", "a"),)
    second_member = (
        RuleRevisionIdentityRef(
            rule_id="rule.alpha",
            rule_version="1.1.0",
            revision_digest="sha256:" + ("b" * 64),
        ),
    )
    source = build_rule_activation_identity_context_v2(
        catalog_revisions=first_member,
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=first_member,
    )
    target = build_rule_activation_identity_context_v2(
        catalog_revisions=(*first_member, *second_member),
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=second_member,
    )

    with pytest.raises(ValueError, match="bump the profile version"):
        build_rule_activation_identity_transition_v2(source=source, target=target)


def test_catalog_only_transition_preserves_generation_and_retained_revisions() -> None:
    active = (_member("rule.alpha", "a"),)
    source = build_rule_activation_identity_context_v2(
        catalog_revisions=active,
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=active,
    )
    target = build_rule_activation_identity_context_v2(
        catalog_revisions=(*active, _member("rule.inactive", "b")),
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=active,
    )

    transition = build_rule_activation_identity_transition_v2(source=source, target=target)

    assert source.generation == target.generation
    assert transition.source.catalog_manifest != transition.target.catalog_manifest


def test_profile_version_cannot_move_backward_to_a_different_snapshot() -> None:
    first = (_member("rule.alpha", "a"),)
    second = (
        RuleRevisionIdentityRef(
            rule_id="rule.alpha",
            rule_version="2.0.0",
            revision_digest="sha256:" + ("b" * 64),
        ),
    )
    source = build_rule_activation_identity_context_v2(
        catalog_revisions=(*first, *second),
        profile_id="baseline",
        profile_version="2.0.0",
        active_members=second,
    )
    target = build_rule_activation_identity_context_v2(
        catalog_revisions=(*first, *second),
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=first,
    )

    with pytest.raises(ValueError, match="increase the profile version"):
        build_rule_activation_identity_transition_v2(source=source, target=target)


def test_cross_profile_transition_uses_independent_version_namespaces() -> None:
    first = (_member("rule.alpha", "a"),)
    second = (_member("rule.emergency", "b"),)
    source = build_rule_activation_identity_context_v2(
        catalog_revisions=(*first, *second),
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=first,
    )
    target = build_rule_activation_identity_context_v2(
        catalog_revisions=(*first, *second),
        profile_id="emergency",
        profile_version="1.0.0",
        active_members=second,
    )

    transition = build_rule_activation_identity_transition_v2(source=source, target=target)

    assert transition.source.profile_snapshot.profile_id == "baseline"
    assert transition.target.profile_snapshot.profile_id == "emergency"


def test_cross_profile_transition_with_same_members_gets_new_generation() -> None:
    active = (_member("rule.alpha", "a"),)
    source = build_rule_activation_identity_context_v2(
        catalog_revisions=active,
        profile_id="baseline",
        profile_version="1.0.0",
        active_members=active,
    )
    target = build_rule_activation_identity_context_v2(
        catalog_revisions=active,
        profile_id="emergency",
        profile_version="1.0.0",
        active_members=active,
    )

    transition = build_rule_activation_identity_transition_v2(source=source, target=target)

    assert source.profile_snapshot.members == target.profile_snapshot.members
    assert source.generation.generation_digest != target.generation.generation_digest
    assert transition.target.profile_snapshot.profile_id == "emergency"
