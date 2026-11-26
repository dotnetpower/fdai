# Agent Pantheon icon set

Line icons for the 15 named FDAI agents (see
[agent-pantheon.md](../../../docs/roadmap/agents/agent-pantheon.md)). One glyph per agent,
pairing the agent's Norse symbol with its pipeline role.

## Files

- `<name>.svg` - one icon per agent (`odin.svg`, `thor.svg`, ...), lower-cased agent name.
- `pantheon.svg` - one collective mark for diagrams and surfaces that represent all 15 agents.
- `manifest.json` - machine-readable index: name, role, org-chart group, suggested accent
  color, mythic glyph note, file name, and the separate collective mark. Render the set
  programmatically from this.
- Preview: [`mocks/ui/agent-icons.html`](../../../mocks/ui/agent-icons.html) is a
  self-contained gallery with size and background toggles.

## Design contract

- `viewBox="0 0 24 24"`, stroke-based: `fill="none"`, `stroke="currentColor"`,
  `stroke-width="1.6"`, round caps and joins.
- No color is baked into the SVG. The icon inherits the current text color, so a consumer
  sets the color once in CSS. `manifest.json` carries a suggested per-group accent, but it
  is advisory - the glyph is monochrome.
- Muninn is the only icon with a filled element (a solid dot marking "stored memory",
  distinguishing it from Huginn's open "thought" ring).

## Usage

As an image, tinted by CSS `color`:

```html
<img src="/agent-icons/thor.svg" alt="Thor" width="24" height="24" />
```

Inline (recolorable via `currentColor`) - fetch and inject, or paste the SVG markup and
set `color` on a wrapper:

```html
<span style="color: #f5a623">
  <!-- contents of thor.svg -->
</span>
```

Data-driven from the manifest:

```ts
import manifest from "/agent-icons/manifest.json";
for (const a of manifest.agents) {
  // `/agent-icons/${a.file}`, tint with a.accent or a.group's accent
}
```

## Groups and accents

| Group | Accent | Agents |
|-------|--------|--------|
| command | `#e5c76b` | Odin |
| operations | `#f5a623` | Thor, Var, Vidar, Bragi |
| judgment | `#4ea8ff` | Forseti |
| sensing | `#2dd4bf` | Huginn, Heimdall |
| governance | `#a78bfa` | Saga, Mimir, Norns, Muninn |
| domain | per agent | Njord `#4ade80`, Freyr `#818cf8`, Loki `#fb7185` |

## Notes

- The 15-agent pantheon is fixed upstream. If an agent is ever renamed in the ontology,
  rename its icon file and `manifest.json` entry in the same change so the set stays in sync.
- The collective mark is not a sixteenth agent. Its six outer nodes represent the role groups,
  and its center represents their coordinated runtime.
- Draft v1. Regenerate or refine a single glyph without touching the others; each file is
  independent.
