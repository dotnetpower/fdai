from __future__ import annotations

import re
from pathlib import Path

_WORKFLOW = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-dev.yml"
).read_text(encoding="utf-8")


def test_observability_request_targets_only_the_stateful_image_updater() -> None:
    assert "plan-observability-" in _WORKFLOW
    assignment = re.search(r"export TF_CLI_ARGS_plan='([^']+)'", _WORKFLOW)
    assert assignment is not None
    assert assignment.group(1).split() == [
        "-target=terraform_data.observability_analyzer_image_update"
    ]
    assert "reconcile_rca_bootstrap_state.sh observability" not in _WORKFLOW
    assert "mode=observability-analyzer" in _WORKFLOW
    assert (
        '{"terraform_data.observability_analyzer_image_update"} '
        'if "${{ startsWith(inputs.request_id, \'plan-observability-\') }}" == "true"'
    ) in _WORKFLOW
    assert "state-only updater replacement" in _WORKFLOW
    assert 'verify_deploy_convergence.sh "${{ inputs.request_id }}"' in _WORKFLOW
