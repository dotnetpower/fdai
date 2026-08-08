type ThemeVariables = Readonly<Record<`--fdai-diagram-${string}`, string>>;

export const CALM_SLATE_LIGHT: ThemeVariables = {
  "--fdai-diagram-canvas": "#fbfaf9",
  "--fdai-diagram-surface": "#ffffff",
  "--fdai-diagram-node": "#ffffff",
  "--fdai-diagram-label-surface": "#ffffff",
  "--fdai-diagram-text": "#2c333a",
  "--fdai-diagram-muted": "#6b7178",
  "--fdai-diagram-border": "#e3e1de",
  "--fdai-diagram-border-strong": "#b8b5b0",
  "--fdai-diagram-neutral-header": "#f4f2f0",
  "--fdai-diagram-control-surface": "#f3f6f8",
  "--fdai-diagram-control-header": "#e9eef2",
  "--fdai-diagram-delivery-surface": "#f1f6f5",
  "--fdai-diagram-delivery-header": "#e6efed",
  "--fdai-diagram-azure": "#44688e",
  "--fdai-diagram-azure-dark": "#3e4c59",
  "--fdai-diagram-cyan-dark": "#4f847e",
  "--fdai-diagram-tone-input-fill": "#f2f5f8",
  "--fdai-diagram-tone-input-stroke": "#44688e",
  "--fdai-diagram-tone-interpretation-fill": "#f0f4f5",
  "--fdai-diagram-tone-interpretation-stroke": "#5f7d91",
  "--fdai-diagram-tone-model-fill": "#eef4f2",
  "--fdai-diagram-tone-model-stroke": "#4f847e",
  "--fdai-diagram-tone-policy-fill": "#eff4ed",
  "--fdai-diagram-tone-policy-stroke": "#5e8259",
  "--fdai-diagram-tone-decision-fill": "#f8f2ed",
  "--fdai-diagram-tone-decision-stroke": "#a56d4b",
  "--fdai-diagram-tone-execution-fill": "#f3f0f6",
  "--fdai-diagram-tone-execution-stroke": "#7b6c9c",
  "--fdai-diagram-tone-feedback-fill": "#f4f1f6",
  "--fdai-diagram-tone-feedback-stroke": "#87769d",
  "--fdai-diagram-tone-store-fill": "#f3f4f4",
  "--fdai-diagram-tone-store-stroke": "#68747e",
  "--fdai-diagram-tone-neutral-fill": "#ffffff",
  "--fdai-diagram-tone-neutral-stroke": "#899097",
  "--fdai-diagram-edge-request": "#44688e",
  "--fdai-diagram-edge-event": "#4f847e",
  "--fdai-diagram-edge-approval": "#7b6c9c",
  "--fdai-diagram-edge-mutation": "#bc7449",
  "--fdai-diagram-edge-audit": "#5e8259",
  "--fdai-diagram-edge-rollback": "#ac5a5a",
  "--fdai-diagram-edge-read": "#4f847e",
  "--fdai-diagram-edge-write": "#7b6c9c",
  "--fdai-diagram-edge-feedback": "#87769d",
  "--fdai-diagram-edge-sequence": "#44688e",
  "--fdai-diagram-edge-transition": "#7b6c9c",
  "--fdai-diagram-edge-association": "#737a80",
  "--fdai-diagram-edge-dependency": "#8a8f94",
  "--fdai-diagram-edge-timeline": "#a56d4b",
  "--fdai-diagram-group-lane-fill": "#faf9f8",
  "--fdai-diagram-group-lane-stroke": "#d7d4d0",
  "--fdai-diagram-group-sidebar-fill": "#f5f2f6",
  "--fdai-diagram-group-sidebar-stroke": "#9a8ead",
  "--fdai-diagram-group-feedback-fill": "#f7f4f7",
  "--fdai-diagram-group-feedback-stroke": "#9a8ead",
  "--fdai-diagram-group-datastore-fill": "#f5f5f4",
  "--fdai-diagram-group-datastore-stroke": "#a3a7aa",
  "--fdai-diagram-badge-fill": "#3e4c59",
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
  "--fdai-diagram-chart-1": "#607f9f",
  "--fdai-diagram-chart-2": "#5f8b84",
  "--fdai-diagram-chart-3": "#897aa5",
  "--fdai-diagram-chart-4": "#bd805d",
  "--fdai-diagram-chart-5": "#a98962",
  "--fdai-diagram-chart-6": "#a86f6f",
  "--fdai-diagram-chart-7": "#7897aa",
  "--fdai-diagram-chart-8": "#766b91",
  "--fdai-diagram-pie-text": "#ffffff",
};

export const CALM_SLATE_DARK: ThemeVariables = {
  ...CALM_SLATE_LIGHT,
  "--fdai-diagram-canvas": "#171a1d",
  "--fdai-diagram-surface": "#202429",
  "--fdai-diagram-node": "#24292e",
  "--fdai-diagram-label-surface": "#202429",
  "--fdai-diagram-text": "#edf0f2",
  "--fdai-diagram-muted": "#b5bbc1",
  "--fdai-diagram-border": "#41484f",
  "--fdai-diagram-border-strong": "#68717a",
  "--fdai-diagram-neutral-header": "#2b3035",
  "--fdai-diagram-control-surface": "#202b35",
  "--fdai-diagram-control-header": "#273744",
  "--fdai-diagram-delivery-surface": "#202f2d",
  "--fdai-diagram-delivery-header": "#283d39",
  "--fdai-diagram-azure": "#86a4c2",
  "--fdai-diagram-azure-dark": "#abc0d5",
  "--fdai-diagram-cyan-dark": "#80aaa4",
  "--fdai-diagram-tone-input-fill": "#252f39",
  "--fdai-diagram-tone-input-stroke": "#86a4c2",
  "--fdai-diagram-tone-interpretation-fill": "#243137",
  "--fdai-diagram-tone-interpretation-stroke": "#82a7b4",
  "--fdai-diagram-tone-model-fill": "#22332f",
  "--fdai-diagram-tone-model-stroke": "#7ead9f",
  "--fdai-diagram-tone-policy-fill": "#283428",
  "--fdai-diagram-tone-policy-stroke": "#91ad89",
  "--fdai-diagram-tone-decision-fill": "#382d27",
  "--fdai-diagram-tone-decision-stroke": "#d09a77",
  "--fdai-diagram-tone-execution-fill": "#302b38",
  "--fdai-diagram-tone-execution-stroke": "#aa99c4",
  "--fdai-diagram-tone-feedback-fill": "#312d38",
  "--fdai-diagram-tone-feedback-stroke": "#b0a2c1",
  "--fdai-diagram-tone-store-fill": "#2a2f33",
  "--fdai-diagram-tone-store-stroke": "#99a3aa",
  "--fdai-diagram-tone-neutral-fill": "#24292e",
  "--fdai-diagram-tone-neutral-stroke": "#8e979f",
  "--fdai-diagram-edge-request": "#86a4c2",
  "--fdai-diagram-edge-event": "#80aaa4",
  "--fdai-diagram-edge-approval": "#aa99c4",
  "--fdai-diagram-edge-mutation": "#d09a77",
  "--fdai-diagram-edge-audit": "#91ad89",
  "--fdai-diagram-edge-rollback": "#cd8585",
  "--fdai-diagram-edge-read": "#80aaa4",
  "--fdai-diagram-edge-write": "#aa99c4",
  "--fdai-diagram-edge-feedback": "#b0a2c1",
  "--fdai-diagram-edge-sequence": "#86a4c2",
  "--fdai-diagram-edge-transition": "#aa99c4",
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
  "--fdai-diagram-chart-1": "#7898b8",
  "--fdai-diagram-chart-2": "#71a097",
  "--fdai-diagram-chart-3": "#9e8db8",
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

export function standaloneThemeCss(): string {
  return `
    svg[data-diagram-id]:not([data-embedded]) { ${declarations(CALM_SLATE_LIGHT)}; }
    @media (prefers-color-scheme: dark) {
      svg[data-diagram-id]:not([data-embedded]) { ${declarations(CALM_SLATE_DARK)}; }
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
      font-size: 24px; font-weight: 680;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-subtitle {
      font-size: 15px;
    }
    svg[data-diagram-id]:not([data-profile="azure-reference"]) .diagram-group .group-surface {
      stroke-width: 1; stroke-dasharray: none;
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
      font-weight: 620;
    }
    svg[data-kind="gantt"] .diagram-node[data-shape="bar"] .node-label {
      fill: var(--fdai-diagram-text); font-size: 14px; font-weight: 600;
    }
    svg[data-kind="gantt"] .diagram-node[data-status="milestone"] > .node-surface {
      filter: none;
    }
    svg[data-kind="gantt"] .chart-tick-label {
      fill: var(--fdai-diagram-muted); font-size: 12px; font-weight: 550;
    }
    svg[data-kind="gantt"] .gantt-grid .chart-guide {
      stroke-dasharray: 2 6; opacity: 0.72;
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
    svg[data-kind="radar"] .radar-spoke {
      stroke: var(--fdai-diagram-border); stroke-width: 1;
    }
    svg[data-kind="radar"] .radar-area {
      fill: var(--fdai-diagram-chart-1); fill-opacity: 0.14;
      stroke: var(--fdai-diagram-chart-1); stroke-width: 2;
    }
    svg[data-kind="radar"] .diagram-edge { opacity: 0; pointer-events: none; }
    svg[data-kind="radar"] .diagram-node > .node-surface {
      fill: var(--fdai-diagram-surface); stroke-width: 1.5; filter: none;
    }
    svg[data-kind="quadrant"] .quadrant-region { stroke: none; }
    svg[data-kind="quadrant"] .region-one { fill: var(--fdai-diagram-tone-policy-fill); }
    svg[data-kind="quadrant"] .region-two { fill: var(--fdai-diagram-tone-model-fill); }
    svg[data-kind="quadrant"] .region-three { fill: var(--fdai-diagram-tone-neutral-fill); }
    svg[data-kind="quadrant"] .region-four { fill: var(--fdai-diagram-tone-decision-fill); }
    svg[data-kind="quadrant"] .quadrant-region { fill-opacity: 0.62; }
    svg[data-kind="quadrant"] .diagram-node > .node-surface {
      filter: none; stroke-width: 1.5;
    }
    svg[data-kind="kanban"] .diagram-group > .group-surface {
      fill: var(--fdai-diagram-neutral-header); fill-opacity: 0.62;
      stroke: none;
    }
    svg[data-kind="kanban"] .diagram-group > .group-header {
      fill: transparent;
    }
    svg[data-kind="kanban"] .diagram-node > .node-surface {
      fill: var(--fdai-diagram-surface); stroke: var(--fdai-diagram-border);
      filter: url(#node-shadow);
    }
    svg[data-kind="sankey"] .diagram-edge > .edge-path {
      opacity: 0.52; stroke-linecap: butt;
    }
    svg[data-kind="sankey"] .diagram-edge:hover > .edge-path,
    svg[data-kind="sankey"] .diagram-edge.is-active > .edge-path {
      opacity: 0.88;
    }
    svg[data-kind="sankey"] .diagram-node > .node-surface {
      fill: var(--fdai-diagram-surface); filter: none; stroke-width: 1.5;
    }
    @media (prefers-reduced-motion: reduce) {
      svg[data-diagram-id] .edge-path { transition: none; }
    }
  `;
}
