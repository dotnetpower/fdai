from __future__ import annotations

from pathlib import Path

import httpx

from fdai.delivery.azure.llm.request_target import COGNITIVE_SERVICES_SCOPE
from fdai.runtime.conversation_assurance import (
    build_azure_conversation_assurance_evaluators,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity


def test_hil_only_secondary_disables_semantic_review() -> None:
    evaluators = build_azure_conversation_assurance_evaluators(
        repo_root=Path(__file__).resolve().parents[2],
        resolved_models_path=str(Path(__file__).resolve().parents[2] / "resolved-models.json"),
        identity=StaticWorkloadIdentity(audience=COGNITIVE_SERVICES_SCOPE),
        http_client=httpx.AsyncClient(),
    )

    assert evaluators == ()
