import type { ComponentChildren } from "preact";

export function TraceMetric({
  href,
  label,
  primary = false,
  value,
  hint,
}: {
  readonly href: string;
  readonly label: string;
  readonly primary?: boolean;
  readonly value: ComponentChildren;
  readonly hint: ComponentChildren;
}) {
  return (
    <a class={`trace-metric${primary ? " is-primary" : ""}`} href={href}>
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
