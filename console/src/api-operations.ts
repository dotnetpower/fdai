import type { AuditPage, HilQueuePage, IncidentPage, RcaView } from "./types";
import {
  apiBoolean,
  apiMode,
  apiNonNegativeInteger,
  apiNullableRatio,
  apiNullableString,
  apiNumber,
  apiOptionalNullableNonNegativeInteger,
  apiOptionalNullableString,
  apiOptionalString,
  apiOptionalStringArray,
  apiPositiveInteger,
  apiRatio,
  apiRecord,
  apiString,
  contractError,
} from "./api-contract";
import { isRfc3339Timestamp } from "./time-format";

export function decodeAuditPage(value: unknown): AuditPage {
  const root = apiRecord(value, "audit page");
  if (!Array.isArray(root["items"])) throw contractError("audit page.items MUST be an array");
  const cursor = root["next_cursor"];
  if (cursor !== null && typeof cursor !== "string") {
    throw contractError("audit page.next_cursor MUST be a string or null");
  }
  return {
    items: root["items"].map((raw, index) => {
      const item = apiRecord(raw, `audit page.items[${index}]`);
      return {
        seq: apiPositiveInteger(item, "seq", "audit item"),
        event_id: apiString(item, "event_id", "audit item"),
        correlation_id: apiNullableString(item, "correlation_id", "audit item"),
        actor: apiString(item, "actor", "audit item"),
        action_kind: apiString(item, "action_kind", "audit item"),
        mode: apiMode(item["mode"]),
        entry: apiRecord(item["entry"], "audit item.entry") as Record<string, unknown>,
        entry_hash: apiString(item, "entry_hash", "audit item"),
        previous_hash: apiString(item, "previous_hash", "audit item"),
        recorded_at: apiString(item, "recorded_at", "audit item"),
      };
    }),
    next_cursor: cursor,
  };
}

export function decodeIncidentPage(value: unknown): IncidentPage {
  const root = apiRecord(value, "incident page");
  if (!Array.isArray(root["items"])) throw contractError("incident page.items MUST be an array");
  const cursor = root["next_cursor"];
  if (cursor !== null && typeof cursor !== "string") {
    throw contractError("incident page.next_cursor MUST be a string or null");
  }
  return {
    items: root["items"].map((raw, index) => {
      const item = apiRecord(raw, `incident page.items[${index}]`);
      const involvedAgents = item["involved_agents"];
      if (
        involvedAgents !== undefined &&
        (!Array.isArray(involvedAgents) ||
          !involvedAgents.every((agent) => typeof agent === "string"))
      ) {
        throw contractError("incident item.involved_agents MUST be an array of strings");
      }
      return {
        correlation_id: apiString(item, "correlation_id", "incident item"),
        incident_id: apiNullableString(item, "incident_id", "incident item"),
        ticket_id: apiNullableString(item, "ticket_id", "incident item"),
        title: apiString(item, "title", "incident item"),
        severity: apiString(item, "severity", "incident item"),
        status: apiIncidentStatus(item["status"]),
        status_source: apiStatusSource(item["status_source"]),
        disposition: apiString(item, "disposition", "incident item"),
        verdict: apiString(item, "verdict", "incident item"),
        vertical: apiString(item, "vertical", "incident item"),
        opened_at: apiString(item, "opened_at", "incident item"),
        last_updated_at: apiString(item, "last_updated_at", "incident item"),
        latest_mode: apiMode(item["latest_mode"]),
        history_count: apiPositiveInteger(item, "history_count", "incident item"),
        involved_agents: involvedAgents ?? [],
      };
    }),
    next_cursor: cursor,
  };
}

export function decodeRcaView(value: unknown): RcaView {
  const root = apiRecord(value, "RCA view");
  if (!Array.isArray(root["hypotheses"])) {
    throw contractError("RCA view.hypotheses MUST be an array");
  }
  const response = root["response"];
  const correlationId = apiString(root, "correlation_id", "RCA view");
  if (correlationId.trim().length === 0) throw contractError("RCA view.correlation_id MUST NOT be empty");
  const hypotheses = root["hypotheses"].map((raw, index) => {
      const item = apiRecord(raw, `RCA view.hypotheses[${index}]`);
      const citations = item["citations"];
      if (!Array.isArray(citations)) {
        throw contractError(`RCA view.hypotheses[${index}].citations MUST be an array`);
      }
      const recordedAt = apiString(item, "recorded_at", "RCA hypothesis");
      if (!isRfc3339Timestamp(recordedAt)) {
        throw contractError("RCA hypothesis.recorded_at MUST be an RFC 3339 timestamp");
      }
      return {
        seq: apiPositiveInteger(item, "seq", "RCA hypothesis"),
        tier: apiRcaTier(item["tier"]),
        outcome: apiRcaOutcome(item["outcome"]),
        grounded: apiBoolean(item, "grounded", "RCA hypothesis"),
        cause: apiNullableString(item, "cause", "RCA hypothesis"),
        confidence: apiNullableRatio(item, "confidence", "RCA hypothesis"),
        reason: apiNullableString(item, "reason", "RCA hypothesis"),
        citations: citations.map((rawCitation, citationIndex) => {
          const citation = apiRecord(rawCitation, `RCA hypothesis.citations[${citationIndex}]`);
          return {
            kind: apiString(citation, "kind", "RCA citation"),
            ref: apiString(citation, "ref", "RCA citation"),
          };
        }),
        remediation_ref: apiNullableString(item, "remediation_ref", "RCA hypothesis"),
        causal_chain: decodeRcaCausalChain(item["causal_chain"]),
        mode: apiMode(item["mode"]),
        recorded_at: recordedAt,
      };
    });
  const sequence = hypotheses.map((hypothesis) => hypothesis.seq);
  if (new Set(sequence).size !== sequence.length || sequence.some((seq, index) => index > 0 && seq <= sequence[index - 1]!)) {
    throw contractError("RCA hypotheses MUST have unique ascending seq values");
  }
  const decodedResponse = response === null
    ? null
    : (() => {
        const item = apiRecord(response, "RCA view.response");
        const recordedAt = apiNullableString(item, "recorded_at", "RCA response");
        if (recordedAt !== null && !isRfc3339Timestamp(recordedAt)) {
          throw contractError("RCA response.recorded_at MUST be an RFC 3339 timestamp or null");
        }
        return {
          verdict: apiString(item, "verdict", "RCA response"),
          decision: apiNullableString(item, "decision", "RCA response"),
          action_kind: apiNullableString(item, "action_kind", "RCA response"),
          mode: item["mode"] === null ? null : apiMode(item["mode"]),
          rollback_reference: apiNullableString(item, "rollback_reference", "RCA response"),
          recorded_at: recordedAt,
        };
      })();
  return {
    correlation_id: correlationId,
    incident_id: apiNullableString(root, "incident_id", "RCA view"),
    hypotheses,
    response:
      decodedResponse,
  };
}

function decodeRcaCausalChain(value: unknown): RcaView["hypotheses"][number]["causal_chain"] {
  if (value === null || value === undefined) return null;
  const chain = apiRecord(value, "RCA causal chain");
  if (!Array.isArray(chain["hops"]) || chain["hops"].length === 0) {
    throw contractError("RCA causal chain.hops MUST be a non-empty array");
  }
  return {
    root_event_id: apiString(chain, "root_event_id", "RCA causal chain"),
    failure_event_id: apiString(chain, "failure_event_id", "RCA causal chain"),
    confidence: apiRatio(chain, "confidence", "RCA causal chain"),
    ambiguity: apiPositiveInteger(chain, "ambiguity", "RCA causal chain"),
    hops: chain["hops"].map((raw, index) => {
      const hop = apiRecord(raw, `RCA causal chain.hops[${index}]`);
      const leadSeconds = apiNumber(hop, "lead_seconds", "RCA causal hop");
      if (leadSeconds < 0) throw contractError("RCA causal hop.lead_seconds MUST be non-negative");
      return {
        cause_event_id: apiString(hop, "cause_event_id", "RCA causal hop"),
        effect_event_id: apiString(hop, "effect_event_id", "RCA causal hop"),
        cause_resource_ref: apiString(hop, "cause_resource_ref", "RCA causal hop"),
        effect_resource_ref: apiString(hop, "effect_resource_ref", "RCA causal hop"),
        lead_seconds: leadSeconds,
        relationship: apiString(hop, "relationship", "RCA causal hop"),
        confidence: apiRatio(hop, "confidence", "RCA causal hop"),
      };
    }),
  };
}

export function decodeHilQueuePage(value: unknown): HilQueuePage {
  const root = apiRecord(value, "HIL queue page");
  if (!Array.isArray(root["items"])) throw contractError("HIL queue page.items MUST be an array");
  const items = root["items"].map((raw, index) => {
      const item = apiRecord(raw, `HIL queue page.items[${index}]`);
      const requestedAt = apiString(item, "requested_at", "HIL queue item");
      const mode = apiOptionalString(item, "mode", "HIL queue item");
      const ttlExpiresAt = apiOptionalNullableString(item, "ttl_expires_at", "HIL queue item");
      if (!isRfc3339Timestamp(requestedAt)) {
        throw contractError("HIL queue item.requested_at MUST be an RFC 3339 timestamp");
      }
      if (ttlExpiresAt !== null && !isRfc3339Timestamp(ttlExpiresAt)) {
        throw contractError("HIL queue item.ttl_expires_at MUST be an RFC 3339 timestamp or null");
      }
      if (mode !== "" && mode !== "shadow" && mode !== "enforce") {
        throw contractError("HIL queue item.mode MUST be shadow, enforce, or omitted");
      }
      return {
        idempotency_key: apiString(item, "idempotency_key", "HIL queue item"),
        event_id: apiString(item, "event_id", "HIL queue item"),
        action_kind: apiString(item, "action_kind", "HIL queue item"),
        reason: apiString(item, "reason", "HIL queue item"),
        requested_at: requestedAt,
        correlation_id: apiNullableString(item, "correlation_id", "HIL queue item"),
        approval_id: apiOptionalString(item, "approval_id", "HIL queue item"),
        action_id: apiOptionalString(item, "action_id", "HIL queue item"),
        target_resource_ref: apiOptionalString(item, "target_resource_ref", "HIL queue item"),
        mode,
        stop_condition: apiOptionalString(item, "stop_condition", "HIL queue item"),
        rollback_kind: apiOptionalString(item, "rollback_kind", "HIL queue item"),
        rollback_reference: apiOptionalNullableString(item, "rollback_reference", "HIL queue item"),
        blast_radius_scope: apiOptionalString(item, "blast_radius_scope", "HIL queue item"),
        blast_radius_count: apiOptionalNullableNonNegativeInteger(item, "blast_radius_count", "HIL queue item"),
        blast_radius_rate_per_minute: apiOptionalNullableNonNegativeInteger(item, "blast_radius_rate_per_minute", "HIL queue item"),
        blast_radius_summary: apiOptionalString(item, "blast_radius_summary", "HIL queue item"),
        reasons: apiOptionalStringArray(item, "reasons", "HIL queue item"),
        citing_rule_ids: apiOptionalStringArray(item, "citing_rule_ids", "HIL queue item"),
        ttl_expires_at: ttlExpiresAt,
      };
    });
  const total = apiNonNegativeInteger(root, "total", "HIL queue page");
  const detailLevel = apiHilDetailLevel(root["detail_level"]);
  if (total < items.length) {
    throw contractError("HIL queue page.total MUST be at least the number of returned items");
  }
  if (detailLevel === "count_only" && items.length > 0) {
    throw contractError("count-only HIL queue pages MUST NOT include item details");
  }
  const keys = items.map((item) => item.idempotency_key);
  if (new Set(keys).size !== keys.length) {
    throw contractError("HIL queue page.items MUST have unique idempotency keys");
  }
  return {
    items,
    total,
    detail_level: detailLevel,
  };
}

function apiIncidentStatus(value: unknown): "open" | "in_progress" | "resolved" {
  if (value === "open" || value === "in_progress" || value === "resolved") return value;
  throw contractError("incident item.status MUST be open, in_progress, or resolved");
}

function apiStatusSource(value: unknown): "incident_lifecycle" | "audit_projection" {
  if (value === "incident_lifecycle" || value === "audit_projection") return value;
  throw contractError("incident item.status_source MUST name a supported projection source");
}

function apiRcaTier(value: unknown): "t0" | "t1" | "t2" | "unknown" {
  if (value === "t0" || value === "t1" || value === "t2" || value === "unknown") return value;
  throw contractError("RCA hypothesis.tier MUST be t0, t1, t2, or unknown");
}

function apiRcaOutcome(value: unknown): "grounded" | "abstained" | "unknown" {
  if (value === "grounded" || value === "abstained" || value === "unknown") return value;
  throw contractError("RCA hypothesis.outcome MUST be grounded, abstained, or unknown");
}

function apiHilDetailLevel(value: unknown): "full" | "count_only" {
  if (value === undefined || value === "full") return "full";
  if (value === "count_only") return "count_only";
  throw contractError("HIL queue page.detail_level MUST be full or count_only");
}
