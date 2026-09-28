# Independent Operational Evidence Issuance implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions, and resumable work
while the [design owner](../../roadmap/rules-and-detection/independent-operational-evidence.md) remains
focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Source-specific issuance design for #1022 criterion 1 | implemented | [Design owner](../../roadmap/rules-and-detection/independent-operational-evidence.md) and its Korean pair | Design only; the owner reviewed it on 2026-09-28 and recorded all six review decisions. No executable behavior exists. Accountability stays per boundary with no single steward. |
| Verifier workload, managed identity, and separation checks | not-started | [Verifier workload and identity separation](../../roadmap/rules-and-detection/independent-operational-evidence.md#verifier-workload-and-identity-separation) | No workload, identity, executor-class anchor set, deployment preflight, startup anchor comparison, or own-role readback exists. The Core app still runs as the executor identity. |
| Issuance seam, proof store, rejection records, and operational admission provider | not-started | [Issuance path and proof format](../../roadmap/rules-and-detection/independent-operational-evidence.md#issuance-path-and-proof-format) | `OperationalEvidenceIssuer` and its attempt-scoped `outcome` read, the pinned create-only admission and rejection layout, writer readback, content-classified rotation and revocation, and the binding recheck on `admit` are unimplemented. Existing providers only read retained records. |
| Trust registry, case-scope grant registry, and Operator authentication receipt | not-started | [Trust registry and purpose mapping](../../roadmap/rules-and-detection/independent-operational-evidence.md#trust-registry-and-purpose-mapping); [Principal-to-case-scope and purpose binding](../../roadmap/rules-and-detection/independent-operational-evidence.md#principal-to-case-scope-and-purpose-binding) | No pinned registry, grant schema, review pin, or retained receipt with exact groups, a no-overage flag, and principal kind exists. |
| Class-specific owner outcomes | not-started | [Fail-closed rejection matrix](../../roadmap/rules-and-detection/independent-operational-evidence.md#fail-closed-rejection-matrix) | Owners still hold with generic reasons such as `context_admission_required`. Class-specific hold reasons, the refused-transition audit, a versioned `ForecastOutcome` exclusion, and the Pattern read status are unimplemented. |
| Test-context readback | not-started | [Source-specific design](../../roadmap/rules-and-detection/independent-operational-evidence.md#source-specific-design) | Covers `operator-test-context-command`, `test-context-transition`, `operational-test-context`, and `operational-test-observation`. Consumers exist and fail closed; no proof is issued. |
| Forecast readback | not-started | [Forecast history source slices](../../roadmap/rules-and-detection/independent-operational-evidence.md#forecast-history-source-slices) | Covers the four `forecast-history-*` purposes and `forecast-context`. Raw sources depend on #1021; consumers keep excluding scoring. |
| Case-history read and current-case reuse readback | not-started | [Case-history read](../../roadmap/rules-and-detection/independent-operational-evidence.md#case-history-read); [Current-case reuse](../../roadmap/rules-and-detection/independent-operational-evidence.md#current-case-reuse) | Consumers exist and fail closed; no grant registry or issued proof exists. Bragi remains the accountable caller of the read function. |
| Capability state, contracts, deterministic tests, and connected handoff | not-started | [Local testability and connected handoff](../../roadmap/rules-and-detection/independent-operational-evidence.md#local-testability-and-connected-handoff) | No capability row, contract registration, adapter or transport test, or connected receipt exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-28 | implemented | Recorded the owner's review of the issuance design (#1022 criterion 1): write exclusivity plus immutability, the Operator receipt alone, per-boundary accountability, insert-only PostgreSQL proof tables in both venues, the proposed freshness ceilings, and the five-second history deadline with `unavailable` on overrun. Aligned the proof-store section with PostgreSQL. | `current change`; [owner decision record](https://github.com/dotnetpower/fdai/issues/1022#issuecomment-5863412337) on #1022 | Implement criteria 2-7; no executable behavior exists yet. |
| 2026-09-28 | in-progress | Adopted this ledger for a new owner with the first reviewable source-specific design for independent operational evidence issuance (#1022 criterion 1); there is no earlier history. Before publication, two rounds of independent High-risk critique found 6 Medium and 3 Low issues, and all nine are resolved in this change: attempt-scoped typed rejection records with explicit class-specific owner outcomes; routine rotation kept separate from revocation, which the loader classifies by content, with pin-history lineage and a re-attestation path; exact receipt groups; Bragi as the accountable caller, with per-boundary accountability and the Saga steward proposal withdrawn; all executor-class anchors; and route coverage. Design only: no verifier, proof producer, registry, grant mapping, contract, or test was added, and no consumer behavior or authority changed. | `current change`; `docs/roadmap/rules-and-detection/independent-operational-evidence.md` and its Korean pair; `scripts/lib/design-routes.json` route `operational-evidence-issuance`; changed-path translation, translation-quality, readable-Hangul, roadmap-tracking, design-route, doc-link, punctuation, and document-size checks. | Record the owner's review and the six open decisions, then deliver #1022 criteria 2-7. |

### Remaining work

- [x] #1022 criterion 1: the owner reviewed the
  [design](../../roadmap/rules-and-detection/independent-operational-evidence.md) on 2026-09-28 and recorded a
  decision for each item in [Review decisions](../../roadmap/rules-and-detection/independent-operational-evidence.md#review-decisions),
  with no single steward.
- [ ] #1022 criterion 2: implement the verifier workload, `OperationalEvidenceIssuer` with its `outcome` read,
  the insert-only PostgreSQL admission and rejection tables, the operational admission provider, and the pinned trust
  registry. Focused tests show that an admission exists only after verifier-issued readback, that a forged
  response body admits nothing, that `outcome` accepts only the rejection its own attempt named, and that a
  removal or narrowing retires records without a `revoked` label while routine rotation keeps them.
- [ ] When criterion 2 adds the verifier, issuer, proof store, and registry modules, add their paths to the
  `operational-evidence-issuance` route in `scripts/lib/design-routes.json` with a `docs_update` entry for the
  design owner; `check-design-doc-impact.py` then requires the owner to change with them.
- [ ] #1022 criterion 3: issue all eleven purpose ids from their named authoritative sources with digest-parity
  tests shared with each consumer. Forecast kinds stay `unavailable` until #1021 delivers their raw sources;
  consumer wiring is tracked in the [prediction learning ledger](prediction-learning-and-case-history.md).
- [ ] #1022 criterion 4: add the Operator authentication receipt with exact groups, a no-overage flag, and
  principal kind, plus the pinned case-scope grant registry. Focused tests show that equal digests without an
  explicit grant and a `principal_groups` set that differs from the receipt are both denied.
- [ ] #1022 criterion 5: pass one negative test per rejection class that asserts its recorded class and owner
  reason, a stopped-verifier test that reports only `unavailable`, and a test that finds no token in any proof,
  record, log, metric, error, or response.
- [ ] #1022 criterion 6: pass exact-source adapter, transport, and loopback PostgreSQL writer-separation tests,
  and publish the executable connected handoff; record connected receipts only after separate authorization.
- [ ] #1022 criterion 7: register contracts and capability rows, keep both design languages current, and show
  with pantheon layout tests that no agent, topic, `owns`, `subscribes`, execution, or promotion changed.
