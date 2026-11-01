import { describe, expect, test } from "vitest";
import { HubApiError, type InstallationDetail } from "./api";
import { classifyHubError, deriveInstallationReadiness } from "./readiness-status";

const baseInstallation: InstallationDetail = {
  installation_id: "prod-korea",
  enrollment: "enrolled",
  settings: {
    channel: "RELEASE",
    version_range: ">=1.4.0 <2.0.0",
    region: "koreacentral",
    allowed_regions: ["koreacentral"],
    windows: [
      {
        start: "02:00:00",
        duration_minutes: 60,
        timezone: "Asia/Seoul",
        allows_downtime: false,
      },
    ],
  },
  configuration_digest: "sha256:" + "a".repeat(64),
  reported_at: "2026-10-25T01:00:00Z",
  schema_revision: 15,
  current_release: "1.5.0",
  health: "healthy",
  entities: [
    {
      entity_id: "core",
      kind: "workload",
      managed: true,
      ownership_gap: null,
      release_id: "1.5.0",
      health: "healthy",
    },
  ],
  suppressions: [],
  open_plan: null,
  last_evaluation: {
    outcome: "up-to-date",
    target_release_id: null,
    plan_id: null,
    checks: [],
    evaluated_at: "2026-10-25T01:05:00Z",
  },
  reports: [],
};

describe("classifyHubError", () => {
  test("distinguishes 401, 403, 503, timeout, and network failures without leaking secrets (UXH-02/03/04)", () => {
    expect(classifyHubError(new HubApiError(401, "authentication_required"))).toMatchObject({
      kind: "session-expired",
      title: "Session expired",
    });
    expect(classifyHubError(new HubApiError(403, "principal_not_authorized"))).toMatchObject({
      kind: "access-denied",
      title: "Operator access or boundary denied",
    });
    expect(
      classifyHubError(new HubApiError(503, "catalog_not_imported_approve_pin_and_import")),
    ).toMatchObject({
      kind: "prerequisite-unavailable",
      title: "Service or prerequisite unavailable",
    });
    expect(classifyHubError(new DOMException("aborted", "TimeoutError"))).toMatchObject({
      kind: "timeout",
      title: "Request timed out",
    });
    expect(classifyHubError(new TypeError("Failed to fetch"))).toMatchObject({
      kind: "network-unreachable",
      title: "Hub API unreachable",
    });
  });
});

describe("deriveInstallationReadiness", () => {
  const nowMs = Date.parse("2026-10-25T02:00:00Z");

  test("identifies unmanaged Entities as the primary blocker (UXH-01)", () => {
    const view = deriveInstallationReadiness(
      {
        ...baseInstallation,
        entities: [
          {
            entity_id: "core",
            kind: "workload",
            managed: false,
            ownership_gap: "ownership_unproven",
            release_id: "1.5.0",
            health: "healthy",
          },
        ],
      },
      nowMs,
    );
    expect(view.nextStep.posture).toBe("blocked");
    expect(view.nextStep.targetTab).toBe("entities");
    expect(view.prerequisites.find((p) => p.id === "entities")?.status).toBe("fail");
  });

  test("explains preauthorized scheduled updates without adding a mandatory apply button (#2535)", () => {
    const view = deriveInstallationReadiness(
      {
        ...baseInstallation,
        last_evaluation: {
          outcome: "waiting",
          target_release_id: "1.6.0",
          plan_id: null,
          checks: [
            {
              release_id: "1.6.0",
              blocks: [{ reason_code: "maintenance_window_unavailable", details: [] }],
            },
          ],
          evaluated_at: "2026-10-25T01:05:00Z",
        },
      },
      nowMs,
    );
    expect(view.nextStep.posture).toBe("scheduled");
    expect(view.nextStep.detail).toContain("no manual apply button is needed");
    expect(view.recovery).toBeNull();
  });

  test("distinguishes rollback failure holds and builds a recovery timeline (UXH-12)", () => {
    const view = deriveInstallationReadiness(
      {
        ...baseInstallation,
        suppressions: [
          {
            scope: "entity:core",
            starts_at: "2026-10-25T01:10:00Z",
            ends_at: "2026-10-26T01:10:00Z",
            origin: "failure",
            failed_plan_id: "plan-0001",
          },
        ],
        reports: [
          {
            plan_id: "plan-0001",
            attempt: 1,
            outcome: "rolled-back",
            reason_code: "health_check_failed",
            exact_plan_digest: "sha256:" + "b".repeat(64),
            summary: "Canary failed readiness check",
            reported_at: "2026-10-25T01:10:00Z",
            received_at: "2026-10-25T01:10:01Z",
          },
        ],
      },
      nowMs,
    );
    expect(view.nextStep.posture).toBe("recovery-needed");
    expect(view.recovery).not.toBeNull();
    expect(view.recovery?.latestFailedReport?.outcome).toBe("rolled-back");
    expect(view.recovery?.activeHolds).toHaveLength(1);
  });

  test("flags stale Agent reports and expired open Plans separately from healthy workloads (UXH-09/10/11)", () => {
    const staleNow = Date.parse("2026-10-27T05:00:00Z");
    const view = deriveInstallationReadiness(
      {
        ...baseInstallation,
        open_plan: {
          plan_id: "plan-0002",
          sequence: 2,
          target_release_id: "1.6.0",
          expires_at: "2026-10-25T03:00:00Z",
        },
      },
      staleNow,
    );
    expect(view.timeHorizons.planExpired).toBe(true);
    expect(view.nextStep.headline).toContain("expired");
    expect(view.prerequisites.find((p) => p.id === "agent")?.status).toBe("warn");
  });
});
