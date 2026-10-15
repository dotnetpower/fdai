// Typed client for the Hub's read-only and approval routes (`fdai_lifecycle_hub.api`).
// Same origin in production (the Hub serves this UI); proxied to 8090 in dev (vite.config.ts).

export type Outcome =
  | "issued"
  | "unchanged"
  | "waiting"
  | "no-eligible-release"
  | "up-to-date"
  | "no-managed-entity";

export type Health = "healthy" | "degraded" | "unhealthy" | "unknown";

export type OwnershipGap = "ownership_tag_only" | "ownership_unproven" | null;

export interface ConstraintBlock {
  reason_code: string;
  details: readonly string[];
}

export interface CandidateCheck {
  release_id: string;
  blocks: readonly ConstraintBlock[];
}

export interface Evaluation {
  outcome: Outcome;
  target_release_id: string | null;
  plan_id: string | null;
  checks: readonly CandidateCheck[];
  evaluated_at: string;
}

export interface InstallationSummary {
  installation_id: string;
  channel: string;
  version_range: string;
  current_release: string | null;
  target_release_id: string | null;
  outcome: Outcome | null;
  health: Health | null;
  next_window_starts_at: string | null;
  next_window_ends_at: string | null;
  // Whether the next window is already open, as opposed to still upcoming. `next_window_starts_at`
  // alone can't tell these apart: a daily window that opened hours ago still has a past start time.
  next_window_open: boolean;
  last_evaluated_at: string | null;
}

export interface MaintenanceWindow {
  start: string;
  duration_minutes: number;
  timezone: string;
  allows_downtime: boolean;
}

export interface EntityView {
  entity_id: string;
  kind: string;
  managed: boolean;
  ownership_gap: OwnershipGap;
  release_id: string | null;
  health: Health | null;
}

export interface Suppression {
  scope: string;
  starts_at: string;
  ends_at: string;
  origin: "manual" | "failure";
  failed_plan_id: string | null;
}

export interface OpenPlanRef {
  plan_id: string;
  sequence: number;
  target_release_id: string;
  expires_at: string;
}

export interface PlanReportView {
  plan_id: string;
  attempt: number;
  outcome: string;
  reason_code: string;
  exact_plan_digest: string | null;
  summary: string;
  reported_at: string;
  received_at: string;
}

export interface InstallationDetail {
  installation_id: string;
  enrollment: string;
  settings: {
    channel: string;
    version_range: string;
    region: string;
    allowed_regions: readonly string[];
    windows: readonly MaintenanceWindow[];
  };
  configuration_digest: string;
  reported_at: string;
  schema_revision: number;
  current_release: string | null;
  health: Health | null;
  entities: readonly EntityView[];
  suppressions: readonly Suppression[];
  open_plan: OpenPlanRef | null;
  last_evaluation: Evaluation | null;
  reports: readonly PlanReportView[];
}

export interface PlanEventView {
  kind: string;
  recorded_at: string;
}

export interface PlanDetail {
  plan_id: string;
  installation_id: string;
  sequence: number;
  plan_type: string;
  target_release_id: string;
  source_state_digest: string;
  configuration_digest: string;
  hub_key_id: string;
  entity_ids: readonly string[];
  expires_at: string;
  status: "open" | "superseded";
  events: readonly PlanEventView[];
  evaluations: readonly Evaluation[];
  reports: readonly PlanReportView[];
}

export interface PendingEnrollment {
  installation_id: string;
  installation_key_id: string;
  requested_at: string;
  channel: string;
  version_range: string;
  region: string;
  entities: readonly EntityView[];
  reported_at: string;
  schema_revision: number;
}

export class HubApiError extends Error {
  constructor(
    readonly status: number,
    readonly reasonCode: string,
  ) {
    super(`Hub API ${status}: ${reasonCode}`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { ...(init?.body ? { "content-type": "application/json" } : {}), ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({ error: response.statusText }))) as {
      error?: string;
    };
    throw new HubApiError(response.status, body.error ?? "unknown_error");
  }
  return (await response.json()) as T;
}

export const hubApi = {
  listInstallations: () =>
    request<{ installations: readonly InstallationSummary[] }>("/v1/installations"),
  getInstallation: (installationId: string) =>
    request<InstallationDetail>(`/v1/installations/${encodeURIComponent(installationId)}`),
  getPlan: (installationId: string, planId: string) =>
    request<PlanDetail>(
      `/v1/installations/${encodeURIComponent(installationId)}/plans/${encodeURIComponent(planId)}`,
    ),
  listPendingEnrollments: () =>
    request<{ enrollments: readonly PendingEnrollment[] }>("/v1/enrollments/pending"),
  getPendingEnrollment: (installationId: string) =>
    request<PendingEnrollment>(`/v1/enrollments/pending/${encodeURIComponent(installationId)}`),
  approveEnrollment: (installationId: string, approver: string, installationKeyId: string) =>
    request<{ enrolled: string }>(
      `/v1/installations/${encodeURIComponent(installationId)}/enrollment/approve`,
      {
        method: "POST",
        body: JSON.stringify({ approver, installation_key_id: installationKeyId }),
      },
    ),
  rejectEnrollment: (installationId: string, approver: string, reason: string) =>
    request<{ rejected: string }>(
      `/v1/installations/${encodeURIComponent(installationId)}/enrollment/reject`,
      { method: "POST", body: JSON.stringify({ approver, reason }) },
    ),
};
