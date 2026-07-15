/**
 * SVG glyphs for Activity Bar groups and standalone icons.
 *
 * Single responsibility: given a group id, return a JSX SVG. No layout,
 * no interaction, no state. Icons intentionally use ``currentColor`` so
 * the rail styling controls their tint.
 *
 * Icon choices reflect operator intent:
 *  - Overview   : bar chart (summary)
 *  - Operations : lightning bolt (live work)
 *  - Agents     : collaborating principals
 *  - Governance : shield check (control)
 *  - Evidence   : clock rewind (audit and reconstruction)
 *  - Labs       : flask (development-only experiments)
 */

import type { JSX } from "preact";
import type { PanelGroup } from "../panels";

const iconProps = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": 1.8,
  "stroke-linecap": "round" as const,
  "stroke-linejoin": "round" as const,
};

function IconOperations(): JSX.Element {
  return (
    <svg {...iconProps}>
      <path d="M13 2 L3 14 L11 14 L11 22 L21 10 L13 10 Z" />
    </svg>
  );
}

function IconEvidence(): JSX.Element {
  return (
    <svg {...iconProps}>
      <path d="M12 4 A8 8 0 1 1 4.6 15.5" />
      <path d="M4 4 L4 9 L9 9" />
      <path d="M12 8 L12 12 L15 14" />
    </svg>
  );
}

function IconAgents(): JSX.Element {
  return (
    <svg {...iconProps}>
      <circle cx="9" cy="8" r="3" />
      <circle cx="17" cy="10" r="2" />
      <path d="M3 20 C3 16 6 13 9 13 C12 13 15 16 15 20" />
      <path d="M14 15 C17 15 19 17 19 20" />
    </svg>
  );
}

function IconGovernance(): JSX.Element {
  return (
    <svg {...iconProps}>
      <path d="M12 3 L4 6 V12 C4 17 8 20.5 12 21.5 C16 20.5 20 17 20 12 V6 Z" />
      <path d="M9 12 L11 14 L15 10" />
    </svg>
  );
}

function IconOverview(): JSX.Element {
  return (
    <svg {...iconProps}>
      <path d="M4 21 L4 3" />
      <path d="M4 21 L21 21" />
      <rect x="7" y="12" width="3" height="7" />
      <rect x="12" y="8" width="3" height="11" />
      <rect x="17" y="14" width="3" height="5" />
    </svg>
  );
}

function IconLabs(): JSX.Element {
  return (
    <svg {...iconProps}>
      <path d="M9 3 H15" />
      <path d="M10 3 V9 L5 18 A2 2 0 0 0 7 21 H17 A2 2 0 0 0 19 18 L14 9 V3" />
      <path d="M8 15 H16" />
    </svg>
  );
}

export function settingsIcon(): JSX.Element {
  return (
    <svg {...iconProps}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" />
    </svg>
  );
}

export function groupIcon(group: PanelGroup): JSX.Element {
  switch (group) {
    case "overview":
      return <IconOverview />;
    case "operations":
      return <IconOperations />;
    case "agents":
      return <IconAgents />;
    case "governance":
      return <IconGovernance />;
    case "evidence":
      return <IconEvidence />;
    case "labs":
      return <IconLabs />;
  }
}
