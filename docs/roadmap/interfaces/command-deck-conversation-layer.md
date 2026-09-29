---
title: Command Deck Conversation Layer
---
# Command Deck Conversation Layer

This design defines the portable presentation layer for the Command Deck conversation screen and
the one static Command deck study that is its reference consumer. The layer is presentation only
and grants no Console, Operator API, or executor authority.

## Design at a glance

- `ui/calm-slate-deck-conversation.css` holds the portable conversation roles: evidence-source
  readiness, the retrieval trace, citations, evidence notes, the sources panel, follow-ups, the
  composer context, compact code blocks, structured answer blocks, and the run record with its
  phase strip, observed execution timeline, and model provider waterfall.
- `mocks/ui/deck.html` is the reference consumer: one Command deck page that replays every response
  form with one turn anatomy. One replay engine, `mocks/ui/assets/deck-sources.js`, renders every
  form. The incident, change, and memory forms and two answer scenarios come from
  `mocks/ui/assets/deck-forms.js`, and one page stylesheet, `mocks/ui/assets/deck-study.css`, frames
  the preview. The Answer form uses the readable layout of the
  [common answer presentation](operator-console.md#common-answer-presentation): the common answer
  renderer, `mocks/ui/assets/deck-answer.ts`, renders its Markdown and typed JSON answers with the
  Console's own parsers, and its preview controls render edited Markdown or JSON. The Console Command
  Deck imports the same layer, as [Adoption](#adoption) describes.
- The retired study addresses `deck-sources.html`, `deck-adaptive.html`, `deck-sources-v2.html`, and
  `incident-conversation.html` redirect to the matching form of `deck.html` and keep their query
  parameters. They carry no presentation of their own.
- Rules that reuse a shared primitive are scoped under `.cs-deck-conversation`, and
  `console/src/shared-style-tokens.test.ts` keeps the layer additive, so importing it changes no
  surface that doesn't render the root role.

## Adoption

Console adoption is a replacement migration. `console/src/styles.css` imports the layer after the
primitives, the deck overlay carries the `cs-deck-conversation` root role, the owning deck
components render the roles, and the superseded legacy `.deck-*` declarations are deleted instead
of overridden. Legacy class names stay only as hooks that code or tests query.

| Console surface | Layer roles it renders |
|-----------------|------------------------|
| Evidence-source readiness, the user bubble, the composer context, and follow-ups | Readiness, user line, context chip, Jump to latest, and follow-up roles |
| Retrieval trace | The live grounding panel, its steps and source window, and the answer skeleton |
| Grounded reply | Answer state, citations and cited-word runs, the action row (verdict with claim count, sources pill, quiet tools), the sources list, the processing disclosure, and the request card for an action draft |
| Code | The compact code pattern for answer code, JSON and text payloads, and generated code evidence. highlight.js token classes take the shared `--cs-code-*` tokens. |
| Run record | The record summary, phase strip, execution timeline, and model provider waterfall |
| Structured presentation and documents | The assembly line, the fact grid for summaries, the evidence note for limits, quiet facts for evidence and record rows, disclosures for collapsed blocks and exact values, and the document card for Markdown documents and verified document artifacts |
| Investigation | The start line on the plan role, the plan status and settled limits on the first panel, the context receipt, quiet milestone lines, and stopped reads |
| Common answer presentation | Citation buttons that open their source, answer evidence rows as the layer's source disclosures with Back to answer, the original Markdown on the quiet disclosure, and the readiness strip inside the evidence services disclosure |

Console sections without a study counterpart keep their structure and take the layer's status
colors, quiet labels, and 12 px floor: the run record's phase details, signals, and execution
details; the observed-work investigation timeline; the verification posture line and the evidence
services summary of the common answer presentation; and the presentation tables and charts. A
settled investigation panel folds when its work completed and stays open when it failed, was
partial, or was unavailable. An
operational brief flows with the answer instead of sitting in a card, and a callout with a neutral
or positive tone stays a quiet note, because only limits and gaps are attention. The brief head,
recorded-state line, evidence posture groups, and steps have no typed presentation block yet, so the
Console doesn't render them. The investigation keeps its observed-work list instead of wave rows,
because the `work_progress_shape` pin carries only the wave and planned-read counts, not which read
belongs to which wave. The Console uses the pin to name the plan and to keep a pause between waves
from starting the answer, as the
[work progress contract](operator-console-progressive-conversations.md#work-progress-contract)
describes.

## Response forms

The preview controls choose a response form and one of its scenarios. `?form=` and `?scenario=` open
the same state directly. Every form uses the same turn anatomy: the question, a read-only preparation
panel, a cited answer, structured answer blocks, the verification row, the sources panel, the run
record, and follow-ups.

| Form | Scenarios | What it shows |
|------|-----------|---------------|
| Answer | Grounded, partial evidence, source unavailable, conflicting evidence, corrected, unverified, connected resources | A one-shot cited answer. The unverified scenario holds an unsupported causal claim and shows only verified facts. Connected resources shares its correlation with the Trace and Agent Activity studies. |
| Investigation | The eight fixtures under `mocks/ui/fixtures/adaptive/` | The procedural form described in [Investigation form](#investigation-form). |
| Incident | Open incident, service readiness | An operational brief: a reference line and title, recorded state, a fact grid, explicit unknowns, a collapsed recorded timeline, and a read-only next step. |
| Change | Governed proposal, effect verification, cancellation | A typed request draft with its seven safeguards, an effect checked by an independent read, and a cancellation receipt limited to conversation state. |
| Memory and documents | Memory retention, Markdown document | A retention request that needs consent, and a document rendered from governed inputs with its Markdown source. |

Structured answer blocks are the parts after the prose: a brief head, a recorded-state line, a fact
grid, an evidence-posture group (verified, unavailable, and not claimed), a captioned table, ordered
steps, a collapsed timeline, a next safe step, a request card, and a rendered document. A proposal
or retention request is the only card in a reply, because it's one bounded unit of work. Its
controls start separate preview requests, and a blocked control states why next to it. Every run
record names its typed presentation profile, such as `governed_proposal` or `operational_brief`,
when the form has one.

These forms keep authority visible:

- A proposal can't be submitted until all seven safeguards are ready, and a separate executor
  identity applies any approved change.
- Effect verification needs an independent observation. The executor's dispatch receipt only shows
  that the provider accepted the request.
- Cancellation changes only the operator's own resumable conversation work, and the run record
  names that authority instead of `read`.
- Memory is retained only after consent. Raw logs, secrets, temporary state, and unverified claims
  are excluded.

## Workspace shell

The study frames the conversation with the Console shell primitives. The header holds search, New
conversation, Conversations, What the deck sees, and Close. Conversations opens the history panel,
which lists one conversation per form under Current screen and Other screens and can be filtered.
Choosing the current conversation replays it, and choosing another reopens the page on its form.
What the deck sees shows the reference screen that the composer chip adds to new questions, when it
was observed, and a Refresh action.

At or below a 1,100 px viewport, the shared primitives turn the history panel into an overlay with a
scrim and hide the context panel. Escape and the scrim close the overlay, and focus returns to the
header control. The transcript, the readiness strip, and the composer share one 900 px column and
the same gutters, so questions, answers, and the input align on the same two edges.

## Replay behavior

The study renders the full preparation plan as pending steps and shows each step's result only
after the step runs. It reads sources through a fixed window sized to the rows the turn will read,
streams whole words with a short pause after each sentence, and folds the preparation panel away
before the answer appears.

The transcript eases toward new content without lifting the question being answered above the top
edge. When the turn settles, it eases to the verification row, and it stops following as soon as
the operator scrolls, so text being read never jumps. A scroll that lands on the bottom follows the
newest content instead. Jump to latest appears at the end of the composer context row only when
real content sits below the visible edge. The Console applies the same rules through
`console/src/deck/scroll-stick.ts`, moving directly to each target instead of easing.

Like the Console, the study records model trace capture per turn. The run record shows model
events and provider lanes with request, system, and response digests only when capture was on for
that turn and the setting is still on. Turning the setting on never reveals provider data for a
turn that wasn't captured. A replayed turn maps the run record's synthetic schedule onto the phase
times it observed, so the recorded durations match what was shown.

## Investigation form

A procedural investigation keeps its work in the transcript instead of folding it away. Density
comes from the typed trajectory as the
[work progress contract](operator-console-progressive-conversations.md#work-progress-contract)
defines, never from answer prose. The study renders these roles:

- **Plan.** One line with the plan the compiler made, above the work it describes.
- **Waves.** One row per planned wave, with one status mark each: the wave number, a spinner, then
  the outcome. Reads in a wave run as parallel lanes, and the next wave starts only after the
  current one ends. A finished wave folds to a one-line summary, so the transcript stays calm while
  the next wave runs. A deterministic comparison, when planned, follows as the last row.
- **Activity cards.** Each read shows its label, kind, status, and duration. Its details show the
  operation, authorization result, evidence authority, execution authority none, the target
  identity, and the tool, then the typed call and the redacted provider representation as compact
  code blocks, and the output or the reason it has none. Details render only after the read ends.
- **Workflow milestones.** Deterministic progress facts after each wave, styled apart from answer
  text and never carrying evidence claims. Each reads as one quiet line; its "Progress" label
  remains for assistive technology.
- **Limits.** The policy limits while the turn runs. When the turn settles, the server's
  used-of-maximum telemetry replaces them. The study draws no live remaining-budget meter.
- **Context receipt.** A collapsed receipt for an applied operator preference, labeled as context
  rather than evidence or instructions.

The answer leads with the finding, then a fact grid, one line per check, any limits as evidence
notes, and a next safe step. Stopping keeps every finished read, marks running reads as stopped
and waves that haven't started as not started, and composes no answer. Suggested follow-ups start a
new request.

The study's investigation scenarios cover no drift, drift found, a timed-out read, conflicting
evidence, denied authorization, a clarification between equal matches, stale context, and an
exhausted budget. A drift finding offers Draft remediation as a separate request instead of
creating a draft. The scenarios read the synthetic trajectories in `mocks/ui/fixtures/adaptive/`,
which the Console's contract tests also parse.

## Code blocks

Run record payloads use the component gallery's compact code pattern: a dark code surface, a
language label with Copy, and syntax colors. The colors come from the shared `--cs-code-*` tokens in
`ui/calm-slate-tokens.css`, which the gallery also reads. Copy returns the exact source text. The
Console uses the same pattern for answer code and generated code evidence. Its highlighter's token
classes map to the shared tokens, and plain text is never highlighted by guessing a grammar.

When trace capture is on for a turn, each model call's dynamic system prompt also offers the public
synthetic prompt fixture, `mocks/ui/assets/prompts/system-prompt.example.md`. It opens inline as
read-only Markdown with Copy and Download, loads within a five-second deadline, and states a failed
load explicitly. Closing it cancels a pending load. The fixture is never a captured runtime prompt.

## Navigation consent

Selecting a source opens its provenance in place instead of leaving the conversation. Any deck
link to another screen, including a source's Open action and the evidence-source strip, first asks
the operator in a confirmation dialog and navigates only after consent. In-page anchors, new-tab
clicks, and file downloads aren't intercepted. In the Console, a docked or full-workspace
conversation closes on a route change, so its links ask first. The floating layout keeps the
conversation open across routes, so its links navigate directly.

## Related docs

| To learn about | Read |
|----------------|------|
| Console module ownership and boundaries | [Operator Console Module Map and Boundaries](operator-console-module-map.md) |
| UI evaluation criteria | [UI/UX quality rubric](../../reference/ui-ux-quality-rubric.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/command-deck-conversation-layer.md) |
