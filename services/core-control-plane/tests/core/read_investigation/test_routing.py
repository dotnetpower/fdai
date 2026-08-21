from __future__ import annotations

import pytest
from fdai.core.read_investigation import resource_name_from_question


@pytest.mark.parametrize(
    "question",
    (
        (
            "Out of everything currently in scope, which VMs are actually up and humming "
            "right now? Please list each one with its current power state, based on read-only "
            "inventory evidence only."
        ),
        (
            "Which VMs in the currently configured Azure scope are actually up and running "
            "right now? Please show each one's current power state, drawing only on read-only "
            "inventory evidence."
        ),
    ),
)
def test_collection_evidence_qualifier_is_not_a_resource_name(question: str) -> None:
    assert resource_name_from_question(question) is None


def test_hyphenated_resource_name_remains_selectable() -> None:
    assert resource_name_from_question("What is the current state of vm-app?") == "vm-app"
