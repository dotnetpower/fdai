import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { SegmentedControl } from "./form-controls";
import { StatusBadge, type BadgeTone } from "./status-badge";
import { Tooltip } from "./tooltip";

export type EvidenceState = "measured" | "unavailable" | "not-connected" | "simulated";

export type SparkKind = "area" | "dual-bar" | "line" | "step";

export interface SparkSpec {
  readonly kind: SparkKind;
  readonly values: readonly number[];
  readonly secondaryValues?: readonly number[];
  readonly color?: string;
  readonly secondaryColor?: string;
  readonly ariaLabel: string;
}

export interface SparkMetricCardProps {
  readonly id?: string;
  readonly label: string;
  readonly value: string | number;
  readonly unit?: string;
  readonly delta?: string;
  readonly deltaTone?: BadgeTone;
  readonly evidenceState?: EvidenceState;
  readonly unmeasuredLabel?: string;
  readonly spark?: SparkSpec;
  readonly footerLeft?: ComponentChildren;
  readonly footerRight?: ComponentChildren;
  readonly onOpenDetail?: () => void;
  readonly detailAriaLabel?: string;
}

const EVIDENCE_TONE: Record<EvidenceState, BadgeTone> = {
  measured: "live",
  unavailable: "neutral",
  "not-connected": "sre",
  simulated: "info",
};

function renderSparkSvg(spec: SparkSpec) {
  const width = 200;
  const height = 40;
  const padY = 4;
  const values = spec.values;
  if (values.length === 0) return null;

  const secondary = spec.secondaryValues ?? [];
  const all = spec.kind === "dual-bar"
    ? values.map((v, i) => v + (secondary[i] ?? 0))
    : values;
  const maxVal = Math.max(...all, 1);
  const minVal = spec.kind === "dual-bar" ? 0 : Math.min(...values, 0);
  const span = Math.max(maxVal - minVal, 1);
  const stroke = spec.color ?? "var(--sig-live, #0f766e)";
  const secondaryStroke = spec.secondaryColor ?? "var(--sig-sec, #a63446)";

  if (spec.kind === "dual-bar") {
    const gap = 3;
    const barW = Math.max(3, (width - gap * (values.length - 1)) / values.length);
    return (
      <svg class="cs-spark-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={spec.ariaLabel}>
        {values.map((v, i) => {
          const s = secondary[i] ?? 0;
          const totalH = ((v + s) / maxVal) * (height - padY * 2);
          const primaryH = ((v) / maxVal) * (height - padY * 2);
          const secondaryH = Math.max(0, totalH - primaryH);
          const x = i * (barW + gap);
          const yPrimary = height - padY - primaryH;
          const ySecondary = yPrimary - secondaryH;
          return (
            <g key={i}>
              {secondaryH > 0 ? (
                <rect x={x} y={ySecondary} width={barW} height={secondaryH} rx="1.5" fill={secondaryStroke} />
              ) : null}
              <rect x={x} y={yPrimary} width={barW} height={Math.max(1.5, primaryH)} rx="1.5" fill={stroke} />
            </g>
          );
        })}
      </svg>
    );
  }

  const coords = values.map((v, i) => {
    const x = values.length === 1 ? width / 2 : (i / (values.length - 1)) * width;
    const y = height - padY - ((v - minVal) / span) * (height - padY * 2);
    return { x, y };
  });

  if (spec.kind === "step") {
    const parts: string[] = [];
    coords.forEach((pt, idx) => {
      if (idx === 0) {
        parts.push(`M ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`);
      } else {
        parts.push(`H ${pt.x.toFixed(1)} V ${pt.y.toFixed(1)}`);
      }
    });
    const lineD = parts.join(" ");
    const areaD = `${lineD} V ${height - padY} H 0 Z`;
    return (
      <svg class="cs-spark-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={spec.ariaLabel}>
        <path d={areaD} fill={stroke} fill-opacity="0.14" />
        <path d={lineD} fill="none" stroke={stroke} stroke-width="1.8" />
      </svg>
    );
  }

  const firstPt = coords[0];
  const lastPt = coords[coords.length - 1];
  if (!firstPt || !lastPt) return null;
  const linePoints = coords.map((pt) => `${pt.x.toFixed(1)},${pt.y.toFixed(1)}`).join(" ");
  const areaD = `M ${firstPt.x.toFixed(1)} ${height - padY} `
    + coords.map((pt) => `L ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`).join(" ")
    + ` L ${lastPt.x.toFixed(1)} ${height - padY} Z`;

  return (
    <svg class="cs-spark-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={spec.ariaLabel}>
      {spec.kind === "area" ? <path d={areaD} fill={stroke} fill-opacity="0.15" /> : null}
      <polyline
        fill="none"
        stroke={stroke}
        stroke-width="1.8"
        stroke-linejoin="round"
        stroke-linecap="round"
        points={linePoints}
      />
    </svg>
  );
}

export function SparkMetricCard({
  id,
  label,
  value,
  unit,
  delta,
  deltaTone = "neutral",
  evidenceState = "measured",
  unmeasuredLabel = "Unmeasured",
  spark,
  footerLeft,
  footerRight,
  onOpenDetail,
  detailAriaLabel,
}: SparkMetricCardProps) {
  const isMeasured = evidenceState === "measured" || evidenceState === "simulated";
  const displayValue = isMeasured ? value : "-";
  const content = (
    <>
      <div class="cs-spark-head">
        <span class="cs-spark-label">{label}</span>
        {onOpenDetail ? (
          <svg
            class="cs-spark-cue"
            width="14"
            height="14"
            viewBox="0 0 14 14"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M3 7h8M8 4l3 3-3 3" />
          </svg>
        ) : null}
      </div>
      <div class="cs-spark-main">
        <span class="cs-spark-value-group">
          <span class="cs-spark-value">{displayValue}</span>
          {isMeasured && unit ? <span class="cs-spark-unit">{unit}</span> : null}
        </span>
        {delta ? (
          <StatusBadge tone={isMeasured ? deltaTone : EVIDENCE_TONE[evidenceState]} label={delta} />
        ) : !isMeasured ? (
          <StatusBadge tone={EVIDENCE_TONE[evidenceState]} label={unmeasuredLabel} />
        ) : null}
      </div>
      {spark && isMeasured && spark.values.length > 0 ? (
        renderSparkSvg(spark)
      ) : (
        <div class="cs-spark-unmeasured" role="status">
          {unmeasuredLabel}
        </div>
      )}
      {(footerLeft || footerRight) ? (
        <div class="cs-spark-foot">
          <span>{footerLeft}</span>
          <span>{footerRight}</span>
        </div>
      ) : null}
    </>
  );

  if (onOpenDetail) {
    return (
      <button
        id={id}
        type="button"
        class="cs-spark-panel cs-spark-panel--interactive"
        aria-label={detailAriaLabel ?? label}
        onClick={onOpenDetail}
      >
        {content}
      </button>
    );
  }

  return (
    <article id={id} class="cs-spark-panel">
      {content}
    </article>
  );
}

export type TelemetryCategory = "auto" | "sre" | "sec" | "human";

export interface TimelinePoint {
  readonly id: string;
  readonly timeLabel: string;
  readonly riskScore: number;
  readonly category: TelemetryCategory;
  readonly summary: string;
  readonly forecast?: boolean;
  readonly forecastBasis?: string;
}

export interface TimelineBucket {
  readonly label: string;
  readonly auto: number;
  readonly sre: number;
  readonly sec: number;
  readonly human: number;
  readonly forecast?: boolean;
}

export interface DomainBreakdownRow {
  readonly id: string;
  readonly label: string;
  readonly auto: number;
  readonly sre: number;
  readonly sec: number;
  readonly human: number;
}

export type TimelineView = "scatter" | "stacked" | "domain";
export type TimelineWindow = "15m" | "1h" | "24h";

export interface LiveScatterTimelineProps {
  readonly title: string;
  readonly subtitle?: string;
  readonly streamState: "live" | "paused" | "static" | "unavailable";
  readonly view: TimelineView;
  readonly onViewChange: (view: TimelineView) => void;
  readonly window?: TimelineWindow;
  readonly onWindowChange?: (window: TimelineWindow) => void;
  readonly onTogglePause?: () => void;
  readonly points: readonly TimelinePoint[];
  readonly buckets: readonly TimelineBucket[];
  readonly domains?: readonly DomainBreakdownRow[];
  readonly visibleSeries?: Readonly<Record<TelemetryCategory, boolean>>;
  readonly onToggleSeries?: (category: TelemetryCategory) => void;
  readonly summaryText?: string;
  readonly labels?: {
    readonly scatter?: string;
    readonly stacked?: string;
    readonly domain?: string;
    readonly auto?: string;
    readonly sre?: string;
    readonly sec?: string;
    readonly human?: string;
    readonly now?: string;
    readonly unavailable?: string;
    readonly pause?: string;
    readonly resume?: string;
    readonly timeWindowAria?: string;
    readonly seriesFiltersAria?: string;
    readonly riskAxis?: string;
    readonly forecastZone?: string;
    readonly streamLive?: string;
    readonly streamPaused?: string;
    readonly streamStatic?: string;
    readonly streamUnavailable?: string;
  };
  readonly children?: ComponentChildren;
}

const SERIES_COLOR: Record<TelemetryCategory, string> = {
  auto: "var(--sig-auto-top, #5a9a92)",
  sre: "var(--sig-sre, #c86d18)",
  sec: "var(--sig-sec, #a63446)",
  human: "var(--sig-human, #4a2574)",
};

export function LiveScatterTimeline({
  title,
  subtitle,
  streamState,
  view,
  onViewChange,
  window,
  onWindowChange,
  onTogglePause,
  points,
  buckets,
  domains = [],
  visibleSeries = { auto: true, sre: true, sec: true, human: true },
  onToggleSeries,
  summaryText,
  labels,
  children,
}: LiveScatterTimelineProps) {
  const [activePoint, setActivePoint] = useState<TimelinePoint | null>(null);
  const scatterLabel = labels?.scatter ?? "Scatter";
  const stackedLabel = labels?.stacked ?? "Stacked";
  const domainLabel = labels?.domain ?? "Domain";
  const nowLabel = labels?.now ?? "NOW";
  const unavailableLabel = labels?.unavailable ?? "Telemetry stream unavailable";
  const pauseLabel = labels?.pause ?? "Pause";
  const resumeLabel = labels?.resume ?? "Resume";
  const timeWindowAria = labels?.timeWindowAria ?? "Time window";
  const seriesFiltersAria = labels?.seriesFiltersAria ?? "Series filters";
  const riskAxisLabel = labels?.riskAxis ?? "Risk";
  const forecastZoneLabel = labels?.forecastZone ?? "+Horizon";
  const streamBadgeLabel = streamState === "live"
    ? (labels?.streamLive ?? "LIVE")
    : streamState === "paused"
    ? (labels?.streamPaused ?? "PAUSED")
    : streamState === "static"
    ? (labels?.streamStatic ?? "SAMPLE")
    : (labels?.streamUnavailable ?? "UNAVAILABLE");

  const streamTone: BadgeTone =
    streamState === "live" ? "live" : streamState === "paused" ? "sre" : "neutral";

  const visiblePoints = points.filter((pt) => visibleSeries[pt.category]);
  const svgW = 760;
  const svgH = 240;
  const padL = 42;
  const padR = 20;
  const padT = 18;
  const padB = 30;
  const plotW = svgW - padL - padR;
  const plotH = svgH - padT - padB;
  const nowX = padL + plotW * 0.78;
  const hasForecast = visiblePoints.some((pt) => pt.forecast);

  const seriesItems: readonly { key: TelemetryCategory; label: string }[] = [
    { key: "auto", label: labels?.auto ?? "Auto-resolved" },
    { key: "sre", label: labels?.sre ?? "SRE" },
    { key: "sec", label: labels?.sec ?? "Security" },
    { key: "human", label: labels?.human ?? "Human" },
  ];

  return (
    <section class="cs-timeline-panel" aria-label={title}>
      <div class="cs-timeline-head">
        <div class="cs-timeline-title-wrap">
          <div class="cs-timeline-title-row">
            <h3 class="cs-timeline-title">{title}</h3>
            <StatusBadge tone={streamTone} label={streamBadgeLabel} />
          </div>
          {subtitle ? <p class="cs-timeline-subtitle">{subtitle}</p> : null}
        </div>
        <div class="cs-timeline-controls">
          <SegmentedControl
            ariaLabel={title}
            role="tablist"
            value={view}
            onChange={onViewChange}
            options={[
              { value: "scatter", label: scatterLabel },
              { value: "stacked", label: stackedLabel },
              { value: "domain", label: domainLabel },
            ]}
          />
          {window && onWindowChange ? (
            <SegmentedControl
              ariaLabel={timeWindowAria}
              value={window}
              onChange={onWindowChange}
              options={[
                { value: "15m", label: "15m" },
                { value: "1h", label: "1h" },
                { value: "24h", label: "24h" },
              ]}
            />
          ) : null}
          {onTogglePause ? (
            <button type="button" class="cs-filter-reset" onClick={onTogglePause}>
              {streamState === "paused" ? resumeLabel : pauseLabel}
            </button>
          ) : null}
        </div>
      </div>

      {(onToggleSeries || summaryText) ? (
        <div class="cs-timeline-meta-strip">
          {onToggleSeries ? (
            <div class="cs-timeline-legend" role="group" aria-label={seriesFiltersAria}>
              {seriesItems.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  class="cs-legend-chip"
                  aria-pressed={visibleSeries[item.key] ? "true" : "false"}
                  onClick={() => onToggleSeries(item.key)}
                >
                  <span
                    class="cs-status-dot"
                    style={{ background: SERIES_COLOR[item.key] }}
                    aria-hidden="true"
                  />
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          ) : <div />}
          {summaryText ? <div class="cs-timeline-summary">{summaryText}</div> : null}
        </div>
      ) : null}

      {streamState === "unavailable" ? (
        <div class="cs-spark-unmeasured" role="status">{unavailableLabel}</div>
      ) : view === "domain" ? (
        domains.length === 0 ? (
          <div class="cs-spark-unmeasured" role="status">{unavailableLabel}</div>
        ) : (
          <div class="cs-domain-bars">
            {domains.map((row) => {
              const total = Math.max(row.auto + row.sre + row.sec + row.human, 1);
              return (
                <div key={row.id} class="cs-domain-row">
                  <span>{row.label}</span>
                  <div class="cs-domain-track" aria-label={`${row.label}: ${row.auto + row.sre + row.sec + row.human}`}>
                    <span style={{ width: `${(row.auto / total) * 100}%`, background: SERIES_COLOR.auto }} />
                    <span style={{ width: `${(row.sre / total) * 100}%`, background: SERIES_COLOR.sre }} />
                    <span style={{ width: `${(row.sec / total) * 100}%`, background: SERIES_COLOR.sec }} />
                    <span style={{ width: `${(row.human / total) * 100}%`, background: SERIES_COLOR.human }} />
                  </div>
                  <span class="cs-seg-count">{row.auto + row.sre + row.sec + row.human}</span>
                </div>
              );
            })}
          </div>
        )
      ) : view === "stacked" ? (
        <div class="cs-timeline-stage">
          <svg class="cs-timeline-svg" viewBox={`0 0 ${svgW} ${svgH}`} role="img" aria-label={stackedLabel}>
            {[25, 50, 75].map((pct) => {
              const y = padT + plotH * (1 - pct / 100);
              return (
                <line
                  key={pct}
                  x1={padL}
                  y1={y}
                  x2={svgW - padR}
                  y2={y}
                  stroke="var(--cs-hairline)"
                  stroke-dasharray="3 3"
                />
              );
            })}
            {buckets.map((bucket, idx) => {
              const maxBucket = Math.max(
                ...buckets.map((b) =>
                  (visibleSeries.auto ? b.auto : 0)
                  + (visibleSeries.sre ? b.sre : 0)
                  + (visibleSeries.sec ? b.sec : 0)
                  + (visibleSeries.human ? b.human : 0),
                ),
                1,
              );
              const stepW = plotW / Math.max(buckets.length, 1);
              const barW = Math.max(8, stepW - 6);
              const x = padL + idx * stepW + 3;
              const segs: readonly { key: TelemetryCategory; count: number }[] = [
                { key: "auto", count: visibleSeries.auto ? bucket.auto : 0 },
                { key: "sre", count: visibleSeries.sre ? bucket.sre : 0 },
                { key: "sec", count: visibleSeries.sec ? bucket.sec : 0 },
                { key: "human", count: visibleSeries.human ? bucket.human : 0 },
              ];
              let yCursor = padT + plotH;
              return (
                <g key={bucket.label} opacity={bucket.forecast ? 0.65 : 1}>
                  {segs.map((seg) => {
                    if (seg.count <= 0) return null;
                    const h = (seg.count / maxBucket) * plotH;
                    yCursor -= h;
                    return (
                      <rect
                        key={seg.key}
                        x={x}
                        y={yCursor}
                        width={barW}
                        height={Math.max(2, h)}
                        rx="2"
                        fill={SERIES_COLOR[seg.key]}
                      />
                    );
                  })}
                  <text
                    x={x + barW / 2}
                    y={svgH - 8}
                    text-anchor="middle"
                    fill="var(--cs-text-soft)"
                    font-size="12"
                  >
                    {bucket.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      ) : (
        <div class="cs-timeline-stage">
          <svg class="cs-timeline-svg" viewBox={`0 0 ${svgW} ${svgH}`} role="img" aria-label={scatterLabel}>
            <rect
              x={nowX}
              y={padT}
              width={svgW - padR - nowX}
              height={plotH}
              fill="var(--sig-live, #0f766e)"
              fill-opacity="0.045"
            />
            {[0, 25, 50, 75, 100].map((score) => {
              const y = padT + plotH * (1 - score / 100);
              return (
                <g key={score}>
                  <line
                    x1={padL}
                    y1={y}
                    x2={svgW - padR}
                    y2={y}
                    stroke="var(--cs-hairline)"
                    stroke-dasharray={score === 0 ? undefined : "3 3"}
                  />
                  <text x={padL - 8} y={y + 4} text-anchor="end" fill="var(--cs-text-soft)" font-size="12">
                    {score}
                  </text>
                </g>
              );
            })}
            <text x={padL} y={12} fill="var(--cs-text-soft)" font-size="12">
              {riskAxisLabel}
            </text>
            <line
              x1={nowX}
              y1={padT}
              x2={nowX}
              y2={padT + plotH}
              stroke="var(--sig-live, #0f766e)"
              stroke-width="1.4"
              stroke-dasharray="4 3"
            />
            <text x={nowX + 6} y={padT + 13} fill="var(--sig-live-text, #0f5f59)" font-size="12" font-weight="600">
              {hasForecast ? forecastZoneLabel : nowLabel}
            </text>
            {buckets.slice(0, 8).map((bucket, idx, list) => {
              const x = padL + ((idx + 0.5) / Math.max(list.length, 1)) * (nowX - padL - 12);
              return (
                <text
                  key={`tick-${bucket.label}-${idx}`}
                  x={x}
                  y={svgH - 8}
                  text-anchor="middle"
                  fill="var(--cs-text-soft)"
                  font-size="12"
                >
                  {bucket.label}
                </text>
              );
            })}
            <text x={nowX} y={svgH - 8} text-anchor="middle" fill="var(--sig-live-text, #0f5f59)" font-size="12" font-weight="600">
              {nowLabel}
            </text>
            {(() => {
              const pastPoints = visiblePoints.filter((p) => !p.forecast);
              const futurePoints = visiblePoints.filter((p) => p.forecast);
              return visiblePoints.map((pt) => {
                const pastIdx = pastPoints.findIndex((p) => p.id === pt.id);
                const futureIdx = futurePoints.findIndex((p) => p.id === pt.id);
                const x = pt.forecast
                  ? nowX + 18 + ((futureIdx + 1) / (futurePoints.length + 1)) * (svgW - padR - nowX - 24)
                  : padL + ((pastIdx + 0.5) / Math.max(pastPoints.length, 1)) * (nowX - padL - 12);
                const clamped = Math.max(4, Math.min(96, pt.riskScore));
                const y = padT + plotH * (1 - clamped / 100);
                const color = SERIES_COLOR[pt.category];

                if (pt.forecast) {
                  return (
                    <g
                      key={pt.id}
                      tabIndex={0}
                      role="button"
                      aria-label={`${pt.timeLabel} ${pt.summary}`}
                      onMouseEnter={() => setActivePoint(pt)}
                      onFocus={() => setActivePoint(pt)}
                      onClick={() => setActivePoint(pt)}
                    >
                      <circle
                        cx={x}
                        cy={y}
                        r="11"
                        fill="none"
                        stroke={color}
                        stroke-dasharray="3 2"
                        stroke-width="1.3"
                      />
                      <polygon
                        points={`${x},${y - 5.5} ${x + 5.5},${y} ${x},${y + 5.5} ${x - 5.5},${y}`}
                        fill={color}
                      />
                    </g>
                  );
                }

                return (
                  <circle
                    key={pt.id}
                    cx={x}
                    cy={y}
                    r={pt.category === "human" || pt.category === "sec" ? 5.8 : 4.5}
                    fill={color}
                    fill-opacity={pt.category === "auto" ? 0.85 : 0.96}
                    tabIndex={0}
                    role="button"
                    aria-label={`${pt.timeLabel} ${pt.summary}`}
                    onMouseEnter={() => setActivePoint(pt)}
                    onFocus={() => setActivePoint(pt)}
                    onClick={() => setActivePoint(pt)}
                  />
                );
              });
            })()}
          </svg>
          {activePoint ? (
            <div class="cs-timeline-tooltip" role="status">
              <strong>{activePoint.timeLabel}</strong> - {activePoint.summary} ({riskAxisLabel} {activePoint.riskScore})
              {activePoint.forecastBasis ? <div>{activePoint.forecastBasis}</div> : null}
            </div>
          ) : null}
        </div>
      )}

      {children}
    </section>
  );
}

export interface SignalRailItem {
  readonly id: string;
  readonly category: TelemetryCategory;
  readonly label: string;
  readonly timestamp?: string;
  readonly onSelect?: () => void;
}

export interface SignalRailProps {
  readonly caption: string;
  readonly items: readonly SignalRailItem[];
}

export function SignalRail({ caption, items }: SignalRailProps) {
  return (
    <div class="cs-signal-rail">
      <span class="cs-signal-rail-caption">{caption}</span>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          class="cs-signal-item"
          onClick={item.onSelect}
          disabled={!item.onSelect}
        >
          <span
            class="cs-status-dot"
            style={{ background: SERIES_COLOR[item.category] }}
            aria-hidden="true"
          />
          <span>{item.label}</span>
          {item.timestamp ? <span class="cs-seg-count">{item.timestamp}</span> : null}
        </button>
      ))}
    </div>
  );
}

export interface LiveDecisionTickerProps {
  readonly timestamp: string;
  readonly category: TelemetryCategory;
  readonly categoryLabel: string;
  readonly message: string;
  readonly actionLabel?: string;
  readonly onOpenHistory?: () => void;
}

export function LiveDecisionTicker({
  timestamp,
  category,
  categoryLabel,
  message,
  actionLabel,
  onOpenHistory,
}: LiveDecisionTickerProps) {
  const tone: BadgeTone = category === "auto" ? "live" : category;
  return (
    <div class="cs-ticker" role="status" aria-live="polite">
      <span class="cs-ticker-time">{timestamp}</span>
      <StatusBadge tone={tone} label={categoryLabel} />
      <Tooltip content={message}>
        <span class="cs-ticker-msg">{message}</span>
      </Tooltip>
      {actionLabel && onOpenHistory ? (
        <button type="button" class="cs-filter-reset" onClick={onOpenHistory}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}
