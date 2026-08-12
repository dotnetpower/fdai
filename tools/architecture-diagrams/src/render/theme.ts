type ThemeVariables = Readonly<Record<`--fdai-diagram-${string}`, string>>;

export const CALM_SLATE_LIGHT: ThemeVariables = {
  "--fdai-diagram-canvas": "#f6f7f6",
  "--fdai-diagram-surface": "#ffffff",
  "--fdai-diagram-node": "#ffffff",
  "--fdai-diagram-label-surface": "#ffffff",
  "--fdai-diagram-text": "#20262d",
  "--fdai-diagram-muted": "#5f6872",
  "--fdai-diagram-border": "#d7dbde",
  "--fdai-diagram-border-strong": "#9ba3aa",
  "--fdai-diagram-shadow": "#17212b",
  "--fdai-diagram-neutral-header": "#ecefee",
  "--fdai-diagram-control-surface": "#edf2f5",
  "--fdai-diagram-control-header": "#dfe8ed",
  "--fdai-diagram-delivery-surface": "#edf3f1",
  "--fdai-diagram-delivery-header": "#dce8e4",
  "--fdai-diagram-azure": "#315f82",
  "--fdai-diagram-azure-dark": "#243f56",
  "--fdai-diagram-cyan-dark": "#3f7773",
  "--fdai-diagram-tone-input-fill": "#edf2f5",
  "--fdai-diagram-tone-input-stroke": "#315f82",
  "--fdai-diagram-tone-interpretation-fill": "#edf3f3",
  "--fdai-diagram-tone-interpretation-stroke": "#4b7180",
  "--fdai-diagram-tone-model-fill": "#ebf2ef",
  "--fdai-diagram-tone-model-stroke": "#3f7773",
  "--fdai-diagram-tone-policy-fill": "#eff2ea",
  "--fdai-diagram-tone-policy-stroke": "#617950",
  "--fdai-diagram-tone-decision-fill": "#f5eee8",
  "--fdai-diagram-tone-decision-stroke": "#986346",
  "--fdai-diagram-tone-execution-fill": "#f0edf4",
  "--fdai-diagram-tone-execution-stroke": "#705f8a",
  "--fdai-diagram-tone-feedback-fill": "#f2edf3",
  "--fdai-diagram-tone-feedback-stroke": "#80688d",
  "--fdai-diagram-tone-store-fill": "#eff1f2",
  "--fdai-diagram-tone-store-stroke": "#596871",
  "--fdai-diagram-tone-neutral-fill": "#ffffff",
  "--fdai-diagram-tone-neutral-stroke": "#737d84",
  "--fdai-diagram-edge-request": "#315f82",
  "--fdai-diagram-edge-event": "#3f7773",
  "--fdai-diagram-edge-approval": "#705f8a",
  "--fdai-diagram-edge-mutation": "#a86a45",
  "--fdai-diagram-edge-audit": "#617950",
  "--fdai-diagram-edge-rollback": "#9d555b",
  "--fdai-diagram-edge-read": "#3f7773",
  "--fdai-diagram-edge-write": "#705f8a",
  "--fdai-diagram-edge-feedback": "#80688d",
  "--fdai-diagram-edge-sequence": "#315f82",
  "--fdai-diagram-edge-transition": "#705f8a",
  "--fdai-diagram-edge-association": "#626c73",
  "--fdai-diagram-edge-dependency": "#778087",
  "--fdai-diagram-edge-timeline": "#986346",
  "--fdai-diagram-group-lane-fill": "#f8f9f8",
  "--fdai-diagram-group-lane-stroke": "#cfd4d6",
  "--fdai-diagram-group-sidebar-fill": "#f0edf3",
  "--fdai-diagram-group-sidebar-stroke": "#8a7895",
  "--fdai-diagram-group-feedback-fill": "#f4f0f4",
  "--fdai-diagram-group-feedback-stroke": "#8a7895",
  "--fdai-diagram-group-datastore-fill": "#f0f2f2",
  "--fdai-diagram-group-datastore-stroke": "#8d979c",
  "--fdai-diagram-badge-fill": "#243f56",
  "--fdai-diagram-badge-ring": "#ffffff",
  "--fdai-diagram-badge-text": "#ffffff",
  "--fdai-diagram-gantt-planned": "#e7e5e2",
  "--fdai-diagram-gantt-planned-stroke": "#aaa6a1",
  "--fdai-diagram-gantt-planned-text": "#2c333a",
  "--fdai-diagram-gantt-active": "#6685a4",
  "--fdai-diagram-gantt-active-stroke": "#44688e",
  "--fdai-diagram-gantt-done": "#718c6d",
  "--fdai-diagram-gantt-done-stroke": "#5e8259",
  "--fdai-diagram-gantt-critical": "#b97b59",
  "--fdai-diagram-gantt-critical-stroke": "#9e5f3c",
  "--fdai-diagram-gantt-milestone": "#887aa5",
  "--fdai-diagram-gantt-milestone-stroke": "#6f608c",
  "--fdai-diagram-gantt-progress": "#ffffff",
  "--fdai-diagram-gantt-text": "#ffffff",
  "--fdai-diagram-chart-surface": "#ffffff",
  "--fdai-diagram-chart-1": "#426b8c",
  "--fdai-diagram-chart-2": "#477d75",
  "--fdai-diagram-chart-3": "#75628d",
  "--fdai-diagram-chart-4": "#a26e50",
  "--fdai-diagram-chart-5": "#987a4d",
  "--fdai-diagram-chart-6": "#9a5e65",
  "--fdai-diagram-chart-7": "#5e7f91",
  "--fdai-diagram-chart-8": "#5c536f",
  "--fdai-diagram-pie-text": "#ffffff",
};

export const CALM_SLATE_DARK: ThemeVariables = {
  ...CALM_SLATE_LIGHT,
  "--fdai-diagram-canvas": "#181b1d",
  "--fdai-diagram-surface": "#22272a",
  "--fdai-diagram-node": "#252b2e",
  "--fdai-diagram-label-surface": "#22272a",
  "--fdai-diagram-text": "#f1f3f2",
  "--fdai-diagram-muted": "#b8c0c4",
  "--fdai-diagram-border": "#3d454a",
  "--fdai-diagram-border-strong": "#737e84",
  "--fdai-diagram-shadow": "#000000",
  "--fdai-diagram-neutral-header": "#2b3035",
  "--fdai-diagram-control-surface": "#202b35",
  "--fdai-diagram-control-header": "#273744",
  "--fdai-diagram-delivery-surface": "#202f2d",
  "--fdai-diagram-delivery-header": "#283d39",
  "--fdai-diagram-azure": "#7196b2",
  "--fdai-diagram-azure-dark": "#b1c7d8",
  "--fdai-diagram-cyan-dark": "#70a19a",
  "--fdai-diagram-tone-input-fill": "#202d37",
  "--fdai-diagram-tone-input-stroke": "#7196b2",
  "--fdai-diagram-tone-interpretation-fill": "#213033",
  "--fdai-diagram-tone-interpretation-stroke": "#78a0ad",
  "--fdai-diagram-tone-model-fill": "#20312d",
  "--fdai-diagram-tone-model-stroke": "#70a19a",
  "--fdai-diagram-tone-policy-fill": "#293226",
  "--fdai-diagram-tone-policy-stroke": "#93a77a",
  "--fdai-diagram-tone-decision-fill": "#382d27",
  "--fdai-diagram-tone-decision-stroke": "#d09a77",
  "--fdai-diagram-tone-execution-fill": "#302b37",
  "--fdai-diagram-tone-execution-stroke": "#a99ac0",
  "--fdai-diagram-tone-feedback-fill": "#332b36",
  "--fdai-diagram-tone-feedback-stroke": "#b299b6",
  "--fdai-diagram-tone-store-fill": "#292f32",
  "--fdai-diagram-tone-store-stroke": "#9ba7ad",
  "--fdai-diagram-tone-neutral-fill": "#24292e",
  "--fdai-diagram-tone-neutral-stroke": "#8e979f",
  "--fdai-diagram-edge-request": "#7196b2",
  "--fdai-diagram-edge-event": "#70a19a",
  "--fdai-diagram-edge-approval": "#a99ac0",
  "--fdai-diagram-edge-mutation": "#d09a77",
  "--fdai-diagram-edge-audit": "#93a77a",
  "--fdai-diagram-edge-rollback": "#cd8585",
  "--fdai-diagram-edge-read": "#70a19a",
  "--fdai-diagram-edge-write": "#a99ac0",
  "--fdai-diagram-edge-feedback": "#b299b6",
  "--fdai-diagram-edge-sequence": "#7196b2",
  "--fdai-diagram-edge-transition": "#a99ac0",
  "--fdai-diagram-edge-association": "#a9afb4",
  "--fdai-diagram-edge-dependency": "#8e979f",
  "--fdai-diagram-edge-timeline": "#d09a77",
  "--fdai-diagram-group-lane-fill": "#1d2125",
  "--fdai-diagram-group-lane-stroke": "#41484f",
  "--fdai-diagram-group-sidebar-fill": "#292631",
  "--fdai-diagram-group-sidebar-stroke": "#8f82a5",
  "--fdai-diagram-group-feedback-fill": "#29262f",
  "--fdai-diagram-group-feedback-stroke": "#8f82a5",
  "--fdai-diagram-group-datastore-fill": "#25292d",
  "--fdai-diagram-group-datastore-stroke": "#68717a",
  "--fdai-diagram-badge-fill": "#9db3c8",
  "--fdai-diagram-badge-ring": "#171a1d",
  "--fdai-diagram-badge-text": "#171a1d",
  "--fdai-diagram-gantt-planned": "#353a3f",
  "--fdai-diagram-gantt-planned-stroke": "#737b83",
  "--fdai-diagram-gantt-planned-text": "#edf0f2",
  "--fdai-diagram-gantt-active": "#567897",
  "--fdai-diagram-gantt-active-stroke": "#86a4c2",
  "--fdai-diagram-gantt-done": "#617b5f",
  "--fdai-diagram-gantt-done-stroke": "#91ad89",
  "--fdai-diagram-gantt-critical": "#9a6248",
  "--fdai-diagram-gantt-critical-stroke": "#d09a77",
  "--fdai-diagram-gantt-milestone": "#6f6088",
  "--fdai-diagram-gantt-milestone-stroke": "#aa99c4",
  "--fdai-diagram-chart-surface": "#202429",
  "--fdai-diagram-chart-1": "#7196b2",
  "--fdai-diagram-chart-2": "#70a19a",
  "--fdai-diagram-chart-3": "#a99ac0",
  "--fdai-diagram-chart-4": "#c58b69",
  "--fdai-diagram-chart-5": "#b5966f",
  "--fdai-diagram-chart-6": "#b97d7d",
  "--fdai-diagram-chart-7": "#87a6b8",
  "--fdai-diagram-chart-8": "#8b7ea8",
};

function declarations(variables: ThemeVariables): string {
  return Object.entries(variables)
    .map(([name, value]) => `${name}:${value}`)
    .join(";");
}

export function standaloneThemeCss(preserveLightTheme = false): string {
  const darkThemeSelector = preserveLightTheme
    ? 'svg[data-diagram-id]:not([data-embedded]):not([data-profile="azure-reference"])'
    : "svg[data-diagram-id]:not([data-embedded])";
  return `
    svg[data-diagram-id]:not([data-embedded]) { ${declarations(CALM_SLATE_LIGHT)}; }
    @media (prefers-color-scheme: dark) {
      ${darkThemeSelector} { ${declarations(CALM_SLATE_DARK)}; }
    }
  `;
}

export function embeddedThemeCss(): string {
  return `
    :host { ${declarations(CALM_SLATE_LIGHT)}; }
    :host-context([data-theme="dark"]) { ${declarations(CALM_SLATE_DARK)}; }
  `;
}

export function calmSlateFoundationCss(): string {
  return `
    svg[data-diagram-id] {
      font-family: "Segoe UI Variable Text", "Segoe UI", "Noto Sans KR", sans-serif;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-title {
      font-size: 28px; font-weight: 720;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-subtitle {
      font-size: 14px; font-weight: 480;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-group .group-surface {
      stroke-width: 1; stroke-dasharray: none;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .group-accent {
      stroke: var(--fdai-diagram-border-strong); stroke-width: 2; stroke-linecap: round;
      opacity: 0.56;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-group[data-depth="1"] > .group-surface {
      filter: url(#group-shadow);
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-group:not([data-depth="1"]) > .group-surface {
      stroke-opacity: 0.78;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-group:not([data-depth="1"]) > .group-header {
      opacity: 0.72;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-node > rect,
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-node > .node-surface {
      stroke-width: 1;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-node:hover > rect,
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-node:focus > rect,
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-node.is-active > rect,
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-node.is-keyboard-focused > rect,
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-node:hover > .node-surface,
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-node:focus > .node-surface,
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-node.is-active > .node-surface,
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-node.is-keyboard-focused > .node-surface {
      stroke-width: 2;
    }
    svg[data-profile="azure-reference"] .diagram-node.is-keyboard-focused > rect,
    svg[data-profile="azure-reference"] .diagram-node.is-keyboard-focused > .node-surface {
      stroke: var(--fdai-diagram-azure); stroke-width: 1.5;
    }
    svg[data-profile="azure-reference"] .diagram-node[data-presentation="icon"].is-keyboard-focused > rect {
      fill: #ffffff;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .node-label,
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .group-label {
      font-weight: 680;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .node-body {
      font-weight: 470;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .group-label {
      font-weight: 650;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .edge-path {
      opacity: 0.82;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .edge-label rect {
      filter: url(#label-shadow); stroke-width: 1;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-legend {
      opacity: 0.9;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .legend-swatch {
      stroke-width: 1.25;
    }
    svg[data-kind="gantt"] .diagram-node[data-shape="bar"] .node-label {
      fill: var(--fdai-diagram-text); font-size: 14px; font-weight: 600;
    }
    svg[data-kind="gantt"] .diagram-node[data-shape="bar"] > .node-surface {
      stroke-width: 1; filter: url(#label-shadow);
    }
    svg[data-kind="gantt"] .node-progress {
      fill-opacity: 0.24;
    }
    svg[data-kind="gantt"] .diagram-node[data-status="milestone"] > .node-surface {
      filter: none;
    }
    svg[data-kind="gantt"] .chart-tick-label {
      fill: var(--fdai-diagram-muted); font-size: 12px; font-weight: 550;
    }
    svg[data-kind="gantt"] .gantt-grid .chart-guide {
      stroke-dasharray: 2 7; opacity: 0.48;
    }
    svg[data-profile="conceptual"] .diagram-group[data-presentation="panel"] > .group-surface {
      fill: var(--fdai-diagram-canvas); stroke: var(--fdai-diagram-border);
    }
    svg[data-profile="conceptual"] .diagram-group[data-presentation="panel"] > .group-header {
      fill: transparent;
    }
    svg[data-profile="conceptual"] .diagram-node > .node-surface {
      filter: url(#node-shadow);
    }
    svg[data-kind="pie"] .diagram-node[data-shape="pie-slice"] .node-label {
      fill: var(--fdai-diagram-text); font-size: 14px; font-weight: 620;
    }
    svg[data-kind="pie"] .diagram-node[data-shape="pie-slice"] > .node-surface {
      stroke: var(--fdai-diagram-canvas); stroke-width: 3;
    }
    svg[data-kind="pie"] .chart-leader {
      fill: none; stroke: var(--fdai-diagram-border-strong); stroke-width: 1;
    }
    svg[data-kind="pie"] .donut-total {
      fill: var(--fdai-diagram-text); font-size: 25px; font-weight: 680;
    }
    svg[data-kind="pie"] .donut-caption {
      fill: var(--fdai-diagram-muted); font-size: 11px; font-weight: 650;
    }
    svg[data-kind="pie"] .donut-center-ring {
      fill: var(--fdai-diagram-surface); fill-opacity: 0.32;
      stroke: var(--fdai-diagram-border); stroke-width: 1;
    }
    svg[data-kind="radar"] .radar-spoke {
      stroke: var(--fdai-diagram-border); stroke-width: 1; opacity: 0.66;
    }
    svg[data-kind="radar"] .radar-area {
      fill: var(--fdai-diagram-chart-1); fill-opacity: 0.18;
      stroke: var(--fdai-diagram-chart-1); stroke-width: 2.5;
    }
    svg[data-kind="radar"] .diagram-edge { opacity: 0; pointer-events: none; }
    svg[data-kind="radar"] .diagram-node > .node-surface {
      fill: var(--fdai-diagram-surface); stroke-width: 1.5; filter: url(#label-shadow);
    }
    svg[data-kind="quadrant"] .quadrant-region { stroke: none; }
    svg[data-kind="quadrant"] .region-one { fill: var(--fdai-diagram-tone-policy-fill); }
    svg[data-kind="quadrant"] .region-two { fill: var(--fdai-diagram-tone-model-fill); }
    svg[data-kind="quadrant"] .region-three { fill: var(--fdai-diagram-tone-neutral-fill); }
    svg[data-kind="quadrant"] .region-four { fill: var(--fdai-diagram-tone-decision-fill); }
    svg[data-kind="quadrant"] .quadrant-region { fill-opacity: 0.44; }
    svg[data-kind="quadrant"] .diagram-node > .node-surface {
      filter: url(#label-shadow); stroke-width: 1.5;
    }
    svg[data-kind="kanban"] .diagram-group > .group-surface {
      fill: var(--fdai-diagram-surface); fill-opacity: 0.72;
      stroke: var(--fdai-diagram-border); filter: url(#group-shadow);
    }
    svg[data-kind="kanban"] .diagram-group > .group-header {
      fill: var(--fdai-diagram-neutral-header); opacity: 0.76;
    }
    svg[data-kind="kanban"] .group-accent { display: none; }
    svg[data-kind="kanban"] .kanban-header-divider {
      stroke: var(--fdai-diagram-border); stroke-width: 1;
    }
    svg[data-kind="kanban"] .kanban-count circle {
      fill: var(--fdai-diagram-surface); stroke: var(--fdai-diagram-border-strong);
      stroke-width: 1;
    }
    svg[data-kind="kanban"] .kanban-count text {
      fill: var(--fdai-diagram-muted); font-size: 11px; font-weight: 700;
      text-anchor: middle;
    }
    svg[data-kind="kanban"] .diagram-node > .node-surface {
      fill: var(--fdai-diagram-surface); stroke: var(--fdai-diagram-border-strong);
      filter: url(#label-shadow);
    }
    svg[data-kind="kanban"] .diagram-node .node-label {
      font-weight: 650;
    }
    svg[data-kind="sankey"] .diagram-edge > .edge-path {
      opacity: 0.52; stroke-linecap: butt;
    }
    svg[data-kind="sankey"] .diagram-edge:hover > .edge-path,
    svg[data-kind="sankey"] .diagram-edge.is-active > .edge-path {
      opacity: 0.88; stroke-width: revert;
    }
    svg[data-kind="sankey"] .diagram-node > .node-surface {
      fill: var(--fdai-diagram-surface); filter: none; stroke-width: 1.5;
    }
    @media (prefers-reduced-motion: reduce) {
      svg[data-diagram-id] .edge-path { transition: none; }
    }
  `;
}
