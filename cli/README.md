# operator-console CLI (Ink)

The real FDAI **operator-console** as a terminal app, built on
[Ink](https://github.com/vadimdemedes/ink) (React for the terminal). It is the
runnable successor to the design mock at [../mocks/ui-cli](../mocks/ui-cli).

> Node/TypeScript island in a Python-first monorepo, like
> [../console](../console). No build step is required to run it (`tsx` executes
> the TypeScript directly). English-only, customer-agnostic; every value shown is
> synthetic.

## Quick start (one command)

To boot the dev read API and open the CLI wired to it in a single step, use the
Python launcher (it starts the API, waits for health, runs the CLI, then tears
the API down on exit):

```bash
uv run python -m tools.console          # from the repo root
# or:  python tools/console.py
```

It reuses an already-running read API on the port if one is up. See
[../tools/console.py](../tools/console.py). The rest of this doc covers running
the pieces directly.

## The one idea: one content, many renderers

The whole point of this package is the boundary the design has to hold: **the CLI,
Slack, and Teams must show the same content and differ only in rendering.** So the
briefing is compiled **once** into a presentation-neutral **block IR**, and each
surface is a pure function from that IR to its own format.

```text
briefing CONTRACT (data)         view-model/contract.ts
        │
        ▼  buildBriefing()       view-model/build-briefing.ts   <- all wording + ordering
   Block[]  (the IR)             view-model/blocks.ts           <- semantic, no colors
        │
        ├── renderers/ink      -> React tree in the terminal   (richest)
        ├── renderers/text     -> plain string                 (pipes, tests)
        ├── renderers/slack    -> Block Kit JSON
        └── renderers/teams    -> Adaptive Card JSON
```

Rule of thumb:

- **Content** (what it says, in what order, which fields) lives in the view-model.
  Change copy once, every surface updates.
- **Presentation** (hex colors, emoji, column widths, button styles) lives in a
  renderer. A new surface is a new renderer over the same `Block[]` - it never
  touches the content.

A `Block` carries meaning and data plus a semantic `Tone` (`t0`, `high`, `good`,
...). Each renderer maps `Tone` to its own affordance: Ink -> hex, Slack -> emoji
and button style, Teams -> Adaptive Card color enum.

## Interactive (the Ink surface)

The `cli` surface is a **REPL**, not a one-shot print. It streams the briefing,
then keeps a live prompt at the bottom - like a coding CLI (Copilot / Claude
Code). It does not exit after the briefing.

- Type a question, a card number (`1`-`3`) to dig into a decision, or `a` / `r` /
  `w` to act on a card; the reply streams in and the exchange is committed to the
  scroll-up log (it survives exit).
- `/exit` (or `/quit`) leaves. `Esc` clears the line.
- Read-only: it only looks things up unless you ask it to act, and acting is
  PR-native. Replies here are synthesized from the synthetic payload and marked
  `(mock)` - there is no live backend yet.
- Input uses Ink's built-in `useInput` (no extra deps). Without a TTY (piped/CI)
  it prints the briefing and exits instead of blocking.

The other surfaces (`text`, `slack`, `teams`) are one-shot: they emit their
format to stdout from the same block IR.

## Data source: sample or the live read API

`--source` selects where the briefing data comes from - the block IR and every
renderer are identical either way:

- `--source=sample` (default) - synthetic data from `data/sample-briefing.ts`
  (`--mode=needs-me|all-clear`).
- `--source=api` - the live read-only console API (`/kpi`, `/hil-queue`,
  `/audit`); `--api=<url>` sets the base URL (default `http://127.0.0.1:8010`).
  The briefing is compiled by `view-model/build-from-readmodel.ts`, and the
  interactive narrator answers `kpi` / `hil queue` / `recent audit` questions by
  calling those same endpoints live (a deterministic tool router; the LLM
  narrator is a fork drop-in). Nothing here mutates - read-only.

Start the dev read API first:

```bash
FDAI_READ_API_DEV_MODE=1 uv run --with uvicorn \
  uvicorn 'fdai.delivery.read_api._local:app' --factory --port 8010
# then, in cli/:
npm run api          # interactive terminal against live data
tsx src/cli.tsx --surface=slack --source=api   # live data as Block Kit
```

## Run

```bash
cd cli
npm install

npm run cli      # Ink terminal render (default)
npm run text     # plain text
npm run slack    # Slack Block Kit JSON
npm run teams    # Teams Adaptive Card JSON
npm test         # vitest unit tests (view-model + renderers)
```

Flags (via `tsx src/cli.tsx`):

- `--surface=cli|text|slack|teams` - which renderer.
- `--mode=needs-me|all-clear` - which world state (HIL decisions pending, or nothing
  to sign off).

```bash
tsx src/cli.tsx --surface=slack --mode=all-clear
```

## Files

| Path | Role |
|------|------|
| [src/view-model/contract.ts](src/view-model/contract.ts) | briefing input contract (mirrors the read-only `console-tool` payload) |
| [src/view-model/blocks.ts](src/view-model/blocks.ts) | the presentation-neutral block IR (`Block`, `Tone`) |
| [src/view-model/build-briefing.ts](src/view-model/build-briefing.ts) | the single compiler: contract -> `Block[]` |
| [src/view-model/build-from-readmodel.ts](src/view-model/build-from-readmodel.ts) | compile a live read-API snapshot -> `Block[]` |
| [src/data/read-api.ts](src/data/read-api.ts) | read-only client for the console API (`/kpi`, `/hil-queue`, `/audit`) |
| [src/data/sample-briefing.ts](src/data/sample-briefing.ts) | synthetic payload for both modes |
| [src/renderers/ink/](src/renderers/ink/) | terminal renderer (React/Ink) + tone->hex theme |
| [src/renderers/text.ts](src/renderers/text.ts) | plain-text renderer |
| [src/renderers/slack.ts](src/renderers/slack.ts) | Slack Block Kit renderer |
| [src/renderers/teams.ts](src/renderers/teams.ts) | Teams Adaptive Card renderer |
| [src/renderers/shared/](src/renderers/shared/) | ascii bar chart + sparkline helpers |
| [src/cli.tsx](src/cli.tsx) | entrypoint: build once, render per `--surface` |

## Boundaries

- **Read-only.** The console renders state and the HIL queue; it issues no
  privileged calls. Approvals are PR-native (`approve` = open a PR); nothing here
  executes an action. The decision-card keys are illustrative in this mock.
- **Not wired to the core yet.** Data comes from `sample-briefing.ts`. A real
  deployment would feed `buildBriefing()` the payload from the read API
  ([../console/src/types.ts](../console/src/types.ts),
  [../src/fdai/delivery/read_api/read_model.py](../src/fdai/delivery/read_api/read_model.py)).
- **Same vocabulary** as the architecture (`T0`/`T1`/`T2`, `side_effect_class`,
  risk levels). See
  [../.github/instructions/app-shape.instructions.md](../.github/instructions/app-shape.instructions.md)
  (Operator console) and
  [../.github/instructions/architecture.instructions.md](../.github/instructions/architecture.instructions.md)
  (Action ontology and console vocabulary).
