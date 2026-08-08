"""Contextual translation argument provenance tests."""

from __future__ import annotations

from fdai.core.conversation.contextual_translation import contextual_arguments_grounded
from fdai.core.conversation.session import Turn


def test_separator_normalization_reuses_exact_prior_subject() -> None:
    prior = (
        Turn(
            turn_id="prior",
            direction="inbound",
            content="query inventory for virtual machine",
        ),
    )

    assert contextual_arguments_grounded(
        {"resource_type": "virtual-machine"},
        utterance="show that again",
        prior_turns=prior,
    )


def test_nested_argument_absent_from_context_is_rejected() -> None:
    prior = (Turn(turn_id="prior", direction="inbound", content="simulate storage"),)

    assert not contextual_arguments_grounded(
        {"scenario": {"resource": "storage", "mode": "destructive"}},
        utterance="repeat that",
        prior_turns=prior,
    )


def test_empty_argument_mapping_is_grounded_without_invention() -> None:
    assert contextual_arguments_grounded({}, utterance="show status", prior_turns=())
