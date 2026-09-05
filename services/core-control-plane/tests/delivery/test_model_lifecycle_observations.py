from __future__ import annotations

import base64
import hashlib
import json

import httpx
import pytest
from fdai.delivery.github.model_lifecycle_observations import (
    GitHubModelLifecycleObservationConfig,
    GitHubModelLifecycleObservationSource,
)


def _proposal() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "fdai.model-lifecycle-proposal.v3",
        "status": "proposal",
        "activation_authority": False,
        "source_models_digest": "b" * 64,
        "affected_capabilities": ["t2.reasoner.primary"],
        "changes": [],
        "deprecations": [],
        "compatibility_impact": [],
        "proposal_digest": None,
    }
    value["proposal_digest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value


@pytest.mark.asyncio
async def test_source_reads_exact_workflow_draft_head() -> None:
    proposal = _proposal()
    digest = str(proposal["proposal_digest"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls"):
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 257,
                        "draft": True,
                        "created_at": "2026-08-23T00:00:00Z",
                        "user": {"login": "github-actions[bot]"},
                        "head": {
                            "ref": f"automation/model-lifecycle-{digest[:12]}",
                            "sha": "1" * 40,
                        },
                        "base": {"ref": "main"},
                    }
                ],
            )
        if request.url.path.endswith("/pulls/257/files"):
            return httpx.Response(
                200,
                json=[{"filename": (f"config/model-lifecycle-proposals/{digest}.json")}],
            )
        assert request.url.params["ref"] == "1" * 40
        return httpx.Response(
            200,
            json={
                "encoding": "base64",
                "content": base64.b64encode(json.dumps(proposal).encode()).decode(),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        observations = await GitHubModelLifecycleObservationSource(
            config=GitHubModelLifecycleObservationConfig(owner="example", repo="fdai"),
            http_client=client,
            token="test-token",
        ).load()

    assert len(observations) == 1
    assert observations[0]["head_sha"] == "1" * 40
    assert observations[0]["proposal"] == proposal
