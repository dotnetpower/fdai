# FDAI Console CLI

The FDAI Console CLI is the terminal surface for read-only operational activity and
grounded conversations. It uses Ink for one-shot briefings and an IME-safe ANSI
cockpit for live Operator Service sessions.

> Node/TypeScript operator package in a Python-first multi-service workspace, like
> [../console](../console). No build step is required to run it (`tsx` executes
> the TypeScript directly). The surface is bilingual and customer-agnostic.

## Quick start (one command)

Prepare the local stack once, then use the Python launcher. The launcher starts an
independent Operator Service with the loopback-only Azure CLI profile, waits for
health, runs the CLI, and stops only the service process it started.

```bash
bash scripts/deployment/local/prepare-console-full-stack.sh
uv run python -m tools.console          # from the repo root
```

The launcher reuses an already-running API only when a protected or open read probe
succeeds. A Browser Entra service on port 8010 remains unchanged; the launcher uses
another loopback port for its CLI profile. See [../tools/console.py](../tools/console.py).

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

## Interactive terminal

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

The live cockpit follows the interaction hierarchy used by current coding agents:
a quiet product header, explicit connection and trust state, observed work in the
main region, a bounded answer region, and one persistent composer. FDAI keeps its
own product identity and safety vocabulary.

Usage:

- Type a question. The reply from the shared `/chat` coordinator streams into
  the conversation above the input box.
- `/exit` (or `/quit`, Ctrl+C) leaves.
- `/help` shows view and editing commands. `/status` explains the visible trust
  and connection indicators.
- Read-only: the CLI sends no execution or approval request. Requests for a
  change must re-enter the typed pipeline through the appropriate non-console
  workflow.
- Without a capable TTY, with `TERM=dumb`, or below 80 by 16 cells, it emits stable
  plain text and exits instead of drawing a broken interface.
- `NO_COLOR=1` removes color without removing labels. `FDAI_REDUCED_MOTION=1`
  disables answer reveal animation and the changing work indicator.

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
  fed by the Operator API's `/live/stream` (SSE), where each frame is a **real
  StageEvent from an actual `ControlLoop` run** (real rule catalog, T0 engine,
  Rego). The header reads `FDAI Console - read only`, followed
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

  **Views (local slash commands).** The main panel is a switchable component.
  Slash commands change presentation only and never enter the semantic intent path:

  - `stream` - the live scrolling op feed (default).
  - `overview` - a calm dashboard (routing-mix bars, a throughput sparkline,
    outcome counters, top resource types) instead of a firehose.
  - `focus <type>` - the feed filtered to one resource type (`focus network`).
  - `pause` / `resume` - freeze or resume the feed (events still count).

  Use `/overview`, `/stream`, `/pause`, `/resume`, `/focus network`, and `/clear`.
  These are parsed locally because they change only terminal presentation. The active
  view is shown as a badge in the header bar. Data lookup, diagnosis, evidence check,
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
[src/data/operator-api.ts](src/data/operator-api.ts). The Python Operator API owns intent
routing, role-aware tool evidence, model selection, evidence check, semantic shadow
verification, response verification, and refusal behavior. The CLI contributes
only a self-describing snapshot of what it currently renders and displays the
returned answer.

Configure the narrator on the Operator API process, not in the CLI process. The
backend accepts the `FDAI_NARRATOR_*` settings and `resolved-models.json`
described in the operator-console design. When the backend is unavailable, the
CLI reports the HTTP failure; it does not silently switch to a second policy
implementation.

### Authentication

The CLI never accepts a bearer token in an argument, URL, or environment variable.
For a loopback API it first requests `GET /local-auth/me`. When the Operator Service
is running with `FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1`, the server resolves the
current interactive Azure CLI user, applies its fixed Contributor ceiling, and
returns an opaque process-local session header. The CLI keeps that value in memory
and attaches it to snapshot, chat, and SSE requests.

The bootstrap endpoint is unavailable outside loopback and when Browser Entra is
active. A missing endpoint falls back to an ordinary read request; a `401` or `403`
stays closed and reports how to start the dedicated CLI profile. This does not
weaken the standard Browser Entra service or expose Thor's identity.

Start the supported CLI profile from the repository root:

```bash
uv run python -m tools.console
```

If the independent Operator Service is already running with the CLI profile, use
`npm run api`. One-shot live Slack, Teams, and text rendering uses the same automatic
session bootstrap.

## Run

```bash
cd cli
npm install

npm run cli      # Ink terminal render (default)
npm run api      # live interactive cockpit through the shared Operator API
npm run text     # plain text
npm run slack    # Slack Block Kit JSON
npm run teams    # Teams Adaptive Card JSON
npm test         # vitest unit tests (view-model + renderers)
```

Flags (via `tsx src/cli.tsx`) accept either `--name=value` or `--name value`.
Unknown, duplicate, empty, and malformed options exit with status 2.

- `--surface=cli|text|slack|teams` - which renderer.
- `--source=sample|api` - renderer fixture or shared live API.
- `--mode=needs-me|all-clear` - which world state (human approval decisions pending, or nothing
  to sign off).
- `--locale=en|ko` - which language the narration renders in (default `en`; also
  reads `FDAI_LOCALE`). Strings come from the message catalog in
  [src/i18n](src/i18n); a key missing from a locale falls back to English, never a
  blank. Data values (operator name, window label, resource ids) are never
  translated.
- `--api=http://127.0.0.1:8010` - shared Operator API base URL. Only HTTP(S) URLs
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
| [src/view-model/build-from-readmodel.ts](src/view-model/build-from-readmodel.ts) | compile a live Operator API snapshot -> `Block[]` |
| [src/i18n/](src/i18n/) | L2 message catalogs (`messages.en.json` source + `messages.ko.json`) and the `t()` helper (dot-path lookup, `{name}` params, English fallback) |
| [src/data/operator-api.ts](src/data/operator-api.ts) | read-only client for `/kpi`, `/hil-queue`, `/audit`, and shared `/chat` |
| [src/operator-api-session.ts](src/operator-api-session.ts) | loopback-only local session bootstrap; keeps the opaque bearer in memory |
| [src/terminal-capabilities.ts](src/terminal-capabilities.ts) | TTY geometry, color, and reduced-motion capability resolution |
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

- **Read-only.** The console renders state and the human approval queue; it issues no
  privileged calls. Nothing here executes or approves an action.
- **Thin channel.** The CLI owns terminal input, screen state, Block IR, and
  rendering. Shared Python modules own data access, conversation policy,
  evidence check, verification, and cloud-provider adapters.
- **No credential input.** The server owns Azure CLI identity resolution. The CLI
  accepts only the opaque loopback session and never persists or prints it.
- **Sample means presentation only.** `sample-briefing.ts` is a renderer fixture,
  not an alternate control plane or narrator.
- **Same vocabulary** as the architecture (`T0`/`T1`/`T2`, `side_effect_class`,
  risk levels). See
  [../.github/instructions/app-shape.instructions.md](../.github/instructions/app-shape.instructions.md)
  (Operator console) and
  [../.github/instructions/architecture.instructions.md](../.github/instructions/architecture.instructions.md)
  (Action ontology and console vocabulary).
