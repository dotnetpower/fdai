import type { AksCommerceProjection } from "../api-aks-commerce";

export function sampleAksCommerce(
  serviceId: "catalog-browse" | "order-fulfillment",
): AksCommerceProjection {
  const order = serviceId === "order-fulfillment";
  return {
    assessment_id: `sha256:${"a".repeat(64)}`,
    service_id: serviceId,
    status: order ? "order_backlog" : "healthy",
    summary: order
      ? "Order fulfillment has a growing order backlog."
      : "Catalog browse is healthy for the assessed window.",
    observed_at: "2026-09-17T00:00:00Z",
    window_start: "2026-09-16T23:55:00Z",
    window_end: "2026-09-17T00:00:00Z",
    complete: true,
    synthetic: true,
    affected_workload_ids: order ? ["order-processor"] : [],
    dependency_path: order
      ? ["storefront", "order-api", "order-queue", "order-processor", "order-store"]
      : ["storefront", "product-api"],
    workloads: (order
      ? ["storefront", "order-api", "order-queue", "order-processor", "order-store"]
      : ["storefront", "product-api"]).map((workloadId) => ({
        workload_id: workloadId,
        display_name: workloadId.replaceAll("-", " "),
        resource_ref: `resource:${workloadId}`,
        ready: workloadId !== "order-processor",
        revision: "revision-1",
        evidence_state: "complete",
      })),
    metrics: order ? [
      {
        name: "stream.active_messages",
        unit: "count",
        current: 125,
        previous: 20,
        source_ref: "source:service-bus",
        observed_at: "2026-09-17T00:00:00Z",
        state: "complete",
        synthetic: false,
      },
      {
        name: "stream.completed_messages",
        unit: "count",
        current: 12,
        previous: 18,
        source_ref: "source:service-bus",
        observed_at: "2026-09-17T00:00:00Z",
        state: "complete",
        synthetic: false,
      },
    ] : [],
    slos: [{
      slo_id: order ? "order-fulfillment.availability" : "catalog-browse.availability",
      objective_ratio: 0.99,
      observed_ratio: order ? 0.94 : 1,
      budget_remaining_ratio: order ? 0 : 1,
      breached: order,
      state: "complete",
      source_ref: "source:synthetic-journey",
    }],
    evidence_gaps: [],
    evidence_refs: ["evidence:kubernetes", "evidence:service-bus", "evidence:browser"],
    proposed_action: order ? {
      action_type: "ops.scale-out",
      state: "pending_approval",
      target_ref: "resource:order-processor",
      action_run_ref: "action-run:example",
      execution_authority: false,
      effect_verified: null,
      effect_evidence_ref: null,
    } : null,
    owner_agent: "Forseti",
    observer_agent: "Heimdall",
    execution_authority: false,
  };
}
