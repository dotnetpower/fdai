# Command Deck Conversation Layer implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Portable Command Deck conversation layer and source-streaming study | implemented | `ui/calm-slate-deck-conversation.css`; `mocks/ui/deck-sources.html`; `mocks/ui/assets/deck-sources.js`; `mocks/ui/tests/deck-sources.test.mjs` and `chat-current.test.mjs` (`27 passed`); `console/src/shared-style-tokens.test.ts` (`7 passed`); Console typecheck | Static mock only. Rules that reuse shared primitives stay under `.cs-deck-conversation`, so the Console renders unchanged until it adopts the layer. The run record mirrors the Console trajectory, execution timeline, and model provider waterfall with synthetic data and per-turn trace capture. The replay's scroll follower is study behavior; adopting it needs a matching change to the Console `scroll-stick` helpers. |
| Adaptive investigation study and investigation roles | implemented | `ui/calm-slate-deck-conversation.css` investigation roles; `mocks/ui/deck-adaptive.html`; `mocks/ui/assets/deck-sources.js`; `mocks/ui/assets/deck-study.css`; `mocks/ui/fixtures/adaptive/`; `mocks/ui/tests/deck-adaptive.test.mjs` (`10 passed`), `deck-sources.test.mjs` (`23 passed`), and `chat-current.test.mjs` (`4 passed`, including the new route); `console/src/shared-style-tokens.test.ts` | Static mock only, replaying eight synthetic investigations that the Console contract tests also parse. Reads run as gated parallel waves, cards separate operation, authorization, evidence authority, and execution authority, budget telemetry replaces policy limits only at settle, and Draft remediation and follow-ups start separate preview requests that run nothing. |
| Console conversation screen adoption of the layer | not-started | [Module map presentation boundary](../../roadmap/interfaces/command-deck-conversation-layer.md#adoption) | Adoption replaces the legacy `.deck-rt-*`, `.deck-gr-*`, `.deck-src-*`, citation, follow-up, readiness, verification, trajectory, execution-timeline, and model-trace declarations instead of overriding them. The investigation roles map to `investigation-timeline.tsx` and `grounded-reply.tsx`. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-28 | implemented | Adopted this focused ledger when the layer design moved out of the Operator Console module map. Earlier transitions, including the study rebuild, the run record, the six replay polish rounds, the shared code tokens, and navigation consent, are recorded in the [module map ledger](operator-console-module-map.md). | `current change`; `docs/roadmap/interfaces/command-deck-conversation-layer.md`; `node --test mocks/ui/tests/chat-current.test.mjs mocks/ui/tests/deck-sources.test.mjs` (`27 passed`); `npm --prefix console test -- --run src/shared-style-tokens.test.ts src/components/mock-visual-boundary.test.ts` (`12 passed`) | Adopt the layer in the Console conversation screen. |
| 2026-09-28 | implemented | Added the adaptive investigation study: a plan line, a context receipt, gated parallel read waves that fold when done, activity cards with typed calls and provider representations, workflow milestones, settled budget telemetry, and a fact-grid answer. Stop keeps finished reads, and Draft remediation starts a separate request. The one-shot study's page styles moved to a shared stylesheet. | `current change`; `ui/calm-slate-deck-conversation.css`; `mocks/ui/deck-adaptive.html`; `mocks/ui/deck-sources.html`; `mocks/ui/assets/deck-sources.js`; `mocks/ui/assets/deck-study.css`; `mocks/ui/fixtures/adaptive/`; `node --test mocks/ui/tests/deck-adaptive.test.mjs mocks/ui/tests/deck-sources.test.mjs mocks/ui/tests/chat-current.test.mjs` (`37 passed`); `npm --prefix console test -- --run src/deck src/shared-style-tokens.test.ts src/components/mock-visual-boundary.test.ts` (`1045 passed`) | Render the investigation roles in the Console after server emission of the work progress fields. |

### Remaining work

- [ ] Adopt `ui/calm-slate-deck-conversation.css` in the Console conversation screen: import it after the
  primitives, render its roles from the deck components, delete the superseded legacy `.deck-*`
  declarations, and record passing Console Deck tests plus a standard-5273 browser check that the
  retrieval trace, citations, sources panel, and run record show no text below 12 px.
- [ ] Port the study's scroll follow rules (question pin, verdict reveal, and position-based stop)
  into `console/src/deck/scroll-stick.ts`, and record passing Console Deck tests for the pinned,
  bottom-follow, and reader-scrolled cases.
- [ ] Apply the navigation consent rule to Console deck links and map the Console `CodeBlock` onto
  the shared `--cs-code-*` tokens, with passing Console Deck tests for both.
- [ ] Retain a real screen-reader pass for the study with the declared browser and screen-reader pair.
- [ ] Render the adaptive investigation roles from `investigation-timeline.tsx` and
  `grounded-reply.tsx` in the Console, and record passing Console Deck tests plus a standard-5273
  browser check that waves, activity cards, milestones, and the fact grid show no text below 12 px.
