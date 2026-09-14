import type { ComponentChildren } from "preact";

export function TraceMetric({
  href,
  label,
  value,
  hint,
}: {
  readonly href: string;
  readonly label: string;
  readonly value: ComponentChildren;
  readonly hint: ComponentChildren;
}) {
  return (
    <a class="trace-metric" href={href}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </a>
  );
}

export function TraceFact({
  label,
  value,
}: {
  readonly label: string;
  readonly value: ComponentChildren;
}) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}
