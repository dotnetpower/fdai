import { useEffect, useState } from "preact/hooks";
import type { ComparisonMetric, DashboardComparison } from "../dashboard-comparison";
import { DataTable, UnavailableState, type Column } from "../components/ui";
import { getLocale } from "../i18n";
import { routeHref } from "../router";
import en from "./i18n/dashboard-comparison.en.json";
import ko from "./i18n/dashboard-comparison.ko.json";
import "./dashboard.comparison.css";

function text(key: keyof typeof en, params: Record<string, string | number> = {}): string {
  const value = (getLocale() === "ko" ? ko[key] : en[key]) || en[key];
  return value.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole);
}

/** Keep admitted paired measurements separate from rolling operational summaries. */
export function CohortComparison({ comparison }: {
  readonly comparison?: DashboardComparison | null | undefined;
}) {
  return comparison ? <PublishedComparison comparison={comparison} /> : null;
}

/** Republish both the visible comparison and screen evidence when its admission expires. */
export function useCohortExpiry(validUntil: string | undefined): boolean {
  const [now, setNow] = useState(Date.now);
  const expiry = validUntil === undefined ? undefined : Date.parse(validUntil);
  useEffect(() => {
    if (expiry === undefined) return;
    const remaining = expiry - Date.now();
    if (remaining <= 0) {
      if (now < expiry) setNow(Date.now());
      return;
    }
    const timeout = setTimeout(() => setNow(Date.now()), Math.min(remaining, 2_147_483_647));
    return () => clearTimeout(timeout);
  }, [expiry, now]);
  return expiry !== undefined && Math.max(now, Date.now()) >= expiry;
}

function PublishedComparison({ comparison }: { readonly comparison: DashboardComparison }) {
  const expired = useCohortExpiry(comparison.valid_until);
  if (expired) return <UnavailableState message={text("expired")} />;

  const number = (value: number) => new Intl.NumberFormat(getLocale(), {
    maximumSignificantDigits: 4,
  }).format(value);
  const format = (metric: ComparisonMetric, value: number) =>
    metric.metric_id === "auto_resolution_rate" ? `${number(value * 100)}%` : number(value);
  const display = (metric: ComparisonMetric) => (
    <div class="comparison-estimate">
      <strong>{format(metric, metric.absolute_value)}</strong>
      <small>{text("samples", { count: metric.sample_size })}</small>
      <small>{text("interval", {
        lower: format(metric, metric.lower_bound), upper: format(metric, metric.upper_bound),
      })}</small>
    </div>
  );
  const rows = comparison.baseline.metrics.map((baseline, index) => ({
    baseline, treatment: comparison.treatment.metrics[index]!,
  }));
  const columns: readonly Column<(typeof rows)[number]>[] = [
    {
      key: "metric", header: text("metric"),
      render: ({ baseline }) => {
        const key = baseline.metric_id;
        return Object.hasOwn(en, key) ? text(key as keyof typeof en) : key;
      },
    },
    { key: "baseline", header: text("baseline"), render: ({ baseline }) => display(baseline) },
    { key: "treatment", header: text("treatment"), render: ({ treatment }) => display(treatment) },
  ];
  return (
    <section class="stack-section dashboard-cohort-comparison">
      <h3 class="section-title">{text("title")}</h3>
      <p class="muted">{text("boundary")}</p>
      <DataTable columns={columns} rows={rows} keyOf={({ baseline }) => baseline.metric_id} />
      <p class="muted">
        {text("window")}: {comparison.baseline.window_start} / {comparison.baseline.window_end}
        {"; "}{comparison.treatment.window_start} / {comparison.treatment.window_end}
      </p>
      <p class="muted">
        {text("revision")}: <code>{comparison.fdai_revision}</code>
        {" / "}{text("protocol")}: {comparison.measurement_protocol_version}
      </p>
      <a href={routeHref("audit", { params: { action: "measurement.dashboard_comparison.v1" } })}>
        {text("evidence")}
      </a>
    </section>
  );
}
