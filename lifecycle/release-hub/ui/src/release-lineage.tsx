import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { nextPromotionTransition, type Action, type Catalog, type Release } from "./api";
import {
  BADGE_HEIGHT,
  buildReleaseLineageGraph,
  buildReleaseStagePipeline,
  CARD_HEIGHT,
  CARD_WIDTH,
  PAD_X,
  type LineageGraph,
  type LineageNode,
} from "./release-lineage.model";

export {
  BADGE_HEIGHT,
  buildReleaseLineageGraph,
  buildReleaseStagePipeline,
  CARD_HEIGHT,
  CARD_WIDTH,
  COL_GAP,
  compareSemVer,
  PAD_X,
  PAD_Y,
  parseSemVerTuple,
  resolveReleaseNodeStatus,
  ROW_GAP,
  type LineageEdge,
  type LineageGraph,
  type LineageNode,
  type LineageNodeStatus,
} from "./release-lineage.model";

function NodeIcon({ kind }: { kind: LineageNode["icon"] }) {
  if (kind === "init") {
    return (
      <svg class="rh-node-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path
          d="M4.5 3.2L12.2 8L4.5 12.8V3.2Z"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linejoin="round"
        />
      </svg>
    );
  }
  if (kind === "branch") {
    return (
      <svg class="rh-node-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="4.5" cy="4" r="1.7" stroke="currentColor" stroke-width="1.3" />
        <circle cx="4.5" cy="12" r="1.7" stroke="currentColor" stroke-width="1.3" />
        <circle cx="11.5" cy="6.5" r="1.7" stroke="currentColor" stroke-width="1.3" />
        <path
          d="M4.5 5.7V10.3M4.5 8.5C4.5 6.8 6.5 6.5 9.8 6.5"
          stroke="currentColor"
          stroke-width="1.3"
          stroke-linecap="round"
        />
      </svg>
    );
  }
  if (kind === "shield") {
    return (
      <svg class="rh-node-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path
          d="M8 2.2L13 4.2V7.8C13 10.9 10.8 13.1 8 14C5.2 13.1 3 10.9 3 7.8V4.2L8 2.2Z"
          stroke="currentColor"
          stroke-width="1.3"
          stroke-linejoin="round"
        />
      </svg>
    );
  }
  return (
    <svg class="rh-node-icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M5.2 11.5H11.4C12.8 11.5 13.8 10.5 13.8 9.2C13.8 8 12.9 7 11.7 6.9C11.3 4.9 9.6 3.5 7.6 3.5C5.4 3.5 3.7 5.2 3.7 7.3C2.7 7.6 2.1 8.5 2.1 9.5C2.1 10.7 3.1 11.5 4.3 11.5"
        stroke="currentColor"
        stroke-width="1.3"
        stroke-linecap="round"
      />
      <circle cx="6.8" cy="11.5" r="1.5" stroke="currentColor" stroke-width="1.2" />
    </svg>
  );
}

function LineageCanvas({
  graph,
  locale,
  selectedId,
  onSelectNode,
  idPrefix,
}: {
  graph: LineageGraph;
  locale: "en" | "ko";
  selectedId?: string | null | undefined;
  onSelectNode?: ((node: LineageNode) => void) | undefined;
  idPrefix: string;
}) {
  void idPrefix;
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const runningNode = graph.nodes.find((n) => n.status === "running");
    if (runningNode && runningNode.x + CARD_WIDTH > el.clientWidth) {
      el.scrollLeft = Math.max(0, runningNode.x + CARD_WIDTH - el.clientWidth + PAD_X);
    }
  }, [graph]);
  return (
    <div ref={scrollRef} class="rh-lineage-scroll" role="region" aria-label="Release lineage graph">
      <svg
        class="rh-lineage-canvas-svg"
        width={graph.width}
        height={graph.height}
        viewBox={`0 0 ${graph.width} ${graph.height}`}
      >
        {graph.edges.map((edge) => {
          const sx = edge.startX + 4;
          const sy = edge.startY;
          const ex = edge.endX - 3;
          const ey = edge.endY;
          const midX = sx + (ex - sx) * 0.5;
          const pathD = `M ${sx + 3.5} ${sy} C ${midX} ${sy}, ${midX} ${ey}, ${ex} ${ey}`;
          const arrowD = `M ${ex - 6} ${ey - 4.2} L ${ex} ${ey} L ${ex - 6} ${ey + 4.2}`;
          return (
            <g
              key={edge.id}
              class={`rh-lineage-edge ${edge.active ? "is-active" : ""} kind-${edge.kind}`}
              aria-hidden="true"
            >
              <path d={pathD} class="rh-edge-line" fill="none" />
              <circle cx={sx} cy={sy} r="3.5" class="rh-edge-port" />
              <path d={arrowD} class="rh-edge-arrow" fill="none" />
            </g>
          );
        })}

        {graph.nodes.map((node) => {
          const isSelected = selectedId === node.id;
          const badgeLabel = locale === "ko" ? node.badgeTextKo : node.badgeText;
          return (
            <foreignObject
              key={node.id}
              x={node.x}
              y={node.y}
              width={CARD_WIDTH}
              height={CARD_HEIGHT + BADGE_HEIGHT}
              class="rh-lineage-fo"
            >
              <div class="rh-lineage-node-wrap">
                <div class="rh-lineage-badge-row">
                  {node.status !== "pending" && (
                    <span class={`rh-lineage-badge status-${node.status}`}>
                      {node.status === "complete" && (
                        <span class="rh-badge-check" aria-hidden="true">
                          ✓
                        </span>
                      )}
                      {node.status === "running" && (
                        <span class="rh-badge-spinner" aria-hidden="true" />
                      )}
                      {node.status === "recalled" && (
                        <span class="rh-badge-recall" aria-hidden="true">
                          ✕
                        </span>
                      )}
                      <span>{badgeLabel}</span>
                    </span>
                  )}
                </div>

                <div
                  role={onSelectNode ? "button" : undefined}
                  tabIndex={onSelectNode ? 0 : undefined}
                  class={`rh-lineage-card status-${node.status} ${node.status === "running" ? "is-running" : ""} ${isSelected ? "is-selected" : ""}`}
                  onClick={() => onSelectNode?.(node)}
                  onKeyDown={(e) => {
                    if (onSelectNode && (e.key === "Enter" || e.key === " ")) {
                      e.preventDefault();
                      onSelectNode(node);
                    }
                  }}
                >
                  <div class="rh-lineage-card-top">
                    <NodeIcon kind={node.icon} />
                    <strong class="rh-node-title">{node.title}</strong>
                  </div>
                  <div class="rh-lineage-card-bottom">
                    <span class="rh-node-sub">{node.subtitle}</span>
                  </div>
                </div>
              </div>
            </foreignObject>
          );
        })}
      </svg>
    </div>
  );
}

export function ReleaseLineageSection({
  catalog,
  locale,
  activeReleaseId,
  buildingDraft,
  disabled,
  onAct,
}: {
  catalog: Catalog;
  locale: "en" | "ko";
  activeReleaseId?: string | null | undefined;
  buildingDraft?: { id: string; stencilId: string; label?: string | undefined } | null | undefined;
  disabled?: boolean | undefined;
  onAct?: ((action: Action, release: Release) => void) | undefined;
}) {
  const t = (en: string, ko: string) => (locale === "ko" ? ko : en);
  const [simulatingId, setSimulatingId] = useState<string | null>(null);
  const defaultSelected = useMemo(() => {
    const runningRel = catalog.releases.find(
      (r) =>
        r.state === "draft" ||
        (r.state === "published" && !r.channels.includes("RELEASE")),
    );
    return runningRel?.id ?? catalog.releases[0]?.id ?? null;
  }, [catalog.releases]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(defaultSelected);

  useEffect(() => {
    if (!simulatingId) return;
    const timer = setTimeout(() => setSimulatingId(null), 8000);
    return () => clearTimeout(timer);
  }, [simulatingId]);

  const graph = useMemo(
    () =>
      buildReleaseLineageGraph(catalog, {
        activeReleaseId,
        simulatingId,
        buildingDraft,
      }),
    [catalog, activeReleaseId, simulatingId, buildingDraft],
  );

  const selectedRelease = useMemo(
    () => catalog.releases.find((r) => r.id === selectedNodeId) ?? catalog.releases[0] ?? null,
    [catalog.releases, selectedNodeId],
  );

  return (
    <section class="rh-lineage-section" aria-labelledby="rh-lineage-heading">
      <div class="rh-lineage-header">
        <div>
          <p class="eyebrow">
            {t("Left-to-Right (LR) Version Lineage & Build Pipeline", "좌→우(LR) 버전 계통도 및 실시간 빌드·승격 상태")}
          </p>
          <h2 id="rh-lineage-heading">
            {t("Release Version Lineage Graph (LR)", "릴리스 버전 전체 계통도 (LR Lineage)")}
          </h2>
          <p>
            {t(
              "All registered Release versions connected from left to right across SemVer evolution, Stencil edition tracks, and recall-lifting succession. Active builds and in-progress stage promotions display an animated border beam.",
              "모든 릴리스 버전의 파생·에디션 분기·리콜 계승 계통을 좌→우(LR)로 연결합니다. 현재 빌드·서명·카나리 승격이 진행 중인 노드는 테두리 광선 애니메이션(Running)으로 표시됩니다.",
            )}
          </p>
        </div>
        <div class="actions">
          {selectedRelease && (
            <button
              type="button"
              onClick={() =>
                setSimulatingId((prev) =>
                  prev === selectedRelease.id ? null : selectedRelease.id,
                )
              }
            >
              {simulatingId === selectedRelease.id
                ? t("Stop build animation preview", "빌드 테두리 애니메이션 중지")
                : t(
                    `Preview build animation on v${selectedRelease.id}`,
                    `v${selectedRelease.id} 빌드 테두리 애니메이션 미리보기`,
                  )}
            </button>
          )}
        </div>
      </div>

      <LineageCanvas
        graph={graph}
        locale={locale}
        selectedId={selectedRelease?.id}
        idPrefix="catalog-lineage"
        onSelectNode={(node) => {
          setSelectedNodeId(node.id);
          if (node.release) {
            location.hash = `/releases/${node.release.id}`;
          }
        }}
      />

      {selectedRelease && (
        <div class="rh-lineage-stage-bar">
          <div class="rh-lineage-stage-head">
            <strong>
              {t(
                `Selected Version Pipeline (LR): Release v${selectedRelease.id}`,
                `선택된 버전의 빌드·승격 LR 파이프라인: Release v${selectedRelease.id}`,
              )}
            </strong>
            <div class="actions">
              <a href={`#/releases/${selectedRelease.id}`} class="chip-btn">
                {t(`Open v${selectedRelease.id} workspace ->`, `v${selectedRelease.id} 상세 작업 영역 열기 ->`)}
              </a>
              {onAct && selectedRelease.state === "draft" && (
                <button
                  type="button"
                  class="primary"
                  disabled={disabled}
                  onClick={() => onAct("publish", selectedRelease)}
                >
                  {t("Sign & Publish to DEV", "DEV 서명 및 발행")}
                </button>
              )}
              {onAct && nextPromotionTransition(selectedRelease) && (
                <button
                  type="button"
                  class="primary"
                  disabled={disabled}
                  onClick={() => onAct("promote", selectedRelease)}
                >
                  {t(
                    `Promote to ${nextPromotionTransition(selectedRelease)!.targetChannel}`,
                    `${nextPromotionTransition(selectedRelease)!.targetChannel} 단계로 승격`,
                  )}
                </button>
              )}
            </div>
          </div>
          <ReleaseStageLineage release={selectedRelease} catalog={catalog} locale={locale} />
        </div>
      )}
    </section>
  );
}

export function ReleaseStageLineage({
  release,
  catalog,
  locale,
}: {
  release: Release;
  catalog: Catalog;
  locale: "en" | "ko";
}) {
  const [simStep, setSimStep] = useState<number | null>(null);

  useEffect(() => {
    if (simStep === null) return;
    if (simStep >= 4) {
      const doneTimer = setTimeout(() => setSimStep(null), 2200);
      return () => clearTimeout(doneTimer);
    }
    const timer = setTimeout(() => setSimStep((s) => (s === null ? null : s + 1)), 1800);
    return () => clearTimeout(timer);
  }, [simStep]);

  const stageGraph = useMemo(
    () => buildReleaseStagePipeline(release, catalog, simStep),
    [release, catalog, simStep],
  );

  return (
    <div class="rh-stage-lineage-box">
      <LineageCanvas
        graph={stageGraph}
        locale={locale}
        idPrefix={`stage-${release.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`}
      />
      <div class="rh-stage-sim-controls">
        <small>
          {locale === "ko"
            ? "단계 흐름: initialize-stencil → clone-codebase → build-sign-dev → promote-rc-canary → release-production"
            : "Stage flow: initialize-stencil → clone-codebase → build-sign-dev → promote-rc-canary → release-production"}
        </small>
        <button
          type="button"
          class="chip-btn"
          onClick={() => setSimStep((prev) => (prev === null ? 0 : null))}
        >
          {simStep !== null
            ? locale === "ko"
              ? "실행 시뮬레이션 중지"
              : "Stop pipeline simulation"
            : locale === "ko"
              ? "▶ 빌드·승격 LR 파이프라인 애니메이션 재생"
              : "▶ Replay LR build pipeline animation"}
        </button>
      </div>
    </div>
  );
}
