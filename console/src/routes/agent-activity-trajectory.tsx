import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import type { AgentStreamStatus } from "../hooks/use-agent-stream";
import { observationSourceLabel, type ObservationSource } from "../hooks/observation-source";
import { t } from "./i18n/agent-trajectory";
import { currentRoute, replaceRouteState, routeHref } from "../router";
import { formatConsoleTime, formatConsoleTimestamp } from "../time-format";
import type { AuditItem } from "../types";
import { agentOf, fmtDur } from "./agent-activity-semantics";
import {
  buildAgentTrajectories,
  filterAgentTrajectories,
  trajectoryPhases,
  trajectoryScale,
  uncorrelatedAuditCount,
  type AgentTrajectory,
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
  readonly selectedAgent: string | null;
  readonly query: string;
  readonly olderAvailable: boolean;
  readonly streamStatus: AgentStreamStatus;
  readonly streamSource: ObservationSource;
  readonly onAgentChange: (agent: string | null) => void;
  readonly onQueryChange: (query: string) => void;
  readonly onShowLog: (correlationId: string) => void;
}

export function AgentTrajectories({
  items,
  selectedAgent,
  query,
  olderAvailable,
  streamStatus,
  streamSource,
  onAgentChange,
  onQueryChange,
  onShowLog,
}: Props) {
  const all = useMemo(() => buildAgentTrajectories(items, agentOf), [items]);
  const shown = useMemo(
    () => filterAgentTrajectories(all, selectedAgent, query),
    [all, selectedAgent, query],
  );
  const agents = useMemo(() => {
    const names = new Set(all.flatMap((trajectory) => trajectory.agents));
    if (selectedAgent !== null) names.add(selectedAgent);
    return [...names].sort((left, right) => left.localeCompare(right));
  }, [all, selectedAgent]);
  const [selectedId, setSelectedId] = useState<string | null>(() => initialSelection(all));
  const current = shown.find((trajectory) => trajectory.correlationId === selectedId) ?? shown[0] ?? null;
  const titleRef = useRef<HTMLHeadingElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const uncorrelated = useMemo(() => uncorrelatedAuditCount(items), [items]);

  useEffect(() => {
    if (selectedId === null) setSelectedId(initialSelection(all));
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
    setSelectedId(correlationId);
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
        {selectedAgent !== null || query ? (
          <button
            type="button"
            class="cs-control-button is-quiet"
            onClick={() => {
              onAgentChange(null);
              onQueryChange("");
            }}
          >
            {t("agentActivity.trajectory.clearFilters")}
          </button>
        ) : null}
      </div>
      <p class="tj-source">
        {t("agentActivity.trajectory.count", {
          shown: shown.length,
          total: all.length,
          records: items.length,
        })}
        <span aria-hidden="true">{" \u00b7 "}</span>
        {t(`agents.connection.${streamStatus}`)} - {observationSourceLabel(streamSource)}
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
              {shown.map((trajectory) => (
                <li key={trajectory.correlationId}>
                  <TrajectoryListItem
                    trajectory={trajectory}
                    selected={trajectory === current}
                    onSelect={() => select(trajectory.correlationId)}
                  />
                </li>
              ))}
            </ul>
          </nav>
          <TrajectoryDetail
            key={current.correlationId}
            trajectory={current}
            selectedAgent={selectedAgent}
            titleRef={titleRef}
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
  selected,
  onSelect,
}: {
  readonly trajectory: AgentTrajectory;
  readonly selected: boolean;
  readonly onSelect: () => void;
}) {
  return (
    <button
      type="button"
      class="tj-item"
      aria-pressed={selected}
      aria-controls="aa-trajectory-detail"
      onClick={onSelect}
    >
      <span class="tj-item-head">
        <strong>{trajectory.title}</strong>
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
  selectedAgent,
  titleRef,
  onShowLog,
}: {
  readonly trajectory: AgentTrajectory;
  readonly selectedAgent: string | null;
  readonly titleRef: { current: HTMLHeadingElement | null };
  readonly onShowLog: (correlationId: string) => void;
}) {
  const [open, setOpen] = useState<ReadonlySet<number>>(() => initialOpenSteps(trajectory));
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
      const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      node.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
      node.querySelector("summary")?.focus({ preventScroll: true });
    });
  };

  return (
    <article id="aa-trajectory-detail" class="tj-detail" aria-labelledby="aa-trajectory-title">
      <header class="tj-hero">
        <div class="tj-hero-copy">
          <span class="tj-eyebrow">
            {t("agentActivity.trajectory.eyebrow")} <code>{trajectory.correlationId}</code>
          </span>
          <h2 id="aa-trajectory-title" ref={titleRef} tabIndex={-1}>{trajectory.title}</h2>
        </div>
        <OutcomePill trajectory={trajectory} large />
      </header>
      <ol class="tj-route" aria-label={t("agentActivity.trajectory.route")}>
        {trajectory.agents.map((agent) => {
          const steps = trajectory.steps.filter((step) => step.agent === agent);
          const tone: TrajectoryTone = steps.some((step) => step.tone === "bad")
            ? "bad"
            : steps.some((step) => step.tone === "attention") ? "attention" : "neutral";
          return (
            <li key={agent} data-tone={tone}>
              <AgentAvatar agent={agent} />
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
      <p class="tj-notice">
        <Icon path={SHIELD} />
        <span>{t("agentActivity.trajectory.projection")}</span>
      </p>
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
        <span>{t("agentActivity.trajectory.fact.started")} <strong>{formatConsoleTimestamp(new Date(trajectory.startMs).toISOString())}</strong></span>
        <span>{t("agentActivity.trajectory.fact.latest")} <strong>{formatConsoleTimestamp(new Date(trajectory.endMs).toISOString())}</strong></span>
        <span>{t("agentActivity.trajectory.fact.tier")} <strong>{trajectory.tiers.join(" / ") || "-"}</strong></span>
        <span>{t("agentActivity.trajectory.fact.mode")} <strong>{trajectory.modes.join(" / ") || "-"}</strong></span>
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
        <a class="cs-control-button is-primary" href={routeHref("trace", { params: { correlation: trajectory.correlationId } })}>
          {t("agentActivity.trajectory.openTrace")}
        </a>
        <button type="button" class="cs-control-button" onClick={() => onShowLog(trajectory.correlationId)}>
          {t("agentActivity.trajectory.showLog")}
        </button>
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
              <AgentAvatar agent={agent} tooltip />
              <span>{agent}</span>
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
            return (
              <Tooltip key={step.seq} content={label}>
                <button
                  type="button"
                  class="tj-mark"
                  data-tone={step.tone}
                  aria-label={label}
                  style={{ top: `${yOf(step.agent) - 22}px`, left: `${left.toFixed(2)}%`, width: `${width.toFixed(2)}%` }}
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
              <span class="tj-step-summary">{step.summary}</span>
              <span class="tj-step-foot">
                {status ? (
                  flagged
                    ? <span class="tj-status" data-tone={step.tone}>{status}</span>
                    : <span class="tj-step-state">{status}</span>
                ) : null}
                <code class="tj-step-kind">{step.actionKind}</code>
                {step.durationMs !== null ? <span class="tj-step-ms">{fmtDur(step.durationMs)}</span> : null}
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
  if (step.outcome) decision.push([t("agentActivity.trajectory.field.outcome"), step.outcome]);
  if (step.decision) decision.push([t("agentActivity.trajectory.field.decision"), step.decision]);
  if (step.reason) decision.push([t("agentActivity.trajectory.field.reason"), step.reason]);
  if (step.tier) decision.push([t("agentActivity.trajectory.field.tier"), step.tier]);
  decision.push([t("agentActivity.trajectory.field.mode"), step.mode]);
  if (step.resource) decision.push([t("agentActivity.trajectory.field.resource"), step.resource]);
  return (
    <div class="tj-step-body">
      <div class="tj-step-grid">
        {step.inputs || step.outputs ? (
          <div class="tj-col">
            {step.inputs ? <DataBlock heading={t("agentActivity.trajectory.block.received")} pairs={step.inputs} /> : null}
            {step.outputs ? <DataBlock heading={t("agentActivity.trajectory.block.produced")} pairs={step.outputs} /> : null}
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
            <dt>{key}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function OutcomePill({ trajectory, large = false }: { readonly trajectory: AgentTrajectory; readonly large?: boolean }) {
  return (
    <span class={`tj-status${large ? " tj-status-lg" : ""}`} data-tone={trajectory.tone}>
      {trajectory.latestOutcome ?? t("agentActivity.trajectory.noOutcome")}
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
  return <Tooltip content={role ? `${agent} \u00b7 ${role}` : agent}>{avatar}</Tooltip>;
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
