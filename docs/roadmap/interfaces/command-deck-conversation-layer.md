---
title: Command Deck Conversation Layer
---
# Command Deck Conversation Layer

This design defines the portable presentation layer for the Command Deck conversation screen and
the static study that is its reference consumer. The layer is presentation only and grants no
Console, Operator API, or executor authority.

## Design at a glance

- `ui/calm-slate-deck-conversation.css` holds the portable conversation roles: evidence-source
  readiness, the retrieval trace, citations, evidence notes, the sources panel, follow-ups, the
  composer context, compact code blocks, and the run record with its phase strip, observed
  execution timeline, and model provider waterfall.
- `mocks/ui/deck-sources.html` (one-shot answer) and `mocks/ui/deck-adaptive.html` (adaptive
  investigation) are the reference consumers. They share one replay engine,
  `mocks/ui/assets/deck-sources.js`, and one page stylesheet, `mocks/ui/assets/deck-study.css`.
  The Console doesn't import the layer yet.
- Rules that reuse a shared primitive are scoped under `.cs-deck-conversation`, and
  `console/src/shared-style-tokens.test.ts` keeps the layer additive, so importing it changes no
  existing surface.

## Adoption

Console adoption is a replacement migration. Import the layer after the primitives, add the root
role to the deck overlay, render the roles from the owning deck components, and delete the
superseded legacy `.deck-*` declarations instead of overriding them.

## Replay behavior

The study renders the full preparation plan as pending steps and shows each step's result only
after the step runs. It reads sources through a fixed window sized to the rows the turn will read,
streams whole words with a short pause after each sentence, and folds the preparation panel away
before the answer appears.

The transcript eases toward new content without lifting the question being answered above the top
edge. When the turn settles, it eases to the verification row, and it stops following as soon as
the operator scrolls, so text being read never jumps.

Like the Console, the study records model trace capture per turn. The run record shows model
events and provider lanes with request, system, and response digests only when capture was on for
that turn and the setting is still on. Turning the setting on never reveals provider data for a
turn that wasn't captured. A replayed turn maps the run record's synthetic schedule onto the phase
times it observed, so the recorded durations match what was shown.

## Adaptive investigation form

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
  text and never carrying evidence claims.
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
`ui/calm-slate-tokens.css`, which the gallery also reads. Copy returns the exact source text.

## Navigation consent

Selecting a source opens its provenance in place instead of leaving the conversation. Any deck
link to another screen, including a source's Open action and the evidence-source strip, first asks
the operator in a confirmation dialog and navigates only after consent. In-page anchors and
new-tab clicks aren't intercepted.

## Related docs

| To learn about | Read |
|----------------|------|
| Console module ownership and boundaries | [Operator Console Module Map and Boundaries](operator-console-module-map.md) |
| UI evaluation criteria | [UI/UX quality rubric](../../reference/ui-ux-quality-rubric.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/command-deck-conversation-layer.md) |
