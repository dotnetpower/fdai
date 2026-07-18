"""Stable process entrypoint facade for the headless control plane."""

from fdai.runtime.bootstrap import _run, main
from fdai.runtime.configuration import (
    _attach_runtime_github_change_feed,
    _attach_runtime_knowledge_source,
    _attach_runtime_metric_provider,
    _finalize_llm_bindings,
    _new_http_client,
    _resolve_catalog_root,
    _resolve_policies_root,
    _summarize_config,
)
from fdai.runtime.consumers import (
    _authoritative_decision,
    _consume,
    _consume_canaries,
    _consume_hil_decisions,
    _log_pantheon_exit,
)
from fdai.runtime.control_loop import (
    _build_control_loop,
    _build_irp_event_handler,
    _build_workflow_coordinator,
    _pending_index_writer,
)
from fdai.runtime.delivery import (
    _build_direct_api_executor,
    _build_hil_channel,
    _build_incident_notifier,
    _build_notification_registry,
    _build_publisher,
    _build_tool_executor,
)
from fdai.runtime.providers import (
    _build_audit_store,
    _build_idempotency_store,
    _build_inventory_age_provider,
    _build_inventory_context_provider,
    _build_metering_store,
    _build_model_health_sink,
    _build_ontology_instance_store,
    _build_operator_memory_store,
    _build_pattern_library,
    _build_process_store,
    _build_resource_lock,
)

__all__ = [
    "_attach_runtime_github_change_feed",
    "_attach_runtime_knowledge_source",
    "_attach_runtime_metric_provider",
    "_authoritative_decision",
    "_build_audit_store",
    "_build_control_loop",
    "_build_direct_api_executor",
    "_build_hil_channel",
    "_build_idempotency_store",
    "_build_incident_notifier",
    "_build_notification_registry",
    "_build_inventory_age_provider",
    "_build_inventory_context_provider",
    "_build_irp_event_handler",
    "_build_metering_store",
    "_build_model_health_sink",
    "_build_ontology_instance_store",
    "_build_operator_memory_store",
    "_build_pattern_library",
    "_build_process_store",
    "_build_publisher",
    "_build_resource_lock",
    "_build_tool_executor",
    "_build_workflow_coordinator",
    "_consume",
    "_consume_canaries",
    "_consume_hil_decisions",
    "_finalize_llm_bindings",
    "_log_pantheon_exit",
    "_new_http_client",
    "_pending_index_writer",
    "_resolve_catalog_root",
    "_resolve_policies_root",
    "_run",
    "_summarize_config",
    "main",
]

if __name__ == "__main__":  # pragma: no cover - process entrypoint
    raise SystemExit(main())
