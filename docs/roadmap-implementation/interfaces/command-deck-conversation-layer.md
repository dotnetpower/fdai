# Command Deck Conversation Layer implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Portable Command Deck conversation layer and source-streaming study | implemented | `ui/calm-slate-deck-conversation.css`; `mocks/ui/deck-sources.html`; `mocks/ui/assets/deck-sources.js`; `mocks/ui/tests/deck-sources.test.mjs` and `chat-current.test.mjs` (`27 passed`); `console/src/shared-style-tokens.test.ts` (`7 passed`); Console typecheck | Static mock only. Rules that reuse shared primitives stay under `.cs-deck-conversation`, so the Console renders unchanged until it adopts the layer. The run record mirrors the Console trajectory, execution timeline, and model provider waterfall with synthetic data and per-turn trace capture. The replay's scroll follower is study behavior; adopting it needs a matching change to the Console `scroll-stick` helpers. |
| Console conversation screen adoption of the layer | not-started | [Module map presentation boundary](../../roadmap/interfaces/command-deck-conversation-layer.md#adoption) | Adoption replaces the legacy `.deck-rt-*`, `.deck-gr-*`, `.deck-src-*`, citation, follow-up, readiness, verification, trajectory, execution-timeline, and model-trace declarations instead of overriding them. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-28 | implemented | Adopted this focused ledger when the layer design moved out of the Operator Console module map. Earlier transitions, including the study rebuild, the run record, the six replay polish rounds, the shared code tokens, and navigation consent, are recorded in the [module map ledger](operator-console-module-map.md). | `current change`; `docs/roadmap/interfaces/command-deck-conversation-layer.md`; `node --test mocks/ui/tests/chat-current.test.mjs mocks/ui/tests/deck-sources.test.mjs` (`27 passed`); `npm --prefix console test -- --run src/shared-style-tokens.test.ts src/components/mock-visual-boundary.test.ts` (`12 passed`) | Adopt the layer in the Console conversation screen. |

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
