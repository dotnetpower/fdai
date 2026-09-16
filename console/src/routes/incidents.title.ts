import type { IncidentSummary, IncidentTitlePresentation } from "../types";
import { t } from "./i18n/evidence";

type IncidentTitleInput = Pick<
  IncidentSummary,
  "title" | "title_source" | "title_presentation"
>;

/** Render only server-classified title metadata; recorded titles remain verbatim. */
export function incidentDisplayTitle(
  incident: IncidentTitleInput,
  unavailable: string,
): string {
  if (incident.title_source === "identifier_fallback") return unavailable;
  const presentation = incident.title_presentation;
  if (presentation == null) return incident.title;
  const subject = presentation.subject ?? localizedSubjectKind(presentation);
  switch (presentation.kind) {
    case "rule_attention":
      return t("incidents.titlePresentation.ruleAttention", {
        rule: presentation.subject ?? incident.title,
      });
    case "signal_on_subject":
      return t("incidents.titlePresentation.signalOnSubject", {
        subject,
        signal: localizedSignal(presentation),
      });
    case "signal":
      return localizedSignal(presentation);
    case "resource_attention":
      return t("incidents.titlePresentation.resourceAttention", { resource: subject });
    case "subject_reason":
      return t("incidents.titlePresentation.subjectReason", {
        subject,
        reason: localizedReason(presentation),
      });
    case "reason":
      return localizedReason(presentation);
  }
}

export function incidentDisplayTechnicalContext(incident: IncidentTitleInput): string | null {
  const technicalRef = incident.title_presentation?.technical_ref;
  return technicalRef && technicalRef !== incident.title ? technicalRef : null;
}

function localizedSubjectKind(presentation: IncidentTitlePresentation): string {
  switch (presentation.subject_kind) {
    case "cloud_resource":
      return t("incidents.titlePresentation.resourceKind.cloudResource");
    case "integration_resource":
      return t("incidents.titlePresentation.resourceKind.integrationResource");
    case "kubernetes_pod":
      return t("incidents.titlePresentation.resourceKind.kubernetesPod");
    case "kubernetes_resource":
      return t("incidents.titlePresentation.resourceKind.kubernetesResource");
    case "kubernetes_workload":
      return t("incidents.titlePresentation.resourceKind.kubernetesWorkload");
    case "trace_target":
      return t("incidents.titlePresentation.resourceKind.traceTarget");
    case "resource":
    case null:
      return t("incidents.titlePresentation.resourceKind.resource");
  }
}

function localizedSignal(presentation: IncidentTitlePresentation): string {
  switch (presentation.signal) {
    case "kubernetes_pod_restart_detected":
      return t("incidents.titlePresentation.signal.kubernetesPodRestart");
    case "resource_inventory_change":
      return t("incidents.titlePresentation.signal.resourceInventoryChange");
    case "trace_continuity_discontinuity":
      return t("incidents.titlePresentation.signal.traceContinuityInterrupted");
    case "trace_propagation_gap":
      return t("incidents.titlePresentation.signal.tracePropagationGap");
    default:
      return presentation.signal_label ?? t("incidents.titleUnavailable");
  }
}

function localizedReason(presentation: IncidentTitlePresentation): string {
  switch (presentation.reason) {
    case "control_loop_unhandled_error":
      return t("incidents.titlePresentation.reason.controlLoopError");
    case "no_rule_match":
      return t("incidents.titlePresentation.reason.noRuleMatch");
    case "no_rule_matches_resource_and_signal_type":
      return t("incidents.titlePresentation.reason.noRuleForResourceAndSignal");
    default:
      return presentation.reason_label ?? t("incidents.titleUnavailable");
  }
}
