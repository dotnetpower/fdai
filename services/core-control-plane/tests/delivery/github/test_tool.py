from __future__ import annotations

from uuid import UUID

import httpx
from fdai.delivery.github.tool import GitHubWorkflowToolConfig, GitHubWorkflowToolExecutor
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import PublishReceipt, RemediationPr
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallRequest


class _Publisher:
    def __init__(self) -> None:
        self.requests: list[RemediationPr] = []

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        self.requests.append(pr)
        return PublishReceipt(pr_ref="example/repo#7", url="https://example.com/pr/7")


def _request(action_type: str, arguments: dict[str, object], *, mode: Mode) -> ToolCallRequest:
    return ToolCallRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="workflow-example-1",
        action_type_name=action_type,
        rule_ids=("example.rule",),
        tool_ref="example-target",
        arguments=arguments,
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
    )


async def test_shadow_records_plan_without_external_call() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    publisher = _Publisher()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        executor = GitHubWorkflowToolExecutor(
            config=GitHubWorkflowToolConfig(owner="example", repo="repo"),
            publisher=publisher,
            http_client=client,
            token="test-token",
        )
        receipt = await executor.execute(
            _request(
                "tool.open-fix-pr",
                {"target_ref": "core", "defect_kind": "control_plane_defect", "reason": "test"},
                mode=Mode.SHADOW,
            )
        )

    assert receipt.outcome is ToolCallOutcome.SUCCEEDED
    assert calls == 0
    assert publisher.requests == []


async def test_enforce_fix_tool_publishes_draft_manifest_pr() -> None:
    publisher = _Publisher()
    async with httpx.AsyncClient() as client:
        executor = GitHubWorkflowToolExecutor(
            config=GitHubWorkflowToolConfig(owner="example", repo="repo"),
            publisher=publisher,
            http_client=client,
            token="test-token",
        )
        receipt = await executor.execute(
            _request(
                "tool.open-fix-pr",
                {
                    "target_ref": "core",
                    "defect_kind": "control_plane_defect",
                    "reason": "verified defect requires a reviewed fix",
                },
                mode=Mode.ENFORCE,
            )
        )

    assert receipt.receipt_ref == "example/repo#7"
    assert publisher.requests[0].patch_path.startswith("delivery/fix-requests/")
    assert '"action_type": "tool.open-fix-pr"' in publisher.requests[0].patch


async def test_security_followup_is_idempotent_against_existing_issue() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=[
                {
                    "number": 12,
                    "html_url": "https://example.com/issues/12",
                    "body": "<!-- fdai-idempotency:workflow-example-1 -->",
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        executor = GitHubWorkflowToolExecutor(
            config=GitHubWorkflowToolConfig(owner="example", repo="repo"),
            publisher=_Publisher(),
            http_client=client,
            token="test-token",
        )
        receipt = await executor.execute(
            _request(
                "tool.file-security-followup",
                {
                    "finding_ref": "finding-1",
                    "severity": "high",
                    "reason": "security assessment requires tracked follow-up",
                },
                mode=Mode.ENFORCE,
            )
        )

    assert receipt.outcome is ToolCallOutcome.ALREADY_APPLIED
    assert receipt.receipt_ref == "example/repo#12"
