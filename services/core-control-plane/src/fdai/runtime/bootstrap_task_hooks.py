"""Production task hooks for the headless Core runtime."""

from __future__ import annotations

from fdai.runtime.bootstrap_lifecycle import (
    log_rule_generation_outbox_exit as _log_rule_generation_outbox_exit,
)
from fdai.runtime.bootstrap_lifecycle import (
    publish_rule_generation_reconciliation as _publish_rule_generation_reconciliation,
)
from fdai.runtime.bootstrap_lifecycle import (
    run_effect_reconciliation as _run_effect_reconciliation,
)
from fdai.runtime.bootstrap_lifecycle import (
    run_effect_reconciliation_request_outbox as _run_effect_reconciliation_request_outbox,
)
from fdai.runtime.bootstrap_lifecycle import (
    run_rule_generation_outbox_publisher as _run_rule_generation_outbox_publisher,
)
from fdai.runtime.bootstrap_lifecycle import (
    supervise_runtime_tasks as _supervise_runtime_tasks,
)
from fdai.runtime.bootstrap_tasks import RuntimeTaskHooks
from fdai.runtime.bootstrap_tasks import (
    schedule_semantic_turn_consumer as _schedule_semantic_turn_consumer,
)
from fdai.runtime.consumers import (
    _consume,
    _consume_canaries,
    _consume_hil_decisions,
    _consume_notification_receipts,
    _consume_operational_readiness,
    _consume_resource_changes,
    _log_pantheon_exit,
)
from fdai.runtime.control_loop import _build_irp_event_handler, _load_resource_types


def default_runtime_task_hooks() -> RuntimeTaskHooks:
    """Return the production task hooks retained as explicit test seams."""

    return RuntimeTaskHooks(
        consume=_consume,
        consume_resource_changes=_consume_resource_changes,
        consume_canaries=_consume_canaries,
        consume_hil_decisions=_consume_hil_decisions,
        consume_notification_receipts=_consume_notification_receipts,
        consume_operational_readiness=_consume_operational_readiness,
        build_irp_event_handler=_build_irp_event_handler,
        load_resource_types=_load_resource_types,
        schedule_semantic_turn_consumer=_schedule_semantic_turn_consumer,
        log_pantheon_exit=_log_pantheon_exit,
        run_effect_reconciliation=_run_effect_reconciliation,
        run_effect_reconciliation_request_outbox=(_run_effect_reconciliation_request_outbox),
        run_rule_generation_outbox_publisher=_run_rule_generation_outbox_publisher,
        log_rule_generation_outbox_exit=_log_rule_generation_outbox_exit,
        publish_rule_generation_reconciliation=_publish_rule_generation_reconciliation,
        supervise_runtime_tasks=_supervise_runtime_tasks,
    )


__all__ = ["default_runtime_task_hooks"]
