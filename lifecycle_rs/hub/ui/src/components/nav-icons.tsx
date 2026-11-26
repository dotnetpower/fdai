/**
 * SVG glyphs for the sidebar's two nav items. Same line-icon convention as
 * console/src/components/rail-icons.tsx (``currentColor`` stroke, no fill), sized
 * down slightly to sit next to the nav's compact text instead of standing alone.
 *
 *  - Installations: stacked layers (a fleet of installed instances)
 *  - Enrollment requests: an inbox tray (incoming requests waiting on review)
 */

import type { JSX } from "preact";

const iconProps = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": 1.8,
  "stroke-linecap": "round" as const,
  "stroke-linejoin": "round" as const,
};

export function InstallationsIcon(): JSX.Element {
  return (
    <svg {...iconProps} aria-hidden="true">
      <path d="M12 3 L21 8 L12 13 L3 8 Z" />
      <path d="M3 13 L12 18 L21 13" />
      <path d="M3 17.5 L12 22 L21 17.5" />
    </svg>
  );
}

export function EnrollmentsIcon(): JSX.Element {
  return (
    <svg {...iconProps} aria-hidden="true">
      <path d="M5.5 5 H18.5 L21 13 V19 A2 2 0 0 1 19 21 H5 A2 2 0 0 1 3 19 V13 Z" />
      <path d="M3 13 H8 L10 16 H14 L16 13 H21" />
    </svg>
  );
}
