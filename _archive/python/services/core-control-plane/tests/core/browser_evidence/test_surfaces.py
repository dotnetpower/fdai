from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.browser_evidence.surfaces import (
    BrowserEvidenceConsoleTool,
    BrowserEvidenceWorkflowStepDispatcher,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.notifications.matrix import load_matrix_from_mapping
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.workflow.approval import WorkflowApprovalPlanner
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.shared.contracts.models import (
    Mode,
    PromotionGate,
    Workflow,
    WorkflowStep,
    WorkflowStepKind,
    WorkflowTrigger,
    WorkflowTriggerKind,
)
from fdai.shared.providers.browser_evidence import (
    BrowserCaptureRequest,
    BrowserEvidenceReceipt,
)
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class CaptureService:
    def __init__(self, status: str = "captured") -> None:
        self.status = status
        self.requests: list[BrowserCaptureRequest] = []

    async def capture(self, request: BrowserCaptureRequest) -> BrowserEvidenceReceipt:
        self.requests.append(request)
        captured = self.status == "captured"
        return BrowserEvidenceReceipt(
            request_id=request.request_id,
            status=self.status,  # type: ignore[arg-type]
            artifact_id="sha256:" + "a" * 64 if captured else None,
            content_digest="a" * 64 if captured else None,
            chain_of_custody_audit_ref="audit:1" if captured else None,
            reason=None if captured else "adapter_failure",
        )


class ActionDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch(self, **_kwargs: object) -> str:
        self.calls += 1
        return "action:1"


def _principal() -> Principal:
    return Principal(id="reader-1", role=Role.READER, display_name="Reader")


def _workflow() -> Workflow:
    return Workflow(
        schema_version="1.0.0",
        name="browser-evidence-flow",
        version="1.0.0",
        trigger=WorkflowTrigger(kind=WorkflowTriggerKind.SIGNAL, signal_type="evidence.request"),
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        steps=[
            WorkflowStep(
                id="capture",
                kind=WorkflowStepKind.EVIDENCE,
                params={
                    "policy_id": "dashboard",
                    "policy_version": 1,
                    "source_url": "https://dashboard.example/evidence",
                    "stable_selectors": "main,#summary",
                },
            )
        ],
    )


def _orchestrator(
    *,
    action_dispatcher: ActionDispatcher,
) -> WorkflowOrchestrator:
    planner = WorkflowApprovalPlanner(
        action_types={},
        group_mapping=GroupMapping(
            reader_group_id="readers",
            contributor_group_id="contributors",
            approver_group_id="approvers",
            owner_group_id="owners",
            break_glass_group_id="break-glass",
        ),
        matrix=load_matrix_from_mapping(
            {
                "matrix": {
                    "version": 1,
                    "default_route": "hil_approval",
                    "routes": {
                        "hil_approval": {
                            "trust_tier": "a1_hil_approval",
                            "primary": "audit-only",
                            "fallback": [],
                        }
                    },
                }
            }
        ),
    )
    return WorkflowOrchestrator(
        planner=planner,
        action_types={},
        audit_store=InMemoryStateStore(),
        process_store=InMemoryProcessRuntimeStore(),
        action_dispatcher=action_dispatcher,
    )


async def test_console_tool_submits_typed_untrusted_capture_request() -> None:
    service = CaptureService()
    tool = BrowserEvidenceConsoleTool(service)  # type: ignore[arg-type]

    result = await tool.call(
        arguments={
            "policy_id": "dashboard",
            "policy_version": 1,
            "source_url": "https://dashboard.example/evidence",
            "stable_selectors": "main,#summary",
        },
        principal=_principal(),
    )

    assert tool.side_effect_class == "read"
    assert result.status == "ok"
    assert result.data["untrusted"] is True
    assert result.data["can_authorize_action"] is False
    assert service.requests[0].stable_selectors == ("main", "#summary")
    public = {name for name in dir(tool) if not name.startswith("_")}
    assert "click" not in public
    assert "fill" not in public
    assert "press" not in public
    assert "clipboard" not in public


async def test_evidence_workflow_step_never_calls_action_dispatcher() -> None:
    capture = CaptureService()
    action = ActionDispatcher()
    orchestrator = _orchestrator(action_dispatcher=action).with_evidence_dispatcher(
        BrowserEvidenceWorkflowStepDispatcher(capture)  # type: ignore[arg-type]
    )

    result = await orchestrator.run(
        _workflow(),
        target_resource_id="resource:test",
        trigger_ts=datetime(2026, 7, 21, 12, tzinfo=UTC),
    )

    assert result.status.value == "succeeded"
    assert result.step_results[0].reason == "browser_evidence_captured"
    assert action.calls == 0
    assert len(capture.requests) == 1


async def test_unavailable_evidence_fails_workflow_closed() -> None:
    capture = CaptureService(status="unavailable")
    action = ActionDispatcher()
    orchestrator = _orchestrator(action_dispatcher=action).with_evidence_dispatcher(
        BrowserEvidenceWorkflowStepDispatcher(capture)  # type: ignore[arg-type]
    )

    result = await orchestrator.run(
        _workflow(),
        target_resource_id="resource:test",
        trigger_ts=datetime(2026, 7, 21, 13, tzinfo=UTC),
    )

    assert result.status.value == "failed"
    assert result.step_results[0].reason == "evidence_unavailable:adapter_failure"
    assert action.calls == 0
