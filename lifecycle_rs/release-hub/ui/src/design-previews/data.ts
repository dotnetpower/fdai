import type { Channel, Sample, SampleStatus } from "../../../../hub/ui/src/design-previews/model";

export interface ReleaseExample {
  readonly id: string;
  readonly title: string;
  readonly channel: Channel;
  readonly status: SampleStatus;
  readonly edition: string;
  readonly components: number;
  readonly note: string;
}

export const RELEASE_EXAMPLES: Sample<ReleaseExample> = {
  mode: "sample", source: "deterministic-design-fixture", observedAt: null,
  records: [
    { id: "0.5.3", title: "A quieter control plane", channel: "RELEASE_CANDIDATE", status: "waiting", edition: "Standard SRE", components: 8, note: "카나리 안정화 시간이 남아 있습니다. 예시상 다음 검토 시각은 14:00 UTC입니다." },
    { id: "0.5.2", title: "Precision in every change", channel: "RELEASE", status: "ready", edition: "Standard SRE", components: 8, note: "정책과 구성의 변경 내역을 비교할 수 있는 릴리스 예시입니다. 실제 서명 검증 결과는 아닙니다." },
    { id: "0.5.4", title: "The next chapter", channel: "DEV", status: "held", edition: "Full Enterprise", components: 8, note: "초안의 보안 검토 근거가 아직 없습니다. 승격 버튼 대신 보류 이유를 먼저 보여 줍니다." },
    { id: "0.5.1", title: "Observe with clarity", channel: "RELEASE", status: "unknown", edition: "Lite Observe", components: 4, note: "이 예시에는 아티팩트 가용성 관측이 없습니다. 건강 상태나 설치 성공을 추정하지 않습니다." },
  ],
};

export const COMPONENTS = [
  { id: "core", name: "Core control plane", role: "판단과 정책" },
  { id: "operator", name: "Operator service", role: "비특권 요청 경계" },
  { id: "ingestion", name: "Document ingestion", role: "문서 수집" },
  { id: "worker", name: "Document worker", role: "문서 처리" },
  { id: "executor", name: "Isolated executor", role: "독립 실행 경계" },
  { id: "console", name: "Console", role: "운영자 화면" },
  { id: "scanner", name: "ClamAV", role: "콘텐츠 검사" },
  { id: "support", name: "Deployment support", role: "설치 지원 도구" },
] as const;
export type ComponentId = typeof COMPONENTS[number]["id"];

export function filterReleases(query: string, channel: Channel | "all"): readonly ReleaseExample[] {
  const normalized = query.trim().toLocaleLowerCase();
  return RELEASE_EXAMPLES.records.filter((item) => (channel === "all" || item.channel === channel)
    && `${item.id} ${item.title} ${item.edition}`.toLocaleLowerCase().includes(normalized));
}
