# operator-console CLI (Ink)

The real FDAI (**Forward Deployed Agents for Cloud Ops**) **operator-console** as a
terminal app, built on
[Ink](https://github.com/vadimdemedes/ink) (React for the terminal). It is the
runnable successor to the design mock at [../mocks/ui-cli](../mocks/ui-cli).

> Node/TypeScript island in a Python-first monorepo, like
> [../console](../console). No build step is required to run it (`tsx` executes
> the TypeScript directly). The surface is bilingual and customer-agnostic.

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

Conversation follows the same boundary in the other direction:

```text
CLI input + screen snapshot
  -> POST /chat
  -> shared Python coordinator, tools, grounding, and verifier
  -> answer
  -> CLI renderer
```

The TypeScript package contains no model client, cloud credential flow, intent
router, or console-tool implementation. Those policies live in the shared
backend so the CLI, web console, and future pull-direction channels cannot
disagree.

## Interactive (briefing + bottom-fixed REPL)

The `cli` surface draws the briefing once with Ink (colour, cards, bars), then
runs an interactive REPL ([src/repl.ts](src/repl.ts)) with a **bottom-fixed
input box** - like a coding CLI: the conversation scrolls in the top area and the
prompt stays pinned to the last two lines.

- The briefing is rich terminal UI, so Ink renders it (committed to the
  scrollback via `<Static>`, see
  [src/renderers/ink/briefing-oneshot.tsx](src/renderers/ink/briefing-oneshot.tsx)).
- The **input** is not an Ink widget. Ink repaints the whole frame, which fights
  the terminal's input cursor and pushes **IME composition (Korean and other
  languages) to the wrong place**. Instead the REPL uses a DEC **scroll region**
  to split the screen (conversation on top, fixed input box on the bottom) and
  edits the line in raw mode, keeping the **real terminal cursor at the caret** -
  so Korean composes exactly where you type, and the input never drifts.
- Editing shortcuts: Left/Right move the cursor, Ctrl+A/Ctrl+E jump to start/end,
  Backspace and Ctrl+W (word) and Ctrl+U (line) delete, Up/Down recall history.

Usage:

- Type a question. The reply from the shared `/chat` coordinator streams into
  the conversation above the input box.
- `/exit` (or `/quit`, Ctrl+C) leaves.
- Read-only: the CLI sends no execution or approval request. Requests for a
  change must re-enter the typed pipeline through the appropriate non-console
  workflow.
- Without a TTY (piped/CI) it prints the briefing and exits instead of blocking.

The other surfaces (`text`, `slack`, `teams`) are one-shot: they emit their
format to stdout from the same block IR.

## Data source: sample or the live pipeline

`--source` selects where the data comes from:

- `--source=sample` (default) - synthetic data from `data/sample-briefing.ts`
  (`--mode=needs-me|all-clear`). This is a renderer fixture: it prints the
  block-IR briefing and exits without opening a conversational REPL.
- `--source=api` - the live read-only console API; `--api=<url>` sets the base
  URL (default `http://127.0.0.1:8010`). In a terminal this opens the **live
  cockpit** ([src/cockpit.ts](src/cockpit.ts)): a single alternate-screen view
  fed by the read API's `/live/stream` (SSE), where each frame is a **real
  StageEvent from an actual `ControlLoop` run** (real rule catalog, T0 engine,
  Rego). The header reads `Forward Deployed Agents - Cloud Ops - read-only`, followed
  by a plain-language summary of what has been handled (fixed-rules vs stepped
  back vs auto-applied vs awaiting you) and a standing trust line (read-only,
  every change opens a pull request, shadow-first, fully audited). The feed
  narrates each event in operator language (`auto-applied as a shadow pull
  request`, `stepped back - no matching rule yet`) joined across route + verify +
  audit, tagged with the tier that decided it. The bottom is a fixed input box
  whose answers **stream** in. This is real pipeline data, not the seeded `/kpi`
  aggregates; questions about live state are answered from the cockpit's own
  counters. Each question carries those counters and recent activity as a
  self-describing snapshot to the shared `/chat` coordinator, so the answer is
  grounded in the screen without moving policy into the channel. Piped/non-TTY
  falls back to the one-shot briefing. The SSE reader limits each complete or
  pending frame to 256 KiB and cancels the connection when parsing fails, so an
  upstream frame cannot grow terminal memory without bound. Nothing here mutates
  - read-only.

  **Views (natural-language screen control).** The main panel is a switchable
  component, driven by plain language (English or Korean):

  - `stream` - the live scrolling op feed (default).
  - `overview` - a calm dashboard (routing-mix bars, a throughput sparkline,
    outcome counters, top resource types) instead of a firehose.
  - `focus <type>` - the feed filtered to one resource type (`focus network`).
  - `pause` / `resume` - freeze or resume the feed (events still count).

  Say things like `overview`, `stream`, `pause`, `focus network`, `clear`. These
  are parsed locally because they change only terminal presentation. The active
  view is shown as a badge in the header bar. Data lookup, diagnosis, grounding,
  and any multi-step tool flow remain server-owned.

  Unlike the briefing (which uses Ink), the live cockpit is a hand-rolled
  raw-ANSI renderer: Ink repaints the whole tree on every change, which moves the
  hardware cursor and makes a CJK/IME preedit jump away from the caret. The
  cockpit instead addresses rows directly, keeps the real cursor at the input
  caret, and draws each frame into one buffer flushed inside a DEC 2026
  synchronized-update pair (`\e[?2026h`/`\e[?2026l`) so the terminal applies a
  whole frame atomically (no row-by-row tearing). Terminals without mode 2026
  ignore the markers. The activity feed is a hardware **scroll region**
  (DECSTBM): a new op scrolls the region up one line and draws only the new row,
  so records glide upward instead of the whole feed repainting. The cursor is
  never hidden/shown per frame (that resets the terminal's blink timer), so the
  caret blinks steadily while the feed moves underneath it.

## Narrator (natural language)

Questions typed at the prompt go to `POST /chat` through
[src/data/read-api.ts](src/data/read-api.ts). The Python read API owns intent
routing, role-aware tool evidence, model selection, grounding, semantic shadow
verification, response verification, and refusal behavior. The CLI contributes
only a self-describing snapshot of what it currently renders and displays the
returned answer.

Configure the narrator on the read-API process, not in the CLI process. The
backend accepts the `FDAI_NARRATOR_*` settings and `resolved-models.json`
described in the operator-console design. When the backend is unavailable, the
CLI reports the HTTP failure; it does not silently switch to a second policy
implementation.

Start the dev read API first:

```bash
FDAI_READ_API_DEV_MODE=1 uv run --with uvicorn \
  uvicorn 'fdai.delivery.read_api.dev.local:app' --factory --port 8010
# then, in cli/:
npm run api          # interactive terminal against live data
tsx src/cli.tsx --surface=slack --source=api   # live data as Block Kit
```

## Run

```bash
cd cli
npm install

npm run cli      # Ink terminal render (default)
npm run api      # live interactive cockpit through the shared read API
npm run text     # plain text
npm run slack    # Slack Block Kit JSON
npm run teams    # Teams Adaptive Card JSON
npm test         # vitest unit tests (view-model + renderers)
```

Flags (via `tsx src/cli.tsx`) accept either `--name=value` or `--name value`.
Unknown, duplicate, empty, and malformed options exit with status 2.

- `--surface=cli|text|slack|teams` - which renderer.
- `--source=sample|api` - renderer fixture or shared live API.
- `--mode=needs-me|all-clear` - which world state (HIL decisions pending, or nothing
  to sign off).
- `--locale=en|ko` - which language the narration renders in (default `en`; also
  reads `FDAI_LOCALE`). Strings come from the message catalog in
  [src/i18n](src/i18n); a key missing from a locale falls back to English, never a
  blank. Data values (operator name, window label, resource ids) are never
  translated.
- `--api=http://127.0.0.1:8010` - shared read-API base URL. Only HTTP(S) URLs
  without embedded credentials, a query, or a fragment are accepted.
- `--help` / `-h` - print usage and exit.

```bash
tsx src/cli.tsx --surface=slack --mode=all-clear
tsx src/cli.tsx --surface=text --locale=ko
```

## Files

| Path | Role |
|------|------|
| [src/view-model/contract.ts](src/view-model/contract.ts) | briefing input contract (mirrors the read-only `console-tool` payload) |
| [src/view-model/blocks.ts](src/view-model/blocks.ts) | the presentation-neutral block IR (`Block`, `Tone`) |
| [src/view-model/build-briefing.ts](src/view-model/build-briefing.ts) | the single compiler: contract -> `Block[]` |
| [src/view-model/build-from-readmodel.ts](src/view-model/build-from-readmodel.ts) | compile a live read-API snapshot -> `Block[]` |
| [src/i18n/](src/i18n/) | L2 message catalogs (`messages.en.json` source + `messages.ko.json`) and the `t()` helper (dot-path lookup, `{name}` params, English fallback) |
| [src/data/read-api.ts](src/data/read-api.ts) | read-only client for `/kpi`, `/hil-queue`, `/audit`, and shared `/chat` |
| [src/channel-context.ts](src/channel-context.ts) | minimal presentation context passed to the REPL and cockpit |
| [src/data/sample-briefing.ts](src/data/sample-briefing.ts) | synthetic payload for both modes |
| [src/renderers/ink/](src/renderers/ink/) | terminal briefing renderer (React/Ink) + tone->hex theme |
| [src/renderers/text.ts](src/renderers/text.ts) | plain-text renderer |
| [src/renderers/slack.ts](src/renderers/slack.ts) | Slack Block Kit renderer |
| [src/renderers/teams.ts](src/renderers/teams.ts) | Teams Adaptive Card renderer |
| [src/renderers/shared/](src/renderers/shared/) | ascii bar chart + sparkline helpers |
| [src/repl.ts](src/repl.ts) | interactive readline REPL (IME-safe input; shared backend answers) |
| [src/cockpit.ts](src/cockpit.ts) | live one-screen cockpit fed by the real pipeline over SSE (`--source=api`) |
| [src/cli.tsx](src/cli.tsx) | entrypoint: build once, render per `--surface` |

## Boundaries

- **Read-only.** The console renders state and the HIL queue; it issues no
  privileged calls. Nothing here executes or approves an action.
- **Thin channel.** The CLI owns terminal input, screen state, Block IR, and
  rendering. Shared Python modules own data access, conversation policy,
  grounding, verification, and cloud-provider adapters.
- **Sample means presentation only.** `sample-briefing.ts` is a renderer fixture,
  not an alternate control plane or narrator.
- **Same vocabulary** as the architecture (`T0`/`T1`/`T2`, `side_effect_class`,
  risk levels). See
  [../.github/instructions/app-shape.instructions.md](../.github/instructions/app-shape.instructions.md)
  (Operator console) and
  [../.github/instructions/architecture.instructions.md](../.github/instructions/architecture.instructions.md)
  (Action ontology and console vocabulary).
