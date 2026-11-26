"""Capability-separated callbacks for existing fixed-agent human-access handoffs."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fdai_service_contracts.human_access_workflow import HumanAccessHandoff, HumanAccessWorkNotice

NoticeStep = Callable[[HumanAccessWorkNotice], Awaitable[HumanAccessHandoff]]
HandoffStep = Callable[[HumanAccessHandoff], Awaitable[HumanAccessHandoff]]


@dataclass(frozen=True, slots=True)
class HumanAccessAgentBindings:
    """Independent capabilities; no agent receives peer handles or a universal workflow writer."""

    judge_request: NoticeStep
    judge_decision: NoticeStep
    judge_effect: HandoffStep
    review: HandoffStep
    prepare: HandoffStep
    record_effect: HandoffStep
    dispatch: HandoffStep
    observe: HandoffStep
    observe_notice: NoticeStep
    judge_recovery: HandoffStep | None = None
    propose_recovery: HandoffStep | None = None
    finish_recovery: HandoffStep | None = None
    resume: NoticeStep | None = None
    record_failure: HandoffStep | None = None

    @property
    def execution_bound(self) -> bool:
        """Report forward/recovery callbacks; never override mode or runtime safeguards."""
        return all(
            callable(step)
            for step in (
                self.judge_request,
                self.judge_decision,
                self.judge_effect,
                self.review,
                self.prepare,
                self.record_effect,
                self.dispatch,
                self.observe,
                self.observe_notice,
                self.judge_recovery,
                self.propose_recovery,
                self.finish_recovery,
                self.resume,
                self.record_failure,
            )
        )


__all__ = ["HumanAccessAgentBindings"]
