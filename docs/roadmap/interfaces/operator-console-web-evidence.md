---
title: Operator Console Public Web Evidence
---

# Operator Console Public Web Evidence

This Tier B companion owns the operator console's public web search routing, retrieval, alternative
discovery, safety boundaries, and regression coverage.

## Public web evidence

Public web evidence is a deployment-level, read-only capability. It stays unavailable until the
deployment enables `FDAI_WEB_SEARCH_ENABLED` and configures an approved domain allowlist.

- **Eligibility:** An explicit operator request such as `search`, `find`, `look up`, `검색해줘`,
  `찾아봐`, or `구글링해줘` selects public web search without requiring a particular subject noun.
  These high-confidence patterns are the T0 fast path. When T0 returns `none` for an eligible
  open, list, comparison, proposal, or status question, a search-capable model returns strict JSON
  with `web` / `local` / `none`, confidence, reason code, and a normalized query. Low-confidence,
  malformed, or unavailable classification stays `none`. Current-screen, audit, inventory,
  catalog, and sensitive-data boundaries are applied before this semantic fallback.
  A deterministic local inventory intent, including an ASCII resource token followed by a Korean
  particle such as `AKS에` and a database state filter such as `stopped db`, overrides a semantic
  public-web plan unless the operator explicitly requests a web search. The coordinator runs only
  the local tool branch. A scope-only next turn reuses only the latest user inventory question, changes only its server provider scope, preserves typed facets and projection, ignores client tool evidence, and stays unresolved when that latest turn isn't inventory. An AKS application
  deployment question remains partial when only cluster inventory is connected; it lists the
  observed cluster resources and states that Kubernetes workload evidence is missing.
  A deterministic evidence fast path doesn't start the shadow answer-planning round because it
  cannot consume contributor prose. Verification and terminal delivery therefore don't wait for
  an unrelated agent bridge.
  Bragi deterministically keeps a data question on the current screen when that screen carries
  a facts or records projection for the turn, including an explicitly empty projection. The scope
  is selected before behavior, tool, incident, agent, concept, and web resolvers. It suppresses
  specialist delegation, semantic web classification, and shadow contributor planning. If the
  requested field is absent, Bragi reports the absence instead of using
  general model knowledge. The `bragi-screen-t0` renderer answers supported fact, record, latest
  audit, action-summary, and promotion-row questions without a narrator-model call. JSON and SSE
  use the same renderer and verifier.
  On the Incidents route, a prompt that references the one selected incident by title, correlation
  id, or a phrase such as "this incident" uses a direct correlation-filtered read instead of the
  fuzzy recent window. A projection without a lifecycle incident id derives an
  `INC-<correlation>` lookup hint, but only the server result is evidence. The coordinator doesn't
  start unrelated inventory, agent, or public-web branches for that turn. An explicit canonical
  tool command such as `query_inventory` keeps tool authority.
  An agent-addressed turn and a turn with server-owned agent evidence skip speculative semantic
  public-web fallback. An explicit or planned web-search request may add a bounded public-web branch
  alongside the agent branch without changing the selected agent's response ownership.
  When semantic classification does run, progress identifies the selected classifier deployment as
  a route source. Completed replies preserve the generation model, response owner, contributors,
  explicit agent-to-Bragi handoff, verification result, and every recorded evidence reference.
  Unverified evidence remains inspectable with an attention state instead of being hidden.
  An evidence manifest marked incomplete uses the same attention treatment, reports retained versus
  declared manifest sources, and labels the collapsed source summary as partial evidence.
  The browser accepts delegation attribution only for fixed Pantheon names. It limits primary,
  contributor, and handoff identities to 64 characters, contributors to eight entries, trace
  references to 256 characters, and handoff reasons to 128 characters before replay.
  Cross-process failures render an attention-state handoff without false attribution. After the
  initial timeout, bounded background probes recover automatically when the core bridge appears.
- **Retrieval:** An eligible turn routes to a search-capable Azure Responses model candidate. The
  classifier converts multilingual public-search requests into a bounded English query; the search
  provider receives only that query and the domain allowlist, then returns a sanitized evidence
  snapshot. Bragi renders the answer with source URLs; it doesn't invent a replacement when search
  is unavailable. Bragi's answer-generation system prompt is not the search-intent authority.
- **Alternative discovery:** The classifier identifies the comparison subject and two to eight
  capabilities, then the coordinator deterministically rebuilds a capability-based query without
  the subject name. Alternatives use medium search context and request at least three distinct
  direct products so deterministic filtering can retain two. Results exclude self references,
  generic vendor homepages, conceptual
  frameworks or strategy guides, editorial or blog pages, generic documentation indexes, and
  duplicate pages from one product identity. Fewer than two distinct product sources makes the
  search unavailable. Bragi compares only cited capability
  overlap, marks unsupported criteria unknown, and labels the comparison partial rather than
  claiming functional equivalence or a winner.
- **Safety boundary:** Sensitive identifiers block retrieval before any provider call. Web snippets
  remain untrusted data, can't grant execution eligibility, and don't satisfy rule-catalog evidence
  requirements for an action.
- **Regression rubric:** A frozen 10-case English and Korean corpus checks explicit, colloquial,
  freshness, web-context, local-scope, and no-search intents. Each case passes only when both the
  structured route and provider-call behavior match the expected result. A separate live held-out
  check measures semantic classification and query normalization with English, Spanish, French,
  and Japanese prompts that aren't present in the T0 pattern set.
  Alternative discovery adds ten observable relevance checks for goal, subject, capabilities,
  candidate count and diversity, self exclusion, direct pages, and conceptual-content exclusion.

No dedicated frozen-corpus artifact path or focused command is identified in the current document
or test tree. The rubric remains the acceptance contract until those cases are materialized as a
reviewable versioned fixture and focused suite.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Core web-search policy, provider seam, and sanitizer | implemented | `services/core-control-plane/src/fdai/core/web_search/`; `services/core-control-plane/tests/core/web_search/` | Focused tests cover allowlists, sensitive-input denial, bounded evidence, sanitization, and no execution authority. |
| Operator classifier, resolver, and Azure adapter paths | in-progress | `services/operator-service/src/fdai_operator_service/application/conversation/capabilities/web_search/`; `services/operator-service/src/fdai_operator_service/adapters/conversation/web_search/` | Production paths exist, but this owner document does not cite a bounded focused suite for the complete eligibility, alternative-discovery, and provider-call contract. |
| Local-evidence precedence and current-screen fast paths | implemented | Operator conversation application and Console answerer; focused conversation and Console tests | Deterministic screen and local-tool precedence exist and prevent speculative public-web fallback from replacing authoritative local evidence. |
| Frozen English and Korean regression corpus | not-started | [Regression rubric](#public-web-evidence) | The ten-case acceptance shape is documented, but no dedicated versioned corpus artifact or focused command was found. |
| Held-out multilingual and live provider evidence | not-started | [Regression rubric](#public-web-evidence) | No governed English, Spanish, French, and Japanese held-out receipt or alternative-discovery relevance artifact is retained. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger and clarified that the frozen regression corpus is not yet materialized; earlier provenance was not reconstructed. | `current change`; current Core and Operator web-search paths and focused checks listed in the scope table. | Materialize the corpus, close focused orchestration coverage, and retain governed live evidence. |

### Remaining work

- [ ] Materialize a versioned English and Korean ten-case route and provider-call corpus with explicit local, web, none, sensitive, current-screen, and alternative-discovery expectations.
- [ ] Add a focused Operator suite that proves eligibility ordering, exact local precedence, classifier bounds, normalized query, provider-call suppression, candidate diversity, and partial comparison rendering.
- [ ] Retain a governed held-out multilingual receipt and alternative-discovery relevance artifact with exact model, policy, allowlist, source, and revision provenance.
- [ ] Retain local and deployed failure, failover, unavailable, sanitization, citation, and no-authority receipts before claiming runtime validation.
