import type { ComponentChildren } from "preact";

export type FacetMap = Readonly<Record<string, number>>;

export function FacetChips({
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
    <div class="rule-facet-set">
      <span>{label}</span>
      <div>
        <button
          type="button"
          class={value === "" ? "is-active" : undefined}
          onClick={() => onChange("")}
        >
          All <small>{options.reduce((sum, [, count]) => sum + count, 0)}</small>
        </button>
        {options.map(([key, count]) => (
          <button
            key={key}
            type="button"
            class={value === key ? "is-active" : undefined}
            onClick={() => onChange(key)}
          >
            {key} <small>{count}</small>
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
