# WebGL Sand UI - mock

A full-WebGL concept for the FDAI surface: on a **light, flat canvas**, the title, KPI
cards, and a status panel **fade in cleanly**. Text is rendered with **SDF glyphs**
(`troika-three-text`) so it stays **crisp at any scale** (no texture blur / stair-stepping); card
backgrounds and shadows use a canvas texture. Pure Three.js (loaded from a CDN), no DOM UI.

> Text uses troika's default SDF font (Roboto). Swap in a specific font file via `Text.font` if a
> particular typeface is required; content here is English-only.

This is an exploratory **mock**, not the production console. The production operator console is a
thin, read-only DOM SPA (see
[../../.github/instructions/app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md));
this WebGL treatment would only ever be an **ambient/visual layer** over that DOM UI, added as a
progressive enhancement - never the sole interface (accessibility, forms, and tables stay DOM).

## Pages

| File | Purpose |
|------|---------|
| [index.html](index.html) | intro: title + KPI cards fade in (clean, particle-free) |
| [dashboard.html](dashboard.html) | full-WebGL operator console: KPIs, trust-tier split, human approval queue, shadow results, audit log (wheel to scroll) |

Both are static demos (plain HTML + Three.js from a CDN), no DOM UI beyond a small nav.

## Scope note

Only the **dashboard** is ported to full WebGL, because it is card/metric-oriented where a WebGL
treatment reads well. Text-heavy, scroll-heavy surfaces (long tables, forms) stay better as DOM
(see the DOM kit in [../../ui/](../../ui/README.md)) - porting those to WebGL would mean
re-implementing scrolling, text selection, and accessibility for little gain. In production the
console is a thin, read-only DOM SPA; this WebGL treatment is an exploratory ambient/visual layer
(see [../../.github/instructions/app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md)).

## Run

Serve the folder over HTTP (the CDN import map needs `http(s)`, not `file://`):

```
cd mocks/ui-webgl
python3 -m http.server 8080
# open http://localhost:8080/
```

## What it shows

- **Clean fade-in**: each card fades in (opacity only, no motion), lightly staggered
  (`main.js` → `order` / `FADE`).
- **Crisp text**: labels render as **SDF glyphs** via `troika-three-text` - vector-sharp at any
  zoom, unlike baked canvas-texture text. Card shapes/shadows use a crisp-filtered canvas texture.
- **Hover focus**: moving the pointer over a card lifts and slightly enlarges it.
- **Click to replay**: resets the fade-in timeline.
- **Reduced motion**: honors `prefers-reduced-motion` by showing the settled state immediately.

## Files

- [index.html](index.html) - canvas + import map + light gradient background.
- [main.js](main.js) - Three.js scene, particle buffers, custom point shader, text planes.

## Notes

- Palette is Calm Slate (mid-dark accents on a light background), consistent with the DOM UI kit
  in [../../ui/](../../ui/README.md).
- English-only and customer-agnostic; all values shown are synthetic placeholders.
- Requires network access for the Three.js and troika-three-text CDN modules.
