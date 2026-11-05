// Presentation-only domain. Never accepted as an API request or operational evidence.
export const DESIGNS = {
  release: [
    { id: "edition", name: "Edition", subtitle: "릴리스를 한 권의 에디션처럼" },
  ],
  lifecycle: [
    { id: "atlas", name: "Atlas", subtitle: "설치 환경을 한눈에 조망" },
    { id: "timeline", name: "Timeline", subtitle: "변경을 시간의 흐름으로 읽기" },
    { id: "ledger", name: "Ledger", subtitle: "설치 상태와 근거를 정밀하게 비교" },
  ],
} as const;

export type HubId = keyof typeof DESIGNS;
export type DesignId<H extends HubId> = typeof DESIGNS[H][number]["id"];
export type PreviewRoute =
  | { kind: "operational" }
  | { kind: "not-found" }
  | { kind: "preview"; hub: "release"; design: DesignId<"release">; page?: "installations" }
  | { kind: "preview"; hub: "lifecycle"; design: DesignId<"lifecycle"> };

export function previewPath<H extends HubId>(hub: H, design: DesignId<H>): string {
  return `/design-previews/${design}`;
}

export const releaseInstallationsPreviewPath = "/design-previews/edition/installations";

/** Reserve only the explicit preview namespace; malformed IDs never enter a live route. */
export function resolvePreview(hub: HubId, pathname: string): PreviewRoute {
  if (pathname !== "/design-previews" && !pathname.startsWith("/design-previews/")) {
    return { kind: "operational" };
  }
  if (hub === "release") {
    if (pathname === releaseInstallationsPreviewPath) {
      return { kind: "preview", hub, design: "edition", page: "installations" };
    }
    const item = DESIGNS.release.find(({ id }) => pathname === previewPath("release", id));
    return item ? { kind: "preview", hub, design: item.id } : { kind: "not-found" };
  }
  const item = DESIGNS.lifecycle.find(({ id }) => pathname === previewPath("lifecycle", id));
  return item ? { kind: "preview", hub, design: item.id } : { kind: "not-found" };
}

export interface Sample<T> {
  readonly mode: "sample";
  readonly source: "deterministic-design-fixture";
  readonly observedAt: null;
  readonly records: readonly T[];
}

export type Channel = "DEV" | "RELEASE_CANDIDATE" | "RELEASE";
export type SampleStatus = "ready" | "waiting" | "held" | "unknown";
export const STATUS_LABELS: Record<SampleStatus, string> = {
  ready: "검토 준비", waiting: "대기", held: "보류", unknown: "근거 없음",
};
