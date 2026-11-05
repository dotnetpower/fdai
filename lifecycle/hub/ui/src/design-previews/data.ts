import type { Channel, Sample, SampleStatus } from "./model";

export interface InstallationExample {
  readonly id: string;
  readonly name: string;
  readonly channel: Channel;
  readonly currentRelease: string | null;
  readonly targetRelease: string | null;
  readonly status: SampleStatus;
  readonly note: string;
  readonly window: string;
  readonly entities: number;
}

export const INSTALLATION_EXAMPLES: Sample<InstallationExample> = {
  mode: "sample", source: "deterministic-design-fixture", observedAt: null,
  records: [
    { id: "example-north", name: "North / 주 운영", channel: "RELEASE", currentRelease: "0.5.1", targetRelease: "0.5.2", status: "waiting", note: "예시 유지보수 창이 열리기를 기다립니다. 계획 발급은 실행 성공이 아닙니다.", window: "02:00-03:00 UTC", entities: 8 },
    { id: "example-canary", name: "Canary / 사전 검증", channel: "RELEASE_CANDIDATE", currentRelease: "0.5.2", targetRelease: "0.5.3", status: "ready", note: "예시 구성 검토가 준비되었습니다. 실제 승인이나 설치 건강 상태는 제공하지 않습니다.", window: "04:00-05:00 UTC", entities: 8 },
    { id: "example-west", name: "West / 보조 운영", channel: "RELEASE", currentRelease: "0.5.1", targetRelease: "0.5.2", status: "held", note: "대상 버전에 맞는 Entity override가 없어 예시 계획이 보류되었습니다.", window: "06:00-07:00 UTC", entities: 6 },
    { id: "example-offline", name: "Offline / 격리 환경", channel: "RELEASE", currentRelease: null, targetRelease: null, status: "unknown", note: "이 예시에는 최신 보고가 없습니다. 빈 값을 정상 상태로 바꾸지 않습니다.", window: "정해지지 않음", entities: 4 },
  ],
};

export type FleetFilter = "all" | "attention" | "unknown";
export function filterInstallations(query: string, filter: FleetFilter): readonly InstallationExample[] {
  const normalized = query.trim().toLocaleLowerCase();
  return INSTALLATION_EXAMPLES.records.filter((item) => `${item.id} ${item.name}`.toLocaleLowerCase().includes(normalized)
    && (filter === "all" || (filter === "unknown" ? item.status === "unknown" : item.status !== "ready")));
}

export type ScheduleDay = "first" | "next";
export function scheduledInstallations(day: ScheduleDay): readonly InstallationExample[] {
  return INSTALLATION_EXAMPLES.records.filter((item) => day === "first"
    ? item.id === "example-north" || item.id === "example-canary"
    : item.id === "example-west");
}
