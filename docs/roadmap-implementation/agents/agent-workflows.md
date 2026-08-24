# Agent Workflows implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Thirteen-workflow metadata registry | implemented | `services/core-control-plane/src/fdai/agents/_framework/workflows.py`; `services/core-control-plane/tests/agents/test_wave7_workflows.py` | All registered workflows default to `shadow`; the registry is metadata and does not by itself prove a deployed end-to-end workflow. |
| Executable shadow trace references | implemented | `services/core-control-plane/tests/agents/test_wave7_workflows.py`; `services/core-control-plane/tests/composition/test_readiness_service.py`; `services/core-control-plane/tests/core/test_control_loop_operator_request.py`; `services/core-control-plane/tests/agents/test_detection_readiness.py` | Focused tests cover the registered trace paths. They are implementation evidence, not retained operational traces. |
| Published workflow sequence diagrams | validated | `docs/diagrams/fdai-agent-workflows-*.diagram.yaml`; `tools/architecture-diagrams/test/agent-workflows.test.ts`; exact-SHA CI and Pages runs; live bilingual geometry checks | All twelve published diagrams show complete sender and receiver names plus the typed message in centered bilingual cards. This presentation adds no direct call, workflow state, authority, or promotion evidence. |
| Machine-readable workflow catalog | in-progress | `rule-catalog/workflows/`; `docs/roadmap/decisioning/process-automation.md` | The executable catalog is intentionally narrower than this design inventory and is not a one-file-per-section projection. |
| Measured promotion gates | not-started | Promotion thresholds in this document and `services/core-control-plane/src/fdai/agents/_framework/workflows.py` | No retained evidence demonstrates the required shadow durations, KPI baselines, or per-workflow gate results. |
| Enforce-mode promotion | not-started | `default_mode="shadow"` in `services/core-control-plane/src/fdai/agents/_framework/workflows.py` | Promotion remains independent per workflow; retrospective what-if is inherently shadow and is not eligible for enforcement. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-20 | validated | Retained exact-source CI, Pages deployment, and live bilingual geometry evidence for the corrected workflow diagrams. Every one of the 24 deployed SVGs exposes a message body for every node, centers the sequence with zero delta, and has zero text overflow or node overlap; the English and Korean routes also have no page or diagram-host overflow at desktop, constrained-desktop, or mobile widths. | Commit `c22ea624b`; [CI run 32336843459](https://github.com/dotnetpower/fdai/actions/runs/32336843459); [Pages run 32336843527](https://github.com/dotnetpower/fdai/actions/runs/32336843527); live `1440x900`, `993x641`, and `390x844` checks. | None for the published sequence-diagram regression. Runtime promotion evidence remains separately open. |
| 2026-08-20 | implemented | Corrected the published sequence presentation after live review found that every workflow collapsed into a narrow left-aligned actor chain, hid typed messages from the visible cards, and truncated return-arrow senders such as Njord. Sequence cards now expose bounded message bodies, center the ordered chain, and preserve complete participant aliases. | `current change`; twelve bilingual workflow specs and mirrored assets; 95 diagram compiler tests, typecheck, artifact freshness, 35-pair public migration, 10 focused site contracts, and direct EN/KO geometry checks passed with zero text overflow or node overlap. | Retain exact-source Pages deployment evidence before closing the visual regression. Runtime promotion evidence remains separately open. |
| 2026-08-13 | implemented | Adopted the implementation ledger and reconciled the workflow inventory with the metadata registry and focused shadow tests. Earlier implementation provenance was not reconstructed. | current change; focused workflow tests | Complete catalog projection where required, retain operational shadow evidence, and evaluate promotion gates independently. |

### Remaining work

- [ ] Decide which design-inventory workflows require machine-readable catalog entries and preserve the documented non-1:1 boundary.
- [ ] Retain per-workflow shadow-duration, KPI-baseline, policy-escape, and trace evidence from an operating environment.
- [ ] Evaluate and record each eligible workflow's promotion result independently; do not promote retrospective what-if.
