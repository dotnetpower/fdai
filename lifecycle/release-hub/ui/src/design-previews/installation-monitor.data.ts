import type { Channel, Sample } from "../../../../hub/ui/src/design-previews/model";

export interface RegisteredInstallationExample {
  readonly id: string;
  readonly name: string;
  readonly channel: Channel;
  readonly reportedVersion: string | null;
  readonly targetVersion: string | null;
  readonly reportedAt: string | null;
}

export type ReportFreshness = "recent" | "stale" | "no-report";
export type ReportFilter = ReportFreshness | "all";

export const REGISTERED_INSTALLATIONS: Sample<RegisteredInstallationExample> & { readonly exampleSnapshotAt: string } = {
  mode: "sample", source: "deterministic-design-fixture", observedAt: null,
  exampleSnapshotAt: "2026-11-05T07:30:00Z",
  records: [
    { id: "example-north", name: "North / 주 운영", channel: "RELEASE", reportedVersion: "0.5.1", targetVersion: "0.5.2", reportedAt: "2026-11-05T07:28:00Z" },
    { id: "example-canary", name: "Canary / 사전 검증", channel: "RELEASE_CANDIDATE", reportedVersion: "0.5.2", targetVersion: "0.5.3", reportedAt: "2026-11-05T07:23:00Z" },
    { id: "example-east", name: "East / 개발 검증", channel: "DEV", reportedVersion: "0.5.2", targetVersion: null, reportedAt: "2026-11-05T07:15:00Z" },
    { id: "example-west", name: "West / 보조 운영", channel: "RELEASE", reportedVersion: "0.5.1", targetVersion: "0.5.2", reportedAt: "2026-11-04T07:10:00Z" },
    { id: "example-lab", name: "Lab / 시험 환경", channel: "DEV", reportedVersion: null, targetVersion: "0.5.4", reportedAt: null },
  ],
};

export function reportFreshness(item: RegisteredInstallationExample, snapshotAt = REGISTERED_INSTALLATIONS.exampleSnapshotAt): ReportFreshness {
  if (item.reportedAt === null) return "no-report";
  const age = Date.parse(snapshotAt) - Date.parse(item.reportedAt);
  if (!Number.isFinite(age) || age < 0) throw new Error(`Invalid example report time for ${item.id}`);
  return age <= 15 * 60 * 1000 ? "recent" : "stale";
}

export function filterRegisteredInstallations(query: string, filter: ReportFilter): readonly RegisteredInstallationExample[] {
  const normalized = query.trim().toLocaleLowerCase();
  return REGISTERED_INSTALLATIONS.records.filter((item) =>
    (filter === "all" || reportFreshness(item) === filter)
    && `${item.name} ${item.id} ${item.reportedVersion ?? ""} ${item.targetVersion ?? ""}`.toLocaleLowerCase().includes(normalized));
}

export function recentlyReportedVersions(): readonly { version: string; count: number }[] {
  const versions = new Map<string, number>();
  for (const item of REGISTERED_INSTALLATIONS.records) {
    if (reportFreshness(item) === "recent" && item.reportedVersion !== null) {
      versions.set(item.reportedVersion, (versions.get(item.reportedVersion) ?? 0) + 1);
    }
  }
  return [...versions].map(([version, count]) => ({ version, count })).sort((a, b) => b.count - a.count || a.version.localeCompare(b.version));
}
