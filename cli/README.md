# operator-console CLI (Ink)

The real FDAI (**Forward Deployed Agents for Cloud Ops**) **operator-console** as a
terminal app, built on
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

- Type a question, a card number to dig into a decision, or `a` / `r` / `w`; the
  reply streams into the conversation above the input box.
- `/exit` (or `/quit`, Ctrl+C) leaves.
- Read-only: it only looks things up unless you ask it to act, and acting is
  PR-native. Answers come from the narrator seam (deterministic, or the LLM when
  configured - see below).
- Without a TTY (piped/CI) it prints the briefing and exits instead of blocking.

The other surfaces (`text`, `slack`, `teams`) are one-shot: they emit their
format to stdout from the same block IR.

## Data source: sample or the live pipeline

`--source` selects where the data comes from:

- `--source=sample` (default) - synthetic data from `data/sample-briefing.ts`
  (`--mode=needs-me|all-clear`). Renders the block-IR briefing + the bottom-fixed
  REPL.
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
  counters so what it says always matches what is on screen. Piped/non-TTY falls
  back to the one-shot briefing. Nothing here mutates - read-only.

  **Views (natural-language screen control).** The main panel is a switchable
  component, driven by plain language (English or Korean):

  - `stream` - the live scrolling op feed (default).
  - `overview` - a calm dashboard (routing-mix bars, a throughput sparkline,
    outcome counters, top resource types) instead of a firehose.
  - `focus <type>` - the feed filtered to one resource type (`focus network`).
  - `pause` / `resume` - freeze or resume the feed (events still count).

  Say things like `overview`, `stream`, `pause`, `focus network`, `clear`. These
  are parsed locally (instant, no model). When the LLM narrator is active it can
  also arrange the view for free-form phrasings (e.g. "show me a chart") via a
  read-only `set_view` tool - it changes only what is displayed, never a
  resource. The active view is shown as a badge in the header bar.

  **Live inventory (read-only).** The narrator can answer questions the event
  stream cannot - "list the resource groups", "which VMs are running" - by
  querying **Azure Resource Graph** (the Inventory seam) with the `query_inventory`
  tool. It authenticates with an Azure AD token from your existing `az login`
  (no key, no env), runs a read-only Kusto query, and answers from the rows.
  Strictly read-only (ARG cannot mutate); results are row-capped. This is
  distinct from `get_live_overview`, which reports what the pipeline has
  *processed* (event counts, resource types), not what exists in the
  subscription. Policy evaluation (does a resource violate a rule) is a separate
  concern handled by OPA over the fetched resources - not this query surface.

  **Diagnostics.** For a symptom on a real resource - "the DB is slow", "my
  deploy did not apply", "what changed" - the narrator diagnoses with read-only
  Azure signals: `query_inventory` checks current state/`provisioningState` (and
  container-app `latestRevisionName`), Resource Health, and the `resourcechanges`
  table (what changed recently); `get_metrics` reads **Azure Monitor** metrics
  (CPU, DTU, response time, requests) to confirm a performance symptom with real
  numbers; `get_activity_log` reads the **Azure Activity Log** for failed
  operations and recent changes ("why did the deploy fail", "recent errors");
  `get_cost` reads **Cost Management** for spend ("this month's cost", "most
  expensive resource group / service"); `get_quota` reads **Compute usages** for
  capacity headroom ("is there quota left", "vCPU headroom"). Security-posture
  questions (public exposure, open NSG rules, encryption) are answered from
  Resource Graph. The narrator runs a **bounded multi-round tool loop**, so it can
  chain (find the resource id, then read its metrics) before answering. It never
  conflates the control plane's own pipeline telemetry with the operator's
  resources, and it is honest when a signal is not available. It also keeps a
  short **conversation history**, so follow-ups resolve against what was just
  discussed ("show the resource groups" -> "which has the most?" -> "its cost?").

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

Questions typed at the prompt go through the **narrator seam**
([src/narrator](src/narrator)). The narrator is a *translator, not a judge*: it
turns a question into read-only `console-tool` calls (`get_kpi`,
`get_hil_queue`, `get_recent_audit`) and answers only from their results - it
never acts (approvals are PR-native) and never invents numbers.

The narrator is **read-only and never acts.** Any request to change, fix, delete,
restart, scale, or approve a resource is refused with a plain explanation
(remediation is a reviewed pull request; HIL approvals happen via PR or ChatOps).
Questions about how the system works or what it guarantees - rollback, safety
invariants, trust tiers, the LLM quality gate, shadow-vs-enforce, rules and
overrides, the verticals, and which agent judges/approves/executes - are answered
from a grounded `describe_guarantees` tool, never invented. When a live data
source is not wired in (active overrides, a live anomaly/drift feed), the
narrator says so honestly rather than reusing unrelated numbers.

**UI-agnostic by design.** The narrator and its data tools (`query_inventory`,
`get_metrics`, `get_cost`, `get_quota`, `get_activity_log`, `describe_guarantees`)
are pure data - they have no dependency on the CLI cockpit and are reused by any
surface (CLI, a future web console, ChatOps). UI-specific behavior is supplied
through optional `NarratorContext` fields (`screen` for `set_view`, `live` for the
on-screen counters, `history` for follow-ups); a different UI provides its own or
omits them. The tools are covered by network-free contract tests
([test/tools-azure.test.ts](test/tools-azure.test.ts)), so the data layer stays
correct as the UI evolves.

**The narrator prompt lives in the ontology, not in code.** It is authored once
as catalog-as-code YAML under
[../rule-catalog/prompts](../rule-catalog/prompts): a UI-agnostic base
(`base/operator-console-narrator.v1.yaml`) plus a CLI surface overlay
(`packs/operator-console-cli.v1.yaml`), both bound to the `console.narrator`
capability so they never enter T2 quality-gate composition. This CLI loads and
composes them via [src/narrator/prompt-store.ts](src/narrator/prompt-store.ts);
the Python read-API chat backend loads the same base through
`core/prompts/registry.py`. So every surface shares one prompt source of truth -
edit the YAML, not the TypeScript.

**The tool contracts are shared too.** Each data tool's model-facing `description`
and `input_schema` live in the ontology manifest
[../rule-catalog/operator-console/tools.v1.yaml](../rule-catalog/operator-console/tools.v1.yaml)
(outside `prompts/`, so the prompt/T2-tool registries never mis-parse it). This
CLI loads them via [src/narrator/tool-store.ts](src/narrator/tool-store.ts) and
keeps only the `run` implementation in TypeScript; a web console or the Python
backend loads the same manifest and supplies its own `run`. The CLI-only
`set_view` display control stays in code (it is a surface affordance, not a
shared data tool).

Two implementations share one interface, chosen at startup:

- **deterministic** (fallback, zero external dependency) - keyword routing over
  the tools. Handles `kpi` / `hil queue` / `recent audit`, card numbers, and
  `a`/`r`/`w`; other phrasings get a live-state summary.
- **llm** - an OpenAI-compatible model that understands free-form natural
  language (any language, including Korean) and calls the same tools. It is
  selected automatically, in this order:

  1. **Zero config (keyless, preferred)** - when `resolved-models.json` (the
     pipeline's env-specific resolver output, found via `LLM_RESOLVED_MODELS_PATH`
     or searched upward from the cwd) carries a `narrator` block, the narrator
     talks to Azure OpenAI using an **Azure AD token minted from your existing
     `az login`** (`az account get-access-token`). No API key, no env exports.

     ```json
     { "narrator": { "endpoint": "https://<res>.openai.azure.com/",
                     "deployment": "gpt-4o-mini",
                     "api_version": "2024-08-01-preview" } }
     ```

     `resolved-models.json` is gitignored (it is env-specific and may carry
     customer-identifying values), so the endpoint never lands in the repo.
  2. **Explicit env config** (overrides the above; the key only ever comes from
     the environment):

     ```bash
     export FDAI_NARRATOR_BASE_URL=https://api.openai.com/v1   # or Azure endpoint
     export FDAI_NARRATOR_API_KEY=...                          # required
     export FDAI_NARRATOR_MODEL=gpt-4o-mini                    # or Azure deployment
     export FDAI_NARRATOR_PROVIDER=openai                      # openai | azure
     # Azure only: FDAI_NARRATOR_API_VERSION=2024-08-01-preview
     ```
  3. **Pipeline endpoint var** - `FDAI_LLM_ENDPOINT` + `FDAI_NARRATOR_MODEL`
     (Azure via `az login`, keyless).

  The active narrator is shown in the prompt hint (`narrator` vs `AI narrator`).
  With none of these resolvable, the deterministic narrator is used.

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
npm run text     # plain text
npm run slack    # Slack Block Kit JSON
npm run teams    # Teams Adaptive Card JSON
npm test         # vitest unit tests (view-model + renderers)
```

Flags (via `tsx src/cli.tsx`):

- `--surface=cli|text|slack|teams` - which renderer.
- `--mode=needs-me|all-clear` - which world state (HIL decisions pending, or nothing
  to sign off).
- `--locale=en|ko` - which language the narration renders in (default `en`; also
  reads `FDAI_LOCALE`). Strings come from the message catalog in
  [src/i18n](src/i18n); a key missing from a locale falls back to English, never a
  blank. Data values (operator name, window label, resource ids) are never
  translated.

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
| [src/data/read-api.ts](src/data/read-api.ts) | read-only client for the console API (`/kpi`, `/hil-queue`, `/audit`) |
| [src/narrator/](src/narrator/) | narrator seam: read-only tools + deterministic / LLM implementations + factory |
| [src/data/sample-briefing.ts](src/data/sample-briefing.ts) | synthetic payload for both modes |
| [src/renderers/ink/](src/renderers/ink/) | terminal briefing renderer (React/Ink) + tone->hex theme |
| [src/renderers/text.ts](src/renderers/text.ts) | plain-text renderer |
| [src/renderers/slack.ts](src/renderers/slack.ts) | Slack Block Kit renderer |
| [src/renderers/teams.ts](src/renderers/teams.ts) | Teams Adaptive Card renderer |
| [src/renderers/shared/](src/renderers/shared/) | ascii bar chart + sparkline helpers |
| [src/repl.ts](src/repl.ts) | interactive readline REPL (IME-safe input; narrator answers) |
| [src/cockpit.ts](src/cockpit.ts) | live one-screen cockpit fed by the real pipeline over SSE (`--source=api`) |
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
