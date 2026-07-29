import type { ComponentChildren } from "preact";
import { displayValue, t } from "./i18n/governance";

export type FacetMap = Readonly<Record<string, number>>;

export function FacetSelect({
  label,
  value,
  counts,
  onChange,
}: {
  readonly label: string;
  readonly value: string;
  readonly counts: FacetMap;
  readonly onChange: (next: string) => void;
}) {
  const options = Object.entries(counts);
  return (
    <label class="rule-facet-select">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.currentTarget.value)}>
        <option value="">
          {t("governance.common.all")} ({options.reduce((sum, [, count]) => sum + count, 0)})
        </option>
        {options.map(([key, count]) => (
          <option key={key} value={key}>{key} ({count})</option>
        ))}
      </select>
    </label>
  );
}

export function FacetChips({
  label,
  value,
  counts,
  displayGroup,
  onChange,
}: {
  readonly label: string;
  readonly value: string;
  readonly counts: FacetMap;
  readonly displayGroup?: string;
  readonly onChange: (next: string) => void;
}) {
  const options = Object.entries(counts);
  return (
    <div class="rule-facet-set">
      <span>{label}</span>
      <div>
        <button
          type="button"
          class={value === "" ? "is-active" : undefined}
          onClick={() => onChange("")}
        >
          {t("governance.common.all")} <small>{options.reduce((sum, [, count]) => sum + count, 0)}</small>
        </button>
        {options.map(([key, count]) => (
          <button
            key={key}
            type="button"
            class={value === key ? "is-active" : undefined}
            onClick={() => onChange(key)}
          >
            {displayGroup ? displayValue(displayGroup, key) : key} <small>{count}</small>
          </button>
        ))}
      </div>
    </div>
  );
}

export function DetailSection({
  title,
  subtitle,
  action,
  children,
}: {
  readonly title: string;
  readonly subtitle?: string;
  readonly action?: ComponentChildren;
  readonly children: ComponentChildren;
}) {
  return (
    <section class="stack-section">
      <div class="section-header">
        <h4 class="section-title">{title}</h4>
        {action ?? null}
      </div>
      {subtitle ? <p class="muted footnote mono">{subtitle}</p> : null}
      {children}
    </section>
  );
}

export function DetailRow({
  label,
  value,
  mono,
}: {
  readonly label: string;
  readonly value: ComponentChildren;
  readonly mono?: boolean;
}) {
  return (
    <>
      <dt class="muted">{label}</dt>
      <dd class={mono ? "mono" : undefined}>{value}</dd>
    </>
  );
}
