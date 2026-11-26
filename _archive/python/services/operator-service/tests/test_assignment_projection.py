from __future__ import annotations

from copy import deepcopy

import pytest
from fdai_operator_service.assignment_projection import join_assignment_case

DIGEST = "a" * 64
OPERATOR_ID = "operator-" + DIGEST[:32]
CASE_ID = "00000000-0000-0000-0000-000000000001"
PROJECTED = {"case_id": OPERATOR_ID, "state": "approved", "revision": 3}


class Source:
    def __init__(self):
        self.records = {
            f"human_assignment:operator-case:{OPERATOR_ID}": {
                "case_id": CASE_ID,
                "request_digest": DIGEST,
            },
            f"human_assignment:case:{CASE_ID}": {
                "state": "ownership_pr_open",
                "revision": 4,
                "command_receipts": [{"proposal_id": OPERATOR_ID, "request_digest": DIGEST}],
                "effect_receipts": [],
                "reviews": [],
            },
        }

    async def read_state(self, key):
        return deepcopy(self.records.get(key))


async def test_core_owned_state_replaces_presentation_without_claiming_iam_success():
    result = await join_assignment_case(Source(), PROJECTED)
    assert result["state"] == "ownership_pr_open"
    assert result["revision"] == 4
    assert result["effect_receipts"] == []
    assert result["core_case_id"] == CASE_ID
    assert result["execution_authority"] is False


async def test_missing_core_does_not_claim_an_approved_command_converged():
    source = Source()
    source.records.clear()
    result = await join_assignment_case(source, PROJECTED)
    assert result["convergence_status"] == "awaiting_core"
    assert result["state"] == "approved"
    assert result["execution_authority"] is False


async def test_mismatched_creation_cannot_project_another_case():
    source = Source()
    source.records[f"human_assignment:case:{CASE_ID}"]["command_receipts"] = []
    with pytest.raises(ValueError, match="creation"):
        await join_assignment_case(source, PROJECTED)


@pytest.mark.parametrize("kinds", [[], ["ownership"], ["iam"]])
async def test_active_requires_both_independent_effects(kinds):
    source = Source()
    case = source.records[f"human_assignment:case:{CASE_ID}"]
    case["state"] = "active"
    case["effect_receipts"] = [{"kind": kind, "receipt_ref": f"receipt:{kind}"} for kind in kinds]
    with pytest.raises(ValueError, match="both effect"):
        await join_assignment_case(source, PROJECTED)


async def test_active_can_be_observed_only_with_both_receipts():
    source = Source()
    case = source.records[f"human_assignment:case:{CASE_ID}"]
    case["state"] = "active"
    case["effect_receipts"] = [
        {"kind": kind, "receipt_ref": f"receipt:{kind}"} for kind in ("ownership", "iam")
    ]
    assert (await join_assignment_case(source, PROJECTED))["state"] == "active"
