import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { nextPromotionTransition, type Action, type Catalog, type Release } from "./api";
import {
  BADGE_HEIGHT,
  buildConnectorGeometry,
  buildReleaseLineageGraph,
  buildReleaseStagePipeline,
  CARD_HEIGHT,
  CARD_WIDTH,
  computeLineageSummary,
  type LineageGraph,
  type LineageNode,
} from "./release-lineage.model";

export {
  BADGE_HEIGHT,
  buildConnectorGeometry,
  buildReleaseLineageGraph,
  buildReleaseStagePipeline,
  CARD_HEIGHT,
  CARD_WIDTH,
  COL_GAP,
  compareSemVer,
  computeLineageSummary,
  nextSuggestedSemVer,
  PAD_X,
  PAD_Y,
  parseSemVerTuple,
  resolveReleaseNodeStatus,
  ROW_GAP,
  type LineageEdge,
  type LineageGraph,
  type LineageNode,
  type LineageNodeStatus,
  type LineageSummary,
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
  filterTrack,
  onSelectNode,
  idPrefix,
}: {
  graph: LineageGraph;
  locale: "en" | "ko";
  selectedId?: string | null | undefined;
  filterTrack?: string | null | undefined;
  onSelectNode?: ((node: LineageNode) => void) | undefined;
  idPrefix: string;
}) {
  void idPrefix;
  const containerRef = useRef<HTMLDivElement>(null);

  function focusNodeAtIndex(nextIdx: number) {
    const cards = containerRef.current?.querySelectorAll<HTMLElement>(".rh-lineage-card[tabindex]");
    if (!cards || cards.length === 0) return;
    const clamped = Math.max(0, Math.min(cards.length - 1, nextIdx));
    const target = cards[clamped];
    if (target) {
      target.focus();
      const node = graph.nodes[clamped];
      if (node) onSelectNode?.(node);
    }
  }

  return (
    <div
      ref={containerRef}
      class="rh-lineage-scroll"
      role="region"
      aria-label={locale === "ko" ? "릴리스 버전 계통 그래프 (좌우 화살표 키로 이동)" : "Release lineage graph (Use Left/Right arrow keys to navigate)"}
    >
      <svg
        class="rh-lineage-canvas-svg"
        width={graph.width}
        height={graph.height}
        viewBox={`0 0 ${graph.width} ${graph.height}`}
      >
        {graph.edges.map((edge) => {
          const { portCx, portCy, pathD, arrowD } = buildConnectorGeometry(edge);
          return (
            <g
              key={edge.id}
              class={`rh-lineage-edge ${edge.active ? "is-active" : ""} kind-${edge.kind}`}
              aria-hidden="true"
            >
              <path d={pathD} class="rh-edge-line" fill="none" />
              <circle cx={portCx} cy={portCy} r="3.5" class="rh-edge-port" />
              <path d={arrowD} class="rh-edge-arrow" fill="none" />
            </g>
          );
        })}

        {graph.nodes.map((node, index) => {
          const isSelected = selectedId === node.id;
          const isDimmed = Boolean(filterTrack && filterTrack !== "all" && node.stencilId !== filterTrack);
          const badgeLabel = locale === "ko" ? node.badgeTextKo : node.badgeText;
          const hintLabel = node.actionableHint
            ? locale === "ko"
              ? node.actionableHint.ko
              : node.actionableHint.en
            : null;
          const ariaLabel = `${node.title}, ${badgeLabel}, ${node.subtitle}${hintLabel ? ` (${hintLabel})` : ""}`;
          return (
            <foreignObject
              key={node.id}
              x={node.x}
              y={node.y}
              width={CARD_WIDTH}
              height={CARD_HEIGHT + BADGE_HEIGHT}
              class="rh-lineage-fo"
            >
              <div class={`rh-lineage-node-wrap ${isDimmed ? "is-dimmed" : ""}`}>
                <div class="rh-lineage-badge-row">
                  {node.status !== "pending" && (
                    <span class={`rh-lineage-badge status-${node.status}`}>
                      {node.status === "complete" && (
                        <span class="rh-badge-check" aria-hidden="true">
                          ✓
                        </span>
                      )}
                      {node.status === "running" && node.id === "__building_draft__" && (
                        <span class="rh-badge-spinner" aria-hidden="true" />
                      )}
                      {node.status === "running" && node.id !== "__building_draft__" && (
                        <span class="rh-badge-check" aria-hidden="true">●</span>
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
                  aria-label={ariaLabel}
                  aria-pressed={onSelectNode ? isSelected : undefined}
                  aria-current={isSelected ? "step" : undefined}
                  title={hintLabel ?? `${node.title} (${node.subtitle})`}
                  class={`rh-lineage-card status-${node.status} ${node.id === "__building_draft__" ? "is-running" : ""} ${isSelected ? "is-selected" : ""} ${hintLabel ? "is-actionable" : ""}`}
                  onClick={() => onSelectNode?.(node)}
                  onKeyDown={(e) => {
                    if (!onSelectNode) return;
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelectNode(node);
                    } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                      e.preventDefault();
                      focusNodeAtIndex(index + 1);
                    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                      e.preventDefault();
                      focusNodeAtIndex(index - 1);
                    } else if (e.key === "Home") {
                      e.preventDefault();
                      focusNodeAtIndex(0);
                    } else if (e.key === "End") {
                      e.preventDefault();
                      focusNodeAtIndex(graph.nodes.length - 1);
                    }
                  }}
                >
                  <div class="rh-lineage-card-top">
                    <NodeIcon kind={node.icon} />
                    <strong class="rh-node-title">{node.title}</strong>
                  </div>
                  <div class="rh-lineage-card-bottom">
                    <span class="rh-node-sub">{hintLabel && node.status === "running" ? `${node.subtitle} · ${hintLabel}` : node.subtitle}</span>
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
  onQuickPromote,
  onComparePair,
}: {
  catalog: Catalog;
  locale: "en" | "ko";
  activeReleaseId?: string | null | undefined;
  buildingDraft?: { id: string; stencilId: string; label?: string | undefined } | null | undefined;
  disabled?: boolean | undefined;
  onAct?: ((action: Action, release: Release) => void) | undefined;
  onQuickPromote?: ((release: Release) => Promise<void> | void) | undefined;
  onComparePair?: ((baseId: string, targetId: string) => void) | undefined;
}) {
  const t = (en: string, ko: string) => (locale === "ko" ? ko : en);
  const defaultSelected = useMemo(() => {
    const runningRel = catalog.releases.find(
      (r) =>
        r.state === "draft" ||
        (r.state === "published" && !r.channels.includes("RELEASE")),
    );
    return runningRel?.id ?? catalog.releases[0]?.id ?? null;
  }, [catalog.releases]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(defaultSelected);
  const [filterTrack, setFilterTrack] = useState<string>("all");

  useEffect(() => {
    if (!selectedNodeId || !catalog.releases.some((r) => r.id === selectedNodeId)) {
      setSelectedNodeId(defaultSelected);
    }
  }, [catalog.releases, selectedNodeId, defaultSelected]);

  const graph = useMemo(
    () =>
      buildReleaseLineageGraph(catalog, {
        activeReleaseId,
        buildingDraft,
      }),
    [catalog, activeReleaseId, buildingDraft],
  );

  const summary = useMemo(() => computeLineageSummary(graph), [graph]);

  const selectedRelease = useMemo(
    () => catalog.releases.find((r) => r.id === selectedNodeId) ?? catalog.releases[0] ?? null,
    [catalog.releases, selectedNodeId],
  );

  const selectedParentId = useMemo(() => {
    if (!selectedRelease) return null;
    const node = graph.nodes.find((n) => n.id === selectedRelease.id);
    return node?.parentIds?.[0] ?? null;
  }, [graph.nodes, selectedRelease]);

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
        </div>
        <div class="rh-lineage-summary-strip" aria-label={t("Lineage status summary", "버전 계통 상태 요약")}>
          <span class="rh-lineage-badge status-complete">
            <span class="rh-badge-check" aria-hidden="true">✓</span>
            {t(`Complete: ${summary.complete}`, `운영 완료: ${summary.complete}`)}
          </span>
          <span class="rh-lineage-badge status-running">
            <span class="rh-badge-check" aria-hidden="true">●</span>
            {t(`Staged (DEV / RC): ${summary.running}`, `DEV/RC 단계(승격 대기): ${summary.running}`)}
          </span>
          <span class="rh-lineage-badge status-recalled">
            <span class="rh-badge-recall" aria-hidden="true">✕</span>
            {t(`Recalled / Blocked: ${summary.recalled}`, `회수/차단: ${summary.recalled}`)}
          </span>
          {summary.editionTracks.length > 1 && (
            <div class="quick-chips" role="group" aria-label={t("Filter by Stencil track", "에디션 트랙 필터")}>
              <button
                type="button"
                class={`chip-btn ${filterTrack === "all" ? "is-active-chip" : ""}`}
                onClick={() => setFilterTrack("all")}
              >
                {t("All tracks", "전체 트랙")}
              </button>
              {summary.editionTracks.map((tr) => (
                <button
                  key={tr}
                  type="button"
                  class={`chip-btn ${filterTrack === tr ? "is-active-chip" : ""}`}
                  onClick={() => setFilterTrack((prev) => (prev === tr ? "all" : tr))}
                >
                  {tr}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <LineageCanvas
        graph={graph}
        locale={locale}
        selectedId={selectedRelease?.id}
        filterTrack={filterTrack}
        idPrefix="catalog-lineage"
        onSelectNode={(node) => {
          setSelectedNodeId(node.id);
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
              {onComparePair && selectedParentId && (
                <button
                  type="button"
                  class="chip-btn"
                  onClick={() => onComparePair(selectedParentId, selectedRelease.id)}
                >
                  {t(
                    `Compare v${selectedParentId} -> v${selectedRelease.id}`,
                    `이전 계통(v${selectedParentId} -> v${selectedRelease.id}) Diff 비교`,
                  )}
                </button>
              )}
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
              {nextPromotionTransition(selectedRelease) && onQuickPromote && (
                <button
                  type="button"
                  class="primary"
                  disabled={disabled}
                  onClick={() => void onQuickPromote(selectedRelease)}
                >
                  {t(
                    `1-Click Promote to ${nextPromotionTransition(selectedRelease)!.targetChannel}`,
                    `원클릭 ${nextPromotionTransition(selectedRelease)!.targetChannel} 즉시 승격`,
                  )}
                </button>
              )}
              {onAct && nextPromotionTransition(selectedRelease) && (
                <button
                  type="button"
                  class={onQuickPromote ? "chip-btn" : "primary"}
                  disabled={disabled}
                  onClick={() => onAct("promote", selectedRelease)}
                >
                  {t(
                    `Promote to ${nextPromotionTransition(selectedRelease)!.targetChannel}`,
                    `${nextPromotionTransition(selectedRelease)!.targetChannel} 단계로 승격 (옵션)`,
                  )}
                </button>
              )}
            </div>
          </div>
          <details class="release-disclosure" style="margin-top: 12px;">
            <summary>
              {t(
                `Inspect 5-stage build & promotion pipeline for v${selectedRelease.id}`,
                `v${selectedRelease.id} 5단계 빌드·승격 상세 파이프라인 보기`,
              )}
            </summary>
            <ReleaseStageLineage
              release={selectedRelease}
              catalog={catalog}
              locale={locale}
              disabled={disabled}
              onAct={onAct}
            />
          </details>
        </div>
      )}
    </section>
  );
}

export function ReleaseStageLineage({
  release,
  catalog,
  locale,
  disabled,
  onAct,
}: {
  release: Release;
  catalog: Catalog;
  locale: "en" | "ko";
  disabled?: boolean | undefined;
  onAct?: ((action: Action, release: Release) => void) | undefined;
}) {
  const stageGraph = useMemo(
    () => buildReleaseStagePipeline(release, catalog),
    [release, catalog],
  );
  const transition = nextPromotionTransition(release);

  return (
    <div class="rh-stage-lineage-box">
      <LineageCanvas
        graph={stageGraph}
        locale={locale}
        idPrefix={`stage-${release.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`}
        onSelectNode={(node) => {
          if (disabled) return;
          if (node.id === "initialize-stencil") {
            location.hash = "/stencils";
          } else if (node.id === "clone-codebase") {
            location.hash = `/releases/${release.id}`;
          } else if (node.id === "build-sign-dev" && release.state === "draft" && onAct) {
            onAct("publish", release);
          } else if (
            node.id === "promote-rc-canary" &&
            transition?.targetChannel === "RELEASE_CANDIDATE" &&
            onAct
          ) {
            onAct("promote", release);
          } else if (
            node.id === "release-production" &&
            transition?.targetChannel === "RELEASE" &&
            onAct
          ) {
            onAct("promote", release);
          } else {
            location.hash = `/releases/${release.id}`;
          }
        }}
      />
    </div>
  );
}
