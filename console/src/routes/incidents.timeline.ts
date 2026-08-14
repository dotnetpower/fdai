import type { AuditItem } from "../types";
import { agentOf } from "./agent-activity-semantics";
import { t } from "./i18n/evidence";

export interface IncidentTimelineFact {
  readonly label: string;
  readonly value: string;
}

export interface IncidentTimelinePresentation {
  readonly title: string;
  readonly description: string;
  readonly owner: string;
  readonly ownerKind: "agent" | "service";
  readonly actionKind: string;
  readonly facts: readonly IncidentTimelineFact[];
}

const PANTHEON = new Set([
  "Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Var", "Vidar", "Bragi",
  "Saga", "Mimir", "Norns", "Muninn", "Njord", "Freyr", "Loki",
]);

const ACTION_TITLE_KEYS: Readonly<Record<string, string>> = {
  "incident.open": "incidents.event.title.opened",
  "incident.members": "incidents.event.title.correlated",
  "incident.transition": "incidents.event.title.transitioned",
  "notification.escalation": "incidents.event.title.notificationEscalation",
  "notification.route": "incidents.event.title.notificationRoute",
  "hil.requested": "incidents.event.title.approvalRequested",
  "hil.request.dispatch_unavailable": "incidents.event.title.approvalUnavailable",
  "control_loop.operator_request_abstain": "incidents.event.title.requestHeld",
  "audit.record": "incidents.event.title.auditRecorded",
};

export function incidentTimelinePresentation(item: AuditItem): IncidentTimelinePresentation {
  const titleKey = ACTION_TITLE_KEYS[item.action_kind];
  const title = titleKey ? t(titleKey) : humanizeToken(item.action_kind);
  const description = firstString(item, "summary", "detail") ??
    inferredDescription(item, title);
  const owner = timelineOwner(item);
  return {
    title,
    description,
    owner: owner.name,
    ownerKind: owner.kind,
    actionKind: item.action_kind,
    facts: timelineFacts(item),
  };
}

function inferredDescription(item: AuditItem, title: string): string {
  if (item.action_kind === "incident.open") {
    const severity = firstString(item, "severity") ?? "unknown";
    return t("incidents.event.description.opened", {
      severity: localizedIncidentValue("severity", severity),
    });
  }
  if (item.action_kind === "incident.members") {
    const count = arrayLength(item, "member_event_ids");
    return count === 1
      ? t("incidents.event.description.correlatedOne")
      : t("incidents.event.description.correlatedMany", { count });
  }
  if (item.action_kind === "incident.transition") {
    const state = firstString(item, "to_state", "state") ?? "unknown";
    return t("incidents.event.description.transitioned", {
      state: localizedIncidentValue("status", state),
    });
  }
  if (item.action_kind === "notification.escalation") {
    const reason = firstString(item, "reason");
    return reason === null
      ? t("incidents.event.description.notificationEscalation")
      : t("incidents.event.description.notificationEscalationReason", {
          reason: sentence(reason),
        });
  }
  if (item.action_kind === "notification.route") {
    const outcome = firstString(item, "outcome") ?? "unknown";
    return t("incidents.event.description.notificationRoute", {
      outcome: localizedIncidentValue("disposition", outcome),
    });
  }
  if (item.action_kind === "hil.requested") {
    return t("incidents.event.description.approvalRequested");
  }
  if (item.action_kind === "hil.request.dispatch_unavailable") {
    return t("incidents.event.description.approvalUnavailable");
  }
  if (item.action_kind === "control_loop.operator_request_abstain") {
    return t("incidents.event.description.requestHeld");
  }
  if (item.action_kind === "audit.record") {
    return t("incidents.event.description.auditRecorded");
  }
  const reason = firstString(item, "reason");
  if (reason !== null) return reason;
  const outcome = firstString(item, "decision", "outcome", "to_state", "state");
  if (outcome !== null) {
    return t("incidents.event.description.result", { result: humanizeToken(outcome) });
  }
  return t("incidents.event.description.recorded", { action: title });
}

function timelineOwner(item: AuditItem): { readonly name: string; readonly kind: "agent" | "service" } {
  const semanticOwner = agentOf(item);
  if (PANTHEON.has(semanticOwner)) return { name: semanticOwner, kind: "agent" };
  if (item.action_kind === "notification.escalation") {
    return { name: t("incidents.owner.notificationDelivery"), kind: "service" };
  }
  if (item.action_kind === "notification.route") {
    return { name: t("incidents.owner.notificationRouter"), kind: "service" };
  }
  if (semanticOwner === "System") return { name: t("incidents.owner.system"), kind: "service" };
  return { name: humanizeService(semanticOwner), kind: "service" };
}

function timelineFacts(item: AuditItem): readonly IncidentTimelineFact[] {
  const facts: IncidentTimelineFact[] = [
    { label: t("incidents.mode"), value: humanizeToken(item.mode) },
  ];
  addFact(facts, t("incidents.fact.decision"), firstString(item, "decision"), true, "verdict");
  addFact(facts, t("incidents.fact.outcome"), firstString(item, "outcome"), true, "disposition");
  addFact(facts, t("incidents.fact.state"), firstString(item, "to_state", "state"), true, "status");
  addFact(facts, t("incidents.fact.stage"), firstString(item, "pipeline_stage", "stage"), true);
  addFact(facts, t("incidents.fact.severity"), firstString(item, "severity"), true, "severity");
  addFact(facts, t("incidents.fact.category"), firstString(item, "category"), true);
  addFact(facts, t("incidents.fact.tier"), firstString(item, "tier", "trust_tier"), true);
  addFact(facts, t("incidents.fact.rule"), firstString(item, "rule_id"), false);
  addFact(facts, t("incidents.fact.approval"), firstString(item, "approval_id"), false);
  addFact(
    facts,
    t("incidents.rollback"),
    firstString(item, "rollback_reference", "rollback_ref"),
    false,
  );
  const relatedSignals = arrayLength(item, "member_event_ids");
  if (relatedSignals > 0) {
    facts.push({ label: t("incidents.fact.relatedSignals"), value: String(relatedSignals) });
  }
  return facts.slice(0, 5);
}

function addFact(
  facts: IncidentTimelineFact[],
  label: string,
  value: string | null,
  humanize: boolean,
  catalogGroup?: string,
): void {
  if (value === null) return;
  facts.push({
    label,
    value: catalogGroup
      ? localizedIncidentValue(catalogGroup, value)
      : humanize
        ? humanizeToken(value)
        : value,
  });
}

function localizedIncidentValue(group: string, value: string): string {
  const key = `incidents.${group}.${value}`;
  const translated = t(key);
  return translated === key ? humanizeToken(value) : translated;
}

function firstString(item: AuditItem, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = item.entry[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function arrayLength(item: AuditItem, key: string): number {
  const value = item.entry[key];
  return Array.isArray(value) ? value.length : 0;
}

function humanizeToken(value: string): string {
  if (/^sev\d+$/i.test(value)) return value.toUpperCase();
  const words = value.replace(/[._-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function humanizeService(value: string): string {
  return humanizeToken(value.replace(/^fdai[._-]?/, ""));
}

function sentence(value: string): string {
  return /[.!?]$/.test(value) ? value : `${value}.`;
}
