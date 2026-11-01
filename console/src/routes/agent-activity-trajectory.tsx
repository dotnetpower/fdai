import { Fragment } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import type { AgentStreamStatus } from "../hooks/use-agent-stream";
import { observationSourceLabel, type ObservationSource } from "../hooks/observation-source";
import { t } from "./i18n/agent-trajectory";
import { currentRoute, replaceRouteState, routeHref } from "../router";
import { formatConsoleTime, formatConsoleTimestamp } from "../time-format";
import type { AuditItem } from "../types";
import type { LiveAgentActivityEvent } from "./agents.model";
import { agentOf, fmtDur } from "./agent-activity-semantics";
import {
  buildAgentTrajectories,
  filterAgentTrajectories,
  formatOutcomeLabel,
  formatOutcomeWithCode,
  groupTrajectoriesForDisplay,
  mergeLiveEventsIntoAuditItems,
  parseStructuredFieldValue,
  presentReasonLabel,
  presentResourceTypeLabel,
  presentStepSummary,
  presentTrajectoryTitle,
  stabilizeTrajectorySelection,
  trajectoryPhases,
  trajectoryScale,
  trajectorySubtitle,
  uncorrelatedAuditCount,
  type AgentTrajectory,
  type PinnedTrajectoryDetail,
  type TrajectoryPhaseState,
  type TrajectoryStep,
  type TrajectoryStepCategory,
  type TrajectoryTone,
} from "./agent-activity-trajectory-model";
import { agentRoleTitle } from "./agents.view-model";
import "./agent-activity-trajectory.css";

const CATEGORY_ICON: Readonly<Record<TrajectoryStepCategory, string>> = {
  intake: "M1.5 8h8M6.5 5l3 3-3 3M13.5 2.5v11",
  evidence: "M13.5 8h-10M6.5 5l-3 3 3 3M13.5 3v10",
  decision: "M3 2.5v4a3 3 0 0 0 3 3h7.5M10.5 6.5l3 3-3 3M3 13.5v.01",
  risk: "M8 2 14.5 13.5h-13zM8 6.5v3M8 11.5v.01",
  approval: "M6 7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM1.5 14c0-2.5 2-4 4.5-4 1.6 0 2.8.6 3.6 1.6M10.5 12.5l1.5 1.5 3-3",
  action: "M9 1.5 3 9h4.5L7 14.5 13 7H8.5z",
  recovery: "M2.5 3v3.5H6M2.9 6.5A5.5 5.5 0 1 1 3.2 10",
  verification: "M8 1.5 13.5 3.5v4c0 3.5-2.5 6-5.5 7-3-1-5.5-3.5-5.5-7v-4zM5.5 8l1.8 1.8 3.2-3.3",
  record: "M3.5 1.5h9v13l-2-1.2-2.5 1.2-2.5-1.2-2 1.2zM6 5.5h4M6 8.5h4",
  activity: "M2 8h3l2-4 2 8 2-4h3",
};
const PHASE_GLYPH: Readonly<Record<TrajectoryPhaseState, string>> = {
  recorded: "M4 8.5 6.5 11 12 5.5",
  attention: "M8 4v5M8 11.5v.01",
  failed: "M5 5l6 6M11 5l-6 6",
  unrecorded: "",
};
const SHIELD = "M8 1.5 13.5 3.5v4c0 3.5-2.5 6-5.5 7-3-1-5.5-3.5-5.5-7v-4z";
const CHEVRON = "M6 4l4 4-4 4";
const ARROW = "M2 8h10M9 5l3 3-3 3";
const LANE_HEIGHT = 36;

interface Props {
  readonly items: readonly AuditItem[];
  readonly liveEvents?: readonly LiveAgentActivityEvent[];
  readonly selectedAgent: string | null;
  readonly query: string;
  readonly olderAvailable: boolean;
  readonly streamStatus: AgentStreamStatus;
  readonly streamSource: ObservationSource;
  readonly onAgentChange: (agent: string | null) => void;
  readonly onQueryChange: (query: string) => void;
  readonly onClearFilters?: () => void;
  readonly onShowLog: (correlationId: string) => void;
}

export function AgentTrajectories({
  items,
  liveEvents,
  selectedAgent,
  query,
  olderAvailable,
  streamStatus,
  streamSource,
  onAgentChange,
  onQueryChange,
  onClearFilters,
  onShowLog,
}: Props) {
  const mergedItems = useMemo(
    () => mergeLiveEventsIntoAuditItems(items, liveEvents ?? []),
    [items, liveEvents],
  );
  const all = useMemo(() => buildAgentTrajectories(mergedItems, agentOf), [mergedItems]);
  const [correlationFilter, setCorrelationFilter] = useState<string>("");
  const liveShown = useMemo(
    () => filterAgentTrajectories(all, selectedAgent, query).filter(
      (trajectory) => !correlationFilter || trajectory.correlationId === correlationFilter,
    ),
    [all, selectedAgent, query, correlationFilter],
  );
  const agents = useMemo(() => {
    const names = new Set(all.flatMap((trajectory) => trajectory.agents));
    if (selectedAgent !== null) names.add(selectedAgent);
    return [...names].sort((left, right) => left.localeCompare(right));
  }, [all, selectedAgent]);
  const correlations = useMemo(
    () => all.map((trajectory) => trajectory.correlationId),
    [all],
  );
  const [selectedId, setSelectedId] = useState<string | null>(() => initialSelection(all));
  const [selectionVersion, setSelectionVersion] = useState(0);
  const pinnedRef = useRef<PinnedTrajectoryDetail | null>(null);
  const filterKey = `${selectedAgent ?? ""}\0${query}\0${correlationFilter}`;
  const selection = useMemo(
    () => stabilizeTrajectorySelection(liveShown, selectedId, filterKey, pinnedRef.current),
    [liveShown, selectedId, filterKey, selectionVersion],
  );
  pinnedRef.current = selection.pinned;
  const { shown, grouped, current, currentGroupMembers } = selection;
  const titleRef = useRef<HTMLHeadingElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const knownTrajectoryDigestRef = useRef<Map<string, number> | null>(null);
  const [updatedCorrelationIds, setUpdatedCorrelationIds] = useState<ReadonlySet<string>>(new Set());
  const uncorrelated = useMemo(() => uncorrelatedAuditCount(mergedItems), [mergedItems]);

  useEffect(() => {
    const nextDigest = new Map<string, number>();
    for (const trajectory of all) {
      nextDigest.set(trajectory.correlationId, trajectory.endMs);
    }
    const previous = knownTrajectoryDigestRef.current;
    knownTrajectoryDigestRef.current = nextDigest;
    if (previous === null) return;
    const changed: string[] = [];
    for (const [corrId, endMs] of nextDigest) {
      const prevEnd = previous.get(corrId);
      if (prevEnd === undefined || endMs > prevEnd) {
        changed.push(corrId);
      }
    }
    if (changed.length === 0) return;
    setUpdatedCorrelationIds((curr) => new Set([...curr, ...changed]));
    const timer = window.setTimeout(() => {
      setUpdatedCorrelationIds((curr) => {
        const next = new Set(curr);
        changed.forEach((id) => next.delete(id));
        return next;
      });
    }, 3_000);
    return () => window.clearTimeout(timer);
  }, [all]);

  useEffect(() => {
    if (selectedId === null) {
      const requested = initialSelection(all);
      if (requested !== null) {
        setSelectedId(requested);
        return;
      }
    }
    if (current !== null && selectedId !== current.correlationId) {
      setSelectedId(current.correlationId);
    }
  }, [all, current, selectedId]);

  useEffect(() => {
    const syncRouteSelection = () => {
      const requested = initialSelection(all);
      if (requested !== null && requested !== pinnedRef.current?.correlationId) {
        pinnedRef.current = null;
        setSelectedId(requested);
        setSelectionVersion((version) => version + 1);
      }
    };
    window.addEventListener("popstate", syncRouteSelection);
    window.addEventListener("fdai:route-changed", syncRouteSelection);
    return () => {
      window.removeEventListener("popstate", syncRouteSelection);
      window.removeEventListener("fdai:route-changed", syncRouteSelection);
    };
  }, [all]);

  // Keep the selected row visible inside the bounded list without scrolling the page.
  useEffect(() => {
    const list = listRef.current;
    const row = list?.querySelector<HTMLElement>('.tj-item[aria-pressed="true"]');
    if (!list || !row) return;
    const top = row.offsetTop - list.offsetTop;
    if (top < list.scrollTop || top + row.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = Math.max(top - 8, 0);
    }
  }, [current?.correlationId]);

  const select = (correlationId: string): void => {
    pinnedRef.current = null;
    setSelectedId(correlationId);
    setSelectionVersion((version) => version + 1);
    const url = new URL(window.location.href);
    url.searchParams.set("trajectory", correlationId);
    url.searchParams.delete("step");
    url.searchParams.delete("view");
    replaceRouteState(`${url.pathname}${url.search}`);
    window.requestAnimationFrame(() => titleRef.current?.focus());
  };

  return (
    <section class="aa-trajectories" aria-label={t("agentActivity.trajectory.label")}>
      <div class="tj-filters" role="search">
        <label class="cs-control-field">
          <span class="cs-control-label">{t("agentActivity.log.agent")}</span>
          <select
            class="cs-control-select"
            value={selectedAgent ?? ""}
            onChange={(event) => onAgentChange(event.currentTarget.value || null)}
          >
            <option value="">{t("agentActivity.log.allAgents")}</option>
            {agents.map((agent) => <option key={agent} value={agent}>{agent}</option>)}
          </select>
        </label>
        <label class="cs-control-field tj-find">
          <span class="cs-control-label">{t("agentActivity.log.find")}</span>
          <input
            class="cs-control-input"
            type="search"
            value={query}
            placeholder={t("agentActivity.trajectory.findPlaceholder")}
            onInput={(event) => onQueryChange(event.currentTarget.value)}
          />
        </label>
        <label class="cs-control-field tj-correlation-field">
          <span class="cs-control-label">{t("agentActivity.trajectory.correlation")}</span>
          <select
            class="cs-control-select"
            value={correlationFilter}
            onChange={(event) => {
              const next = event.currentTarget.value;
              setCorrelationFilter(next);
              if (next) select(next);
            }}
          >
            <option value="">{t("agentActivity.trajectory.allCorrelations")}</option>
            {correlations.map((id) => (
              <option key={id} value={id}>
                {id.length > 36 ? `${id.slice(0, 24)}...${id.slice(-8)}` : id}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          class="cs-control-button is-quiet tj-clear-btn"
          onClick={() => {
            setCorrelationFilter("");
            if (onClearFilters) {
              onClearFilters();
              return;
            }
            onAgentChange(null);
            onQueryChange("");
          }}
        >
          {t("agentActivity.trajectory.clearFilters")}
        </button>
      </div>
      <p class="tj-source" role="status" aria-live="polite">
        {t("agentActivity.trajectory.count", {
          shown: shown.length,
          total: all.length,
          records: items.length,
        })}
        {uncorrelated > 0 ? (
          <>
            <span aria-hidden="true">{" \u00b7 "}</span>
            {uncorrelated === 1
              ? t("agentActivity.trajectory.uncorrelatedOne")
              : t("agentActivity.trajectory.uncorrelated", { count: uncorrelated })}
          </>
        ) : null}
        {olderAvailable ? (
          <>
            <span aria-hidden="true">{" \u00b7 "}</span>
            {t("agentActivity.trajectory.olderAvailable")}
          </>
        ) : null}
      </p>
      {all.length === 0 ? (
        <div class="tj-empty" role="status">
          <strong>{t("agentActivity.trajectory.emptyTitle")}</strong>
          <p>{t("agentActivity.trajectory.emptyBody")}</p>
        </div>
      ) : shown.length === 0 || current === null ? (
        <div class="tj-empty" role="status">
          <strong>{t("agentActivity.trajectory.noMatchesTitle")}</strong>
          <p>{t("agentActivity.trajectory.noMatchesBody")}</p>
        </div>
      ) : (
        <div class="tj-layout">
          <nav class="tj-list" aria-label={t("agentActivity.trajectory.listLabel")}>
            <ul ref={listRef}>
              {grouped.map((group) => {
                const isGroupUpdated = group.members.some((m) =>
                  updatedCorrelationIds.has(m.correlationId));
                return (
                  <li key={group.key}>
                    <TrajectoryListItem
                      trajectory={group.primary}
                      groupCount={group.members.length}
                      highlighted={isGroupUpdated}
                      selected={group.primary.correlationId === current.correlationId}
                      onSelect={() => select(group.primary.correlationId)}
                    />
                  </li>
                );
              })}
            </ul>
          </nav>
          <TrajectoryDetail
            trajectory={current}
            groupMembers={currentGroupMembers}
            selectedAgent={selectedAgent}
            titleRef={titleRef}
            onSelectMember={select}
            onShowLog={onShowLog}
          />
        </div>
      )}
    </section>
  );
}

function initialSelection(trajectories: readonly AgentTrajectory[]): string | null {
  const search = currentRoute().search;
  const requested = search.get("trajectory") ?? search.get("correlation");
  if (requested) return requested;
  const step = Number(search.get("step"));
  if (Number.isInteger(step) && step > 0) {
    return trajectories.find((trajectory) => trajectory.steps.some((item) => item.seq === step))
      ?.correlationId ?? null;
  }
  return null;
}

function TrajectoryListItem({
  trajectory,
  groupCount = 1,
  highlighted = false,
  selected,
  onSelect,
}: {
  readonly trajectory: AgentTrajectory;
  readonly groupCount?: number;
  readonly highlighted?: boolean;
  readonly selected: boolean;
  readonly onSelect: () => void;
}) {
  return (
    <button
      type="button"
      class={`tj-item${highlighted ? " is-live-updated" : ""}`}
      aria-pressed={selected}
      aria-controls="aa-trajectory-detail"
      onClick={onSelect}
    >
      <span class="tj-item-head">
        <strong>{presentTrajectoryTitle(trajectory)}</strong>
        <OutcomePill trajectory={trajectory} />
      </span>
      <span class="tj-item-meta">
        <span class="tj-stack" aria-label={trajectory.agents.join(", ")}>
          {trajectory.agents.map((agent) => <AgentAvatar key={agent} agent={agent} tooltip />)}
        </span>
        <span>
          {t(trajectory.steps.length === 1
            ? "agentActivity.trajectory.itemMetaOne"
            : "agentActivity.trajectory.itemMeta", {
            steps: trajectory.steps.length,
            elapsed: fmtDur(trajectory.endMs - trajectory.startMs),
          })}
        </span>
        {groupCount > 1 ? (
          <span class="tj-group-badge">
            {t("agentActivity.trajectory.groupedCount", { count: groupCount })}
          </span>
        ) : null}
      </span>
      <span class="tj-item-id">
        <code>{trajectory.correlationId}</code>
        <span>{trajectory.tiers.join(" / ")}</span>
      </span>
    </button>
  );
}

function TrajectoryDetail({
  trajectory,
  groupMembers,
  selectedAgent,
  titleRef,
  onSelectMember,
  onShowLog,
}: {
  readonly trajectory: AgentTrajectory;
  readonly groupMembers: readonly AgentTrajectory[];
  readonly selectedAgent: string | null;
  readonly titleRef: { current: HTMLHeadingElement | null };
  readonly onSelectMember: (correlationId: string) => void;
  readonly onShowLog: (correlationId: string) => void;
}) {
  const [open, setOpen] = useState<ReadonlySet<number>>(() => initialOpenSteps(trajectory));
  const lastCorrelationRef = useRef(trajectory.correlationId);
  useEffect(() => {
    if (lastCorrelationRef.current !== trajectory.correlationId) {
      lastCorrelationRef.current = trajectory.correlationId;
      setOpen(initialOpenSteps(trajectory));
    }
  }, [trajectory]);
  const stepRefs = useRef(new Map<number, HTMLDetailsElement>());
  const toggle = (seq: number, next: boolean): void => {
    setOpen((current) => {
      if (current.has(seq) === next) return current;
      const updated = new Set(current);
      if (next) updated.add(seq);
      else updated.delete(seq);
      return updated;
    });
  };
  const jump = (seq: number): void => {
    toggle(seq, true);
    window.requestAnimationFrame(() => {
      const node = stepRefs.current.get(seq);
      if (!node) return;
      const summary = node.querySelector("summary");
      const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      (summary ?? node).scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
      summary?.focus({ preventScroll: true });
    });
  };

  const subtitle = trajectorySubtitle(trajectory);
  const titleText = presentTrajectoryTitle(trajectory);
  return (
    <article id="aa-trajectory-detail" class="tj-detail" aria-labelledby="aa-trajectory-title">
      <header class="tj-hero">
        <div class="tj-hero-copy">
          <span class="tj-eyebrow">
            {t("agentActivity.trajectory.eyebrow")}{" "}
            <Tooltip content={trajectory.correlationId}>
              <code tabIndex={-1}>{trajectory.correlationId}</code>
            </Tooltip>
          </span>
          <h2 id="aa-trajectory-title" ref={titleRef} tabIndex={-1}>{titleText}</h2>
          {subtitle ? <p class="tj-hero-sub">{subtitle}</p> : null}
        </div>
        <OutcomePill trajectory={trajectory} large />
      </header>
      {groupMembers.length > 1 ? (
        <div class="tj-occurrences" role="group" aria-label={t("agentActivity.trajectory.groupedOccurrences", { count: groupMembers.length })}>
          <span class="tj-occurrences-label">
            {t("agentActivity.trajectory.groupedOccurrences", { count: groupMembers.length })}
          </span>
          <div class="tj-occurrences-list">
            {groupMembers.slice(0, 12).map((member, idx) => (
              <button
                key={member.correlationId}
                type="button"
                class="tj-occurrence-btn"
                aria-pressed={member.correlationId === trajectory.correlationId}
                onClick={() => onSelectMember(member.correlationId)}
              >
                <span>#{idx + 1}</span>
                <code>{shortHash(member.correlationId)}</code>
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <ol class="tj-route" aria-label={t("agentActivity.trajectory.route")}>
        {trajectory.agents.map((agent) => {
          const steps = trajectory.steps.filter((step) => step.agent === agent);
          const tone: TrajectoryTone = steps.some((step) => step.tone === "bad")
            ? "bad"
            : steps.some((step) => step.tone === "attention") ? "attention" : "neutral";
          return (
            <li key={agent} data-tone={tone}>
              <AgentAvatar agent={agent} tooltip />
              <span>
                <strong>{agent}</strong>
                <small>{steps.length === 1
                  ? t("agentActivity.trajectory.agentStepsOne")
                  : t("agentActivity.trajectory.agentSteps", { count: steps.length })}</small>
              </span>
            </li>
          );
        })}
      </ol>
      <div class="tj-notices">
        <p class="tj-notice">
          <Icon path={SHIELD} />
          <span>{t("agentActivity.trajectory.projection")}</span>
        </p>
      </div>
      <dl class="tj-metrics">
        <Metric
          label={t("agentActivity.trajectory.metric.elapsed")}
          value={fmtDur(trajectory.endMs - trajectory.startMs)}
          note={t("agentActivity.trajectory.metric.elapsedNote")}
        />
        <Metric
          label={t("agentActivity.trajectory.metric.steps")}
          value={String(trajectory.steps.length)}
          note={trajectory.agents.length === 1
            ? t("agentActivity.trajectory.metric.stepsNoteOne")
            : t("agentActivity.trajectory.metric.stepsNote", { count: trajectory.agents.length })}
        />
        <Metric
          label={t("agentActivity.trajectory.metric.handoffs")}
          value={String(trajectory.handoffs)}
          note={t("agentActivity.trajectory.metric.handoffsNote")}
        />
        <Metric
          label={t("agentActivity.trajectory.metric.flagged")}
          value={String(trajectory.flaggedSteps)}
          note={t("agentActivity.trajectory.metric.flaggedNote")}
        />
      </dl>
      <p class="tj-facts">
        <span>
          {t("agentActivity.trajectory.fact.started")}{" "}
          <Tooltip content={formatConsoleTimestamp(new Date(trajectory.startMs).toISOString())}>
            <strong tabIndex={-1}>{formatCompactStamp(trajectory.startMs)}</strong>
          </Tooltip>
        </span>
        <span>
          {t("agentActivity.trajectory.fact.latest")}{" "}
          <Tooltip content={formatConsoleTimestamp(new Date(trajectory.endMs).toISOString())}>
            <strong tabIndex={-1}>{formatCompactStamp(trajectory.endMs)}</strong>
          </Tooltip>
        </span>
        <span>{t("agentActivity.trajectory.fact.tier")} <strong>{trajectory.tiers.join(" / ") || "-"}</strong></span>
        <span>{t("agentActivity.trajectory.fact.mode")} <strong>{trajectory.modes.join(" / ") || "-"}</strong></span>
        <span>
          {t("agentActivity.trajectory.field.outcome")}{" "}
          <strong>
            {trajectory.latestOutcome
              ? formatOutcomeLabel(trajectory.latestOutcome)
              : t("agentActivity.trajectory.noOutcome")}
          </strong>
        </span>
        {trajectory.sampleSteps > 0 ? (
          <span>{t("agentActivity.trajectory.fact.sample")} <strong>{trajectory.sampleSteps}</strong></span>
        ) : null}
      </p>
      <ol class="tj-phases" aria-label={t("agentActivity.trajectory.phasesLabel")}>
        {trajectoryPhases(trajectory).map((phase) => (
          <li key={phase.id} data-phase={phase.id} data-state={phase.state}>
            <span class="tj-phase-node"><Icon path={PHASE_GLYPH[phase.state]} size={14} /></span>
            <strong>{t(`agentActivity.trajectory.phase.${phase.id}`)}</strong>
            <small>
              {phase.state === "recorded"
                ? t("agentActivity.trajectory.phaseState.recorded", { count: phase.steps })
                : t(`agentActivity.trajectory.phaseState.${phase.state}`)}
            </small>
          </li>
        ))}
      </ol>
      <TrajectoryMap trajectory={trajectory} onJump={jump} />
      <section class="tj-timeline" aria-labelledby="aa-trajectory-steps-title">
        <div class="tj-section-head">
          <div>
            <h3 id="aa-trajectory-steps-title">{t("agentActivity.trajectory.stepsTitle")}</h3>
            <p>{t("agentActivity.trajectory.stepsHint")}</p>
          </div>
          <div class="tj-segmented">
            <button type="button" onClick={() => setOpen(new Set(trajectory.steps.map((step) => step.seq)))}>
              {t("agentActivity.trajectory.expandAll")}
            </button>
            <button type="button" onClick={() => setOpen(new Set())}>
              {t("agentActivity.trajectory.collapseAll")}
            </button>
          </div>
        </div>
        <ol class="tj-steps">
          {trajectory.steps.map((step, index) => (
            <TrajectoryStepView
              key={step.seq}
              step={step}
              index={index}
              trajectory={trajectory}
              next={trajectory.steps[index + 1] ?? null}
              open={open.has(step.seq)}
              context={selectedAgent !== null && step.agent !== selectedAgent}
              detailsRef={(node) => {
                if (node) stepRefs.current.set(step.seq, node);
                else stepRefs.current.delete(step.seq);
              }}
              onToggle={(next) => toggle(step.seq, next)}
            />
          ))}
        </ol>
      </section>
      <footer class="tj-footer">
        <details class="tj-provenance">
          <summary>{t("agentActivity.trajectory.provenance")}</summary>
          <dl class="tj-provenance-grid">
            <div>
              <dt>{t("agentActivity.trajectory.correlation")}</dt>
              <dd><code>{trajectory.correlationId}</code></dd>
            </div>
            <div>
              <dt>{t("agentActivity.trajectory.block.source")}</dt>
              <dd>{t("agentActivity.trajectory.provenanceRecords", { count: trajectory.steps.length })}</dd>
            </div>
            <div>
              <dt>{t("agentActivity.trajectory.route")}</dt>
              <dd>{trajectory.agents.join(" \u2192 ")}</dd>
            </div>
            <div>
              <dt>{t("agentActivity.trajectory.field.entryHash")}</dt>
              <dd><code>{shortHash(trajectory.steps[trajectory.steps.length - 1]!.entryHash)}</code></dd>
            </div>
          </dl>
        </details>
        <div class="tj-actions">
          <a class="cs-control-button is-primary" href={routeHref("trace", { params: { correlation: trajectory.correlationId } })}>
            {t("agentActivity.trajectory.openTrace")}
          </a>
          <button type="button" class="cs-control-button" onClick={() => onShowLog(trajectory.correlationId)}>
            {t("agentActivity.trajectory.showLog")}
          </button>
        </div>
      </footer>
    </article>
  );
}

function initialOpenSteps(trajectory: AgentTrajectory): ReadonlySet<number> {
  const requested = Number(currentRoute().search.get("step"));
  if (Number.isInteger(requested) && trajectory.steps.some((step) => step.seq === requested)) {
    return new Set([requested]);
  }
  const flagged = trajectory.steps.find((step) => step.tone === "attention" || step.tone === "bad");
  return new Set(flagged ? [flagged.seq] : []);
}

function TrajectoryMap({
  trajectory,
  onJump,
}: {
  readonly trajectory: AgentTrajectory;
  readonly onJump: (seq: number) => void;
}) {
  const scale = useMemo(() => trajectoryScale(trajectory), [trajectory]);
  const lanes = trajectory.agents;
  const yOf = (agent: string): number => lanes.indexOf(agent) * LANE_HEIGHT + LANE_HEIGHT / 2;
  const height = lanes.length * LANE_HEIGHT;
  const links = trajectory.steps.slice(1).map((step, offset) => {
    const previous = trajectory.steps[offset]!;
    if (previous.agent === step.agent) return null;
    const x1 = scale.x(previous.endMs) * 10;
    const x2 = scale.x(step.startMs) * 10;
    const mid = (x1 + x2) / 2;
    const y1 = yOf(previous.agent);
    const y2 = yOf(step.agent);
    return `M${x1.toFixed(1)} ${y1} C${mid.toFixed(1)} ${y1} ${mid.toFixed(1)} ${y2} ${x2.toFixed(1)} ${y2}`;
  }).filter((path): path is string => path !== null);
  return (
    <figure class="tj-map" aria-labelledby="aa-trajectory-map-title">
      <figcaption>
        <h3 id="aa-trajectory-map-title">{t("agentActivity.trajectory.mapTitle")}</h3>
        <span>{t("agentActivity.trajectory.mapHint")}</span>
      </figcaption>
      <div class="tj-map-grid">
        <ul class="tj-lanes">
          {lanes.map((agent) => (
            <li key={agent}>
              <Tooltip content={agentLabel(agent)} anchorClassName="tj-lane-anchor">
                <span class="tj-lane-label" tabIndex={-1}>
                  <AgentAvatar agent={agent} />
                  <span>{breakableName(agent)}</span>
                </span>
              </Tooltip>
            </li>
          ))}
        </ul>
        <div class="tj-plot" style={{ height: `${height}px` }}>
          {lanes.map((agent, index) => (
            <span key={agent} class="tj-lane-line" style={{ top: `${index * LANE_HEIGHT + LANE_HEIGHT / 2}px` }} />
          ))}
          {scale.breaks.map((entry, index) => (
            <span key={index} class="tj-break" style={{ left: `${entry.left.toFixed(2)}%` }} />
          ))}
          <svg class="tj-links" viewBox={`0 0 1000 ${height}`} preserveAspectRatio="none" aria-hidden="true">
            {links.map((path) => <path key={path} d={path} />)}
          </svg>
          {trajectory.steps.map((step, index) => {
            const left = scale.x(step.startMs);
            const width = Math.max(scale.x(step.endMs) - left, 0);
            const label = t("agentActivity.trajectory.marker", {
              index: index + 1,
              agent: step.agent,
              category: t(`agentActivity.trajectory.category.${step.category}`),
              duration: step.durationMs === null ? "-" : fmtDur(step.durationMs),
            });
            const outcome = step.outcome ?? step.decision;
            return (
              <Tooltip
                key={step.seq}
                placement="top"
                anchorClassName="tj-mark-anchor"
                anchorStyle={{ top: `${yOf(step.agent) - 22}px`, left: `${left.toFixed(2)}%`, width: `${width.toFixed(2)}%` }}
                content={(
                  <span class="tj-mark-tip">
                    <strong>{t("agentActivity.trajectory.field.position", { index: index + 1 })}{" \u00b7 "}{step.agent}</strong>
                    <span>{t(`agentActivity.trajectory.category.${step.category}`)}</span>
                    <span class="tj-mark-tip-meta">
                      +{fmtDur(step.endMs - trajectory.startMs)}
                      {step.durationMs !== null ? ` \u00b7 ${fmtDur(step.durationMs)}` : ""}
                    </span>
                    {outcome ? <span class="tj-mark-tip-meta">{outcome}</span> : null}
                  </span>
                )}
              >
                <button
                  type="button"
                  class="tj-mark"
                  data-tone={step.tone}
                  aria-label={label}
                  onClick={() => onJump(step.seq)}
                />
              </Tooltip>
            );
          })}
        </div>
        <span />
        <div class="tj-axis">
          <span>+0</span>
          <span>+{fmtDur(trajectory.endMs - trajectory.startMs)}</span>
        </div>
      </div>
      {scale.breaks.length > 0 ? (
        <p class="tj-map-note">
          {t("agentActivity.trajectory.mapGaps", {
            gaps: scale.breaks.map((entry) => fmtDur(entry.realMs)).join(", "),
          })}
        </p>
      ) : null}
    </figure>
  );
}

function TrajectoryStepView({
  step,
  index,
  trajectory,
  next,
  open,
  context,
  detailsRef,
  onToggle,
}: {
  readonly step: TrajectoryStep;
  readonly index: number;
  readonly trajectory: AgentTrajectory;
  readonly next: TrajectoryStep | null;
  readonly open: boolean;
  readonly context: boolean;
  readonly detailsRef: (node: HTMLDetailsElement | null) => void;
  readonly onToggle: (open: boolean) => void;
}) {
  const flagged = step.tone === "attention" || step.tone === "bad";
  const status = step.outcome ?? step.decision;
  const handoffs = step.conversation ?? [];
  return (
    <>
      <li class={`tj-step${context ? " is-context" : ""}`} data-category={step.category} data-tone={step.tone}>
        <details
          ref={detailsRef}
          open={open}
          data-step-seq={step.seq}
          onToggle={(event) => onToggle(event.currentTarget.open)}
        >
          <summary>
            <span class="tj-node" aria-hidden="true"><Icon path={CATEGORY_ICON[step.category]} /></span>
            <span class="tj-step-main">
              <span class="tj-step-head">
                <span class="tj-step-who">
                  <AgentAvatar agent={step.agent} />
                  <strong>{step.agent}</strong>
                  <span>{t(`agentActivity.trajectory.category.${step.category}`)}</span>
                </span>
                <span class="tj-step-when">
                  <time dateTime={step.recordedAt}>+{fmtDur(step.endMs - trajectory.startMs)}</time>
                  <span>{formatConsoleTime(step.recordedAt, undefined, "-", "milliseconds")}</span>
                </span>
              </span>
              <span class="tj-step-summary">
                {presentStepSummary(step)}
              </span>
              <span class="tj-step-foot">
                {status ? (
                  flagged
                    ? <span class="tj-status" data-tone={step.tone}>{formatOutcomeLabel(status)}</span>
                    : <span class="tj-step-state">{formatOutcomeLabel(status)}</span>
                ) : null}
                <code class="tj-step-kind">{step.actionKind}</code>
                {step.durationMs !== null ? <span class="tj-step-ms">{fmtDur(step.durationMs)}</span> : null}
                {(step.repeatCount ?? 1) > 1 ? (
                  <span class="tj-step-repeat">
                    {t("agentActivity.trajectory.repeatedStep", { count: step.repeatCount ?? 1 })}
                  </span>
                ) : null}
                {step.sample ? <span class="tj-step-state">{t("agentActivity.trajectory.sample")}</span> : null}
              </span>
            </span>
            <span class="tj-chevron" aria-hidden="true"><Icon path={CHEVRON} size={14} /></span>
          </summary>
          {open ? <TrajectoryStepBody step={step} index={index} /> : null}
        </details>
      </li>
      {handoffs.map((turn, turnIndex) => (
        <li key={`${step.seq}:${turnIndex}`} class="tj-handoff">
          <span>
            <Icon path={ARROW} size={12} />
            {t("agentActivity.trajectory.message", { from: turn.from, to: turn.to })}
            <q>{turn.text}</q>
          </span>
        </li>
      ))}
      {handoffs.length === 0 && next !== null && next.agent !== step.agent ? (
        <li class="tj-handoff is-transition">
          <span>
            <Icon path={ARROW} size={12} />
            {t("agentActivity.trajectory.transition", { from: step.agent, to: next.agent })}
          </span>
        </li>
      ) : null}
    </>
  );
}

function TrajectoryStepBody({ step, index }: { readonly step: TrajectoryStep; readonly index: number }) {
  const decision: Array<readonly [string, string]> = [];
  if (step.outcome) {
    decision.push([
      t("agentActivity.trajectory.field.outcome"),
      formatOutcomeWithCode(step.outcome),
    ]);
  }
  if (step.decision) {
    decision.push([
      t("agentActivity.trajectory.field.decision"),
      formatOutcomeWithCode(step.decision),
    ]);
  }
  if (step.reason) {
    const label = presentReasonLabel(step.reason);
    decision.push([
      t("agentActivity.trajectory.field.reason"),
      label === step.reason ? step.reason : `${label} (${step.reason})`,
    ]);
  }
  if (step.tier) decision.push([t("agentActivity.trajectory.field.tier"), step.tier]);
  decision.push([t("agentActivity.trajectory.field.mode"), step.mode]);
  if (step.resource) {
    const typePrefix = step.resourceType && step.resource !== step.resourceType
      ? `${presentResourceTypeLabel(step.resourceType)} \u00b7 `
      : step.resourceType && step.resource === step.resourceType
        ? `${presentResourceTypeLabel(step.resourceType)} (`
        : "";
    const typeSuffix = step.resourceType && step.resource === step.resourceType ? ")" : "";
    decision.push([
      t("agentActivity.trajectory.field.resource"),
      `${typePrefix}${step.resource}${typeSuffix}`,
    ]);
  }
  const turns = step.conversation ?? [];
  return (
    <div class="tj-step-body">
      <div class="tj-step-grid">
        {step.inputs || step.outputs || turns.length > 0 ? (
          <div class="tj-col">
            {step.inputs ? <DataBlock heading={t("agentActivity.trajectory.block.received")} pairs={step.inputs} /> : null}
            {step.outputs ? <DataBlock heading={t("agentActivity.trajectory.block.produced")} pairs={step.outputs} /> : null}
            {turns.length > 0 ? (
              <section class="tj-block">
                <h4>{t("agentActivity.trajectory.block.messages")}</h4>
                {turns.map((turn, turnIdx) => (
                  <blockquote key={turnIdx} class="tj-message">
                    <span>
                      <AgentAvatar agent={turn.from} />
                      <strong>{turn.from}</strong>
                      {" \u2192 "}
                      {turn.to}
                    </span>
                    <p>{turn.text}</p>
                  </blockquote>
                ))}
              </section>
            ) : null}
          </div>
        ) : null}
        <div class="tj-col">
          <DataBlock heading={t("agentActivity.trajectory.block.decision")} pairs={decision} />
          {step.fields.length > 0 ? (
            <DataBlock heading={t("agentActivity.trajectory.block.recorded")} pairs={step.fields} mono />
          ) : null}
        </div>
      </div>
      <p class="tj-record">
        <span>{t("agentActivity.trajectory.block.source")}</span>
        <span>{t("agentActivity.trajectory.field.sequence")} <code>{step.seq}</code></span>
        <span>{t("agentActivity.trajectory.field.eventId")} <code>{step.eventId}</code></span>
        <Tooltip content={step.entryHash}>
          <span tabIndex={-1}>{t("agentActivity.trajectory.field.entryHash")} <code>{shortHash(step.entryHash)}</code></span>
        </Tooltip>
        <span>{t("agentActivity.trajectory.field.position", { index: index + 1 })}</span>
      </p>
    </div>
  );
}

function DataBlock({
  heading,
  pairs,
  mono = false,
}: {
  readonly heading: string;
  readonly pairs: ReadonlyArray<readonly [string, string]>;
  readonly mono?: boolean;
}) {
  return (
    <section class="tj-block">
      <h4>{heading}</h4>
      <dl class={`tj-data${mono ? " is-mono" : ""}`}>
        {pairs.map(([key, value]) => (
          <div key={key}>
            <dt>{breakableName(key)}</dt>
            <dd>{renderFieldValue(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function renderFieldValue(value: string) {
  const parsed = parseStructuredFieldValue(value);
  if (parsed.kind === "structured") {
    return (
      <div class="tj-structured-value">
        {parsed.scalars.length > 0 ? (
          <span class="tj-chips">
            {parsed.scalars.map(([k, v], idx) =>
              k ? (
                <span key={idx} class="tj-chip">
                  <span>{k}:</span> {v}
                </span>
              ) : (
                <span key={idx} class="tj-chip">{v}</span>
              ),
            )}
          </span>
        ) : null}
        {parsed.longScalars.length > 0 ? (
          <div class="tj-nested-rows">
            {parsed.longScalars.map(([k, v]) => (
              <div key={k} class="tj-nested-row">
                <code class="tj-nested-key">{breakableName(k)}</code>
                <span class="tj-nested-reason">{v}</span>
              </div>
            ))}
          </div>
        ) : null}
        {parsed.nestedEntries.map(([nestedKey, nestedObj]) => (
          <NestedObjectBlock key={nestedKey} heading={nestedKey} record={nestedObj} />
        ))}
      </div>
    );
  }
  if (parsed.kind === "object" && parsed.directObject) {
    return <NestedObjectBlock heading="" record={parsed.directObject} />;
  }
  return value;
}

function NestedObjectBlock({
  heading,
  record,
}: {
  readonly heading: string;
  readonly record: Record<string, unknown>;
}) {
  const scalars: Array<readonly [string, string]> = [];
  const longScalars: Array<readonly [string, string]> = [];
  const subObjects: Array<readonly [string, Record<string, unknown>]> = [];
  for (const [key, val] of Object.entries(record)) {
    if (val === null || val === undefined || val === "") continue;
    if (Array.isArray(val)) {
      if (val.length > 0) {
        const joined = val.map(String).join(", ");
        if (key.length + joined.length > 28) longScalars.push([key, joined]);
        else scalars.push([key, joined]);
      }
      continue;
    }
    if (typeof val === "object") {
      subObjects.push([key, val as Record<string, unknown>]);
      continue;
    }
    const strVal = String(val);
    if (key.length + strVal.length > 28 || /^\d{4}-\d{2}-\d{2}T/.test(strVal)) {
      longScalars.push([key, strVal]);
    } else {
      scalars.push([key, strVal]);
    }
  }
  if (scalars.length === 0 && longScalars.length === 0 && subObjects.length === 0) return null;
  return (
    <div class="tj-nested-panel">
      {heading ? <div class="tj-nested-title">{breakableName(heading)}</div> : null}
      {scalars.length > 0 ? (
        <span class="tj-chips">
          {scalars.map(([k, v]) => (
            <span key={k} class="tj-chip">
              <span>{k}:</span> {v}
            </span>
          ))}
        </span>
      ) : null}
      {longScalars.length > 0 ? (
        <div class="tj-nested-rows">
          {longScalars.map(([k, v]) => (
            <div key={k} class="tj-nested-row">
              <code class="tj-nested-key">{breakableName(k)}</code>
              <span class="tj-nested-reason">{v}</span>
            </div>
          ))}
        </div>
      ) : null}
      {subObjects.map(([subKey, subObj]) => (
        <div key={subKey} class="tj-nested-sub">
          <div class="tj-nested-subtitle">{breakableName(subKey)}</div>
          <div class="tj-nested-rows">
            {Object.entries(subObj).map(([axisKey, axisVal]) => {
              if (axisVal === null || axisVal === undefined) return null;
              if (typeof axisVal === "object" && !Array.isArray(axisVal)) {
                const axisRec = axisVal as Record<string, unknown>;
                const level = typeof axisRec["level"] === "string" ? axisRec["level"] : null;
                const reason = typeof axisRec["reason"] === "string" ? axisRec["reason"] : null;
                if (level || reason) {
                  return (
                    <div key={axisKey} class="tj-nested-row">
                      <code class="tj-nested-key">{axisKey}</code>
                      {level ? <span class="tj-chip">{level}</span> : null}
                      {reason ? <span class="tj-nested-reason">{reason}</span> : null}
                    </div>
                  );
                }
                const pairs = Object.entries(axisRec)
                  .filter(([, v]) => v !== null && v !== undefined && v !== "")
                  .map(([k, v]) => `${k}: ${String(v)}`)
                  .join(" \u00b7 ");
                return (
                  <div key={axisKey} class="tj-nested-row">
                    <code class="tj-nested-key">{axisKey}</code>
                    <span class="tj-nested-reason">{pairs}</span>
                  </div>
                );
              }
              return (
                <div key={axisKey} class="tj-nested-row">
                  <code class="tj-nested-key">{axisKey}</code>
                  <span class="tj-nested-reason">{String(axisVal)}</span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function OutcomePill({ trajectory, large = false }: { readonly trajectory: AgentTrajectory; readonly large?: boolean }) {
  return (
    <span class={`tj-status${large ? " tj-status-lg" : ""}`} data-tone={trajectory.tone}>
      {trajectory.latestOutcome
        ? formatOutcomeLabel(trajectory.latestOutcome)
        : t("agentActivity.trajectory.noOutcome")}
    </span>
  );
}

function Metric({ label, value, note }: { readonly label: string; readonly value: string; readonly note: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}<small>{note}</small></dd>
    </div>
  );
}

function AgentAvatar({ agent, tooltip = false }: { readonly agent: string; readonly tooltip?: boolean }) {
  const role = agentRoleTitle(agent);
  const avatar = (
    <span class="tj-avatar" tabIndex={tooltip ? -1 : undefined}>
      {role ? (
        <img src={`${import.meta.env.BASE_URL}agent-icons/${agent.toLowerCase()}.svg`} alt="" />
      ) : (
        <span aria-hidden="true">{agent.slice(0, 1).toUpperCase()}</span>
      )}
    </span>
  );
  if (!tooltip) return avatar;
  return <Tooltip content={agentLabel(agent)}>{avatar}</Tooltip>;
}

function agentLabel(agent: string): string {
  const role = agentRoleTitle(agent);
  return role ? `${agent} \u00b7 ${role}` : agent;
}

/** Lets long producer ids wrap at their own separators instead of being cut. */
function breakableName(name: string) {
  return name.split(/(?<=[._])/).map((part, index) => (
    <Fragment key={index}>{index > 0 ? <wbr /> : null}{part}</Fragment>
  ));
}

function Icon({ path, size = 16 }: { readonly path: string; readonly size?: number }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} aria-hidden="true" focusable="false">
      {path ? <path d={path} /> : null}
    </svg>
  );
}

function shortHash(value: string): string {
  return value.length > 16 ? `${value.slice(0, 10)}\u2026${value.slice(-6)}` : value;
}

function formatCompactStamp(ms: number): string {
  const iso = new Date(ms).toISOString();
  const datePart = iso.slice(0, 10);
  return `${datePart} ${formatConsoleTime(iso, undefined, "-", "seconds")}`;
}

function formatActionKindLabel(actionKind: string): string {
  const readable = actionKind
    .split(".")
    .map((part) => part.replace(/[-_]+/g, " ").trim())
    .filter(Boolean)
    .join(" \u00b7 ");
  return readable ? readable.charAt(0).toUpperCase() + readable.slice(1) : actionKind;
}
