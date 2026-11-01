// Typed client for the Hub's read-only and approval routes (`fdai_lifecycle_hub.api`).
// Same origin in production (the Hub serves this UI); proxied to 8090 in dev (vite.config.ts).
import { authenticatedFetch } from "./auth";

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

export interface ExecutionSettings {
  settings_digest: string;
  product?: string | null;
  windows: readonly MaintenanceWindow[];
  plan_duration_minutes: number;
}

export interface ExecutionSettingsRequest {
  request_id: string;
  expected_settings_digest: string;
  windows: readonly MaintenanceWindow[];
  plan_duration_minutes: number;
  reason_code: string;
  confirmation: string;
}

export type ApplicationBindingRequest =
  Omit<ExecutionSettingsRequest, "windows" | "plan_duration_minutes"> & { product: string };

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
  request_id?: string | null;
  // Absent on a Hub that predates Agent-submitted enrollment.
  requested_by?: string | null;
  requested_via?: "agent" | "operator" | null;
  channel: string;
  version_range: string;
  region: string;
  entities: readonly EntityView[];
  reported_at: string;
  schema_revision: number;
}

export interface ReleaseInventoryItem {
  release_id: string;
  digest: string;
  source_commit: string;
  platform_tag: string;
  channels: readonly string[];
  schema_target: number | null;
  schema_range: { minimum: number; maximum: number } | null;
  images: readonly { section: string; component: string; image_digest: string }[];
  recall_notices: readonly { sequence: number; action: string; notice_digest: string }[];
}

export interface ConfigurationInventoryItem {
  digest: string;
  imported_at: string;
  schema_key_count: number;
  override_count: number;
  installation_ids: readonly string[];
  signature_status: "not-recorded";
}

export interface UpdateChange {
  added_releases: readonly { release_id: string; channels: readonly string[]; schema_target: number | null }[];
  removed_releases: readonly string[];
  changed_releases: readonly string[];
  channel_additions: readonly { channel: string; release_id: string }[];
  channel_removals: readonly { channel: string; release_id: string }[];
  new_channels: readonly string[];
  new_recalls: readonly { scope: string; target: string; sequence: number }[];
  lifted_recalls: readonly { scope: string; target: string; sequence: number }[];
  removed_recalls?: readonly { scope: string; target: string; sequence: number }[];
  schema_widened: boolean;
}

export interface IntegrityRole {
  version: number;
  expires_at: string;
}

/** One verification of the vendor's signed catalog roles. It carries versions, never key material. */
export interface IntegrityResult {
  mode: "tuf";
  verified: boolean;
  reason: string;
  root: IntegrityRole | null;
  snapshot: IntegrityRole | null;
  timestamp: IntegrityRole | null;
  expired: boolean;
  root_rotation: boolean;
  previous_root_version: number;
  max_recall_sequence: number;
  allowed_plan_types: readonly string[];
  demote_operator_overrides_to_shadow: boolean;
}

/** The anti-rollback floors this Hub has persisted, with the latest verification. */
export interface IntegrityState {
  mode: "tuf";
  root_version: number;
  snapshot_version: number;
  snapshot_expires_at: string | null;
  timestamp_version: number;
  timestamp_expires_at: string | null;
  max_recall_sequence: number;
  observed_at: string | null;
  last: IntegrityResult | null;
}

export interface UpdateCandidate {
  revision: number;
  sha256: string;
  expires_at: string;
  signature_verified: boolean;
  key_id: string | null;
  accepted_revision: number | null;
  decision: { allow: boolean; reasons: readonly string[] };
  change: UpdateChange;
  integrity?: IntegrityResult;
}

export type UpdateOutcome = "unchanged" | "adopted" | "review_required" | "failed";

export interface UpdateCheckRecord {
  checked_at: string;
  outcome: UpdateOutcome;
  detail: string;
  candidate: UpdateCandidate | null;
  plans: readonly { installation_id: string; outcome: string; reason?: string }[];
  integrity?: IntegrityResult;
}

export interface UpdateEvent {
  action: string;
  actor: string;
  revision: number;
  sha256: string;
  reason: string;
  recorded_at: string;
}

export interface UpdateStatus {
  mode: "review" | "auto";
  allowed_channels: readonly string[];
  max_new_releases: number;
  check_interval_seconds: number;
  access: "managed-identity" | "anonymous";
  authorization: { authorized_by: string; expires_at: string; valid: boolean } | null;
  accepted: { revision: number; sha256: string; expires_at: string; release_count: number } | null;
  last_check: UpdateCheckRecord | null;
  events: readonly UpdateEvent[];
  /** Present only when the Hub trusts signed catalog roles instead of one release key. */
  integrity?: IntegrityState;
}

export type BindableStatus = "unrequested" | "pending" | "enrolled";

export interface BindableInstallation {
  installation_id: string;
  status: BindableStatus;
}

export class HubApiError extends Error {
  constructor(
    readonly status: number,
    readonly reasonCode: string,
  ) {
    super(`Hub API ${status}: ${reasonCode}`);
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const signal = init?.signal;
  signal?.throwIfAborted();
  const pending = fetchJson<T>(path, init);
  if (!signal) return pending;
  return new Promise<T>((resolve, reject) => {
    const aborted = () => reject(signal.reason);
    signal.addEventListener("abort", aborted, { once: true });
    void pending.then(resolve, reject).finally(() => signal.removeEventListener("abort", aborted));
    if (signal.aborted) aborted();
  });
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(path, {
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

async function requestEnrollment(installationId: string, file: File): Promise<void> {
  if (!/^[a-z][a-z0-9-]{0,62}$/.test(installationId)) {
    throw new Error("Enter a valid installation ID.");
  }
  if (file.size === 0 || file.size > 64 * 1024) {
    throw new Error("Choose a nonempty signed request JSON file of at most 64 KiB.");
  }
  let signed: unknown;
  try {
    signed = JSON.parse(await file.text());
  } catch {
    throw new Error("Could not read the signed request JSON file.");
  }
  const base64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
  if (typeof signed !== "object" || signed === null || Array.isArray(signed) ||
      Object.keys(signed).length !== 2 || !("signed_payload" in signed) || !("proof" in signed) ||
      ![signed.signed_payload, signed.proof].every(
        value => typeof value === "string" && value.length > 0 && base64.test(value),
      )) {
    throw new Error("The file must contain only base64 signed_payload and proof fields. Never upload a private key.");
  }
  await request(`/v1/enrollments/${encodeURIComponent(installationId)}/requests`, {
    method: "POST", body: JSON.stringify(signed), signal: AbortSignal.timeout(10_000),
  });
}

/** The bound installations, or null when the Hub has no Agent identity binding (404). */
async function listBindableInstallations(): Promise<readonly BindableInstallation[] | null> {
  try {
    const { installations } = await request<{ installations: readonly BindableInstallation[] }>(
      "/v1/enrollments/bindable", { signal: AbortSignal.timeout(10_000) },
    );
    return installations;
  } catch (error) {
    if (error instanceof HubApiError && error.status === 404) return null;
    throw error;
  }
}

export const hubApi = {
  requestEnrollment,
  listBindableInstallations,
  listReleases: () =>
    request<{ releases: readonly ReleaseInventoryItem[] }>("/v1/catalog/releases", {
      signal: AbortSignal.timeout(10_000),
    }),
  getUpdateStatus: () =>
    request<UpdateStatus>("/v1/catalog/updates", { signal: AbortSignal.timeout(10_000) }),
  checkForUpdates: () =>
    request<UpdateCheckRecord>("/v1/catalog/updates/check", {
      method: "POST", signal: AbortSignal.timeout(10_000),
    }),
  applyUpdate: (revision: number, sha256: string) =>
    request<UpdateCheckRecord>("/v1/catalog/updates/apply", {
      method: "POST", body: JSON.stringify({ revision, sha256 }), signal: AbortSignal.timeout(10_000),
    }),
  listConfigurations: () =>
    request<{ configurations: readonly ConfigurationInventoryItem[] }>("/v1/configurations", {
      signal: AbortSignal.timeout(10_000),
    }),
  listInstallations: () =>
    request<{ installations: readonly InstallationSummary[] }>("/v1/installations"),
  getInstallation: (installationId: string) =>
    request<InstallationDetail>(`/v1/installations/${encodeURIComponent(installationId)}`, {
      signal: AbortSignal.timeout(10_000),
    }),
  getExecutionSettings: (installationId: string) =>
    request<ExecutionSettings>(
      `/v1/installations/${encodeURIComponent(installationId)}/execution-settings`,
      { signal: AbortSignal.timeout(10_000) },
    ),
  updateExecutionSettings: (installationId: string, body: ExecutionSettingsRequest) =>
    request<{ changed: boolean; settings_digest: string }>(
      `/v1/installations/${encodeURIComponent(installationId)}/execution-settings`,
      {
        method: "POST", body: JSON.stringify(body), signal: AbortSignal.timeout(10_000),
      },
    ),
  bindApplication: (installationId: string, body: ApplicationBindingRequest) =>
    request<{ changed: boolean; settings_digest: string }>(
      `/v1/installations/${encodeURIComponent(installationId)}/application-binding`,
      { method: "POST", body: JSON.stringify(body), signal: AbortSignal.timeout(10_000) },
    ),
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
