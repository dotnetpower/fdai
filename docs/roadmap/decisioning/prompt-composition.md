---
title: Evolving System Prompt
---
# Evolving System Prompt

The T2 tier and quality gate consume a **composable, catalog-as-code prompt**
instead of a single hardcoded string. This document is the design source of
truth: how the layers assemble, where each artifact lives, which seams the
composition root wires, and how we measure that the model actually reads what
we sent. It expands the LLM contract in
[llm-strategy.md](../architecture/llm-strategy.md#t2---reasoning-tier-quality-gate-required) and
the trust routing in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

> **Scope.** Upstream is generic and Azure-first. Web search is deployment opt-in
> through the reviewed Azure Responses adapter; customer-specific overrides remain
> fork-only. Core still ships deny-by-default fakes
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
>
## Adaptive conversation assembly

The adaptive conversation uses one catalog-owned `adaptive-common` base and exactly one plan,
answer, review, refine, or verify pack. A turn adds one fixed Pantheon role and locale; user and
tool prose remain in the untrusted data envelope. The server resolves the explicitly selected
agent independently of the optional stewardship relationship. Operator verifies current ownership
and directory evidence, binds an expiring proof to principal and target, and Core rechecks it before
each role-aware conversation. Identity identifiers and source-revision text never enter system text.
Unknown or expired relationships retain the selected role without pretending to be verified.

Production composition consumes resolved model slots rather than hardcoded models or endpoints.
The five `conversation.adaptive.*` keys are prompt-only bindings: plan and answer use the first
configured T1 narrator, review and verify use an independent configured T1 narrator, and only
optional refinement uses `t2.reasoner.primary`. Exact deployment metadata supplies publisher and
family; names never imply model identity. Held or unknown candidates are excluded.
They do not create model deployments. Role and lifecycle types use the public agent and model facades.
The author and reviewer must be independent configured models; one optional refinement re-enters
independent review. The no-T2 request profile retains the existing non-adaptive path. Every stage
preserves the same no-execution boundary. Schema, byte, time, call, and token budgets are enforced;
optional reads reserve time and two calls for a useful answer and review. Nested query-model
requests share the same turn budget and cancellation scope. The role profile and model traces remain
separate from operational evidence and cannot produce a whole-answer verification badge.

Critique and revision: making a T2 secondary a prerequisite disabled ordinary explanations in
single-publisher local installations and sent knowledge questions into operational query planning.
T1 authorship and independent T1 review therefore stay available when all T2 bindings are absent.
A missing or non-independent escalation target disables refinement only. Provider-side structured
output is used when configured; otherwise the exact schema accompanies the request and the
application validates returned JSON against it. This does not relax evidence verification or the
separate mixed-publisher operational T2 quality gate.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Adaptive role and relationship prompt assembly | implemented | `adaptive_prompt.py`; `wire_adaptive_conversation.py`; `adaptive_relationship.py`; 20 composition checks and connected role/proof checks passed | Uses one common stage policy, fixed selected role, and current no-authority relationship context. Final offline validation and 11 focused critique reviews are recorded with hierarchical conversation planning. |
| Catalog registry, composer, tools, and runtime skills | implemented | [`test_composer.py`](../../../services/core-control-plane/tests/core/prompts/test_composer.py) | Catalog loading, deterministic layer assembly, tool manifests, skills, canaries, and startup fallback have focused coverage. |
| Route-specific conversation prompts | implemented | `conversation-preflight.v1.yaml`; `semantic-judgment.v5.yaml`; focused composer and Azure adapter checks | Startup composes a compact T1 preflight separately from full operational semantic judgment. Pure eligible social turns use only the compact prompt and schema. Mixed, contextual, ambiguous, and operational turns continue to the full capability-aware prompt. |
| Approved external skill-source fetch | implemented | [`skill_source.py`](../../../services/core-control-plane/src/fdai/delivery/github/skill_source.py); [`test_skill_source.py`](../../../services/core-control-plane/tests/delivery/github/test_skill_source.py) | The GitHub delivery adapter resolves immutable commits and returns only bounded exact files. Fetch never grants prompt eligibility; quarantine, publisher verification, approval, and disabled-first installation remain authoritative. |
| Operator memory, debate, and QualityGate integration | implemented | [`test_prompt_deliberation.py`](../../../services/core-control-plane/tests/agents/test_prompt_deliberation.py), [`test_gate.py`](../../../services/core-control-plane/tests/core/quality_gate/test_gate.py) | Bounded memory and one-round Critic/Judge debate feed the deterministic verifier without granting authority. |
| Answer continuity and prompt ablation | implemented | `services/core-control-plane/src/fdai/core/prompts/`; `services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py`; `services/operator-service/src/fdai_operator_service/postgres_iam.py`; 312 focused Python checks and 6 Console checks | An audited runtime toggle, protected prompt-layer ablation, replay evidence, useful safe-hold rendering, and revision-fenced Operator persistence are implemented. Governed shadow evidence remains open before runtime validation. |
| Reviewed web search and core T2 prompt integration | in-progress | [`test_web_search.py`](../../../services/core-control-plane/tests/core/web_search/test_web_search.py), [Wave 5 alpha](#wave-5-alpha---what-shipped) | The safe provider seam and reviewed adapter exist, but snippets are not threaded into the core T2 tool manifest. |
| Fork-first second-approval channel | in-progress | [`hil_pipeline.py`](../../../services/core-control-plane/src/fdai/core/operator_memory/hil_pipeline.py), [`test_hil_pipeline.py`](../../../services/core-control-plane/tests/core/operator_memory/test_hil_pipeline.py) | The upstream domain step now proves distinct-principal, no-self-approval, a bounded approval window, and replay: a redelivered approval refuses with `already_materialized` instead of planting a second entry, and an unprovable or expired window never materializes. The channel that invokes it stays fork-first and unbuilt, so the pipeline slice remains disabled. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-06 | implemented | Removed the mandatory T2 reviewer from ordinary adaptive composition. Distinct configured T1 narrator models author and review; only an optional T2 primary refines, and malformed or unavailable escalation does not disable T1. Unbound provider schema support uses application-side JSON validation. | `current change`; 115 focused composition, transport, schema, budget, runtime, and prompt-registry tests passed; strict mypy passed for both modified source modules. The comparison regression exercises real composition and transport with mocked models and no operational query. | Retain an explicitly authorized live-question receipt before claiming actual answer quality. Strict no-T2 campaign behavior and operational quality gates are unchanged. |
| 2026-09-06 | implemented | Completed fixed-role and relationship composition with independently reviewed answers and provider-budget propagation. Operational catalog failure no longer disables an independently valid general-answer service. | `current change`; 20 composition checks and 653 connected Python checks passed; 11 focused critique reviews are recorded in hierarchical conversation planning. | Live model quality and promotion evidence require separate authorization. |
| 2026-09-06 | in-progress | Added common adaptive stage policy, fixed-role composition, expiring relationship context, and nested provider budget propagation. | `current change`; `test_wire_adaptive_conversation.py` passed 19 cases and `test_adaptive_provider_budget.py` passed 10 cases. | Finish connected critique evidence in hierarchical conversation planning; no live promotion is claimed. |
| 2026-09-02 | implemented | Added the answer-continuity and prompt-ablation slice. The implementation separates guaranteed terminal usefulness from factual verification, protects authority-bearing prompt layers from ablation, makes exclusions replay-visible, and applies revision-fenced settings through one startup snapshot. Ten critique and hardening rounds closed four Medium and five Low defects; the final round found nothing above Low. | `current change`; 312 focused Python checks, 6 Console checks, task-scoped Ruff, strict mypy over 18 source files, and documentation gates passed. | Retain governed shadow evidence before claiming runtime validation. |
| 2026-08-29 | implemented | Hardening round 8 reviewed 23 conversation-preflight lenses and moved social profile bounding inside the safe fallback boundary. Oversized profiles now hold before any narrator call instead of raising through the turn. | `current change`; focused conversation preflight tests. | Retain governed live social-response evidence. |
| 2026-08-28 | implemented | Split temperature-zero social classification, temperature-0.3 persona narration, and full operational semantic judgment into separate composed prompt capabilities. Social narration now combines one common base with exactly one typed enforce pack for greeting, thanks, farewell, or self-introduction. The classifier and narrator receive no ontology capability catalog, the narrator receives no operational context, and only its schema can carry social prose. | `current change`; focused prompt, adapter, routing, and processor checks passed 608 cases; authenticated self-introduction variants used roughly 1.7K-1.9K total tokens across two calls versus the earlier 5,819-token full social input. Composition checks prove act packs remain mutually exclusive. | Retain authenticated per-pack waterfall evidence and measure collision, appropriateness, and latency on a larger bilingual corpus. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected the former fully-live T2 claim. | `current change`; current source and focused tests listed in the scope table. | Complete core T2 web grounding, second approval, and governed runtime evidence. |
| 2026-08-14 | implemented | Added the bounded GitHub skill-source delivery adapter without changing quarantine, approval, or runtime prompt eligibility. | `current change`; concrete adapter and focused rejection-path tests listed in the scope table. | Compose the scheduled source owner and retain governed refresh, approval, and revocation evidence. |
| 2026-08-14 | implemented | Hardened external source delivery with strict ETag validation and redacted credential-provider failures while preserving quarantine and disabled-first prompt eligibility. | `current change`; focused skill-source adapter tests `28 passed`. | Scheduled composition and governed lifecycle evidence remain open. |
| 2026-08-14 | in-progress | Added the upstream second-approval evidence the fork-first channel depends on: a bounded approval window, a replay-safe entry identity derived from the approval, and exhaustive no-self-approval coverage. | `current change`; [`hil_pipeline.py`](../../../services/core-control-plane/src/fdai/core/operator_memory/hil_pipeline.py), [`test_hil_pipeline.py`](../../../services/core-control-plane/tests/core/operator_memory/test_hil_pipeline.py); focused operator-memory and bridge checks passed 76 cases; strict mypy and task-scoped Ruff passed. | Build the fork-first channel that invokes the materializer, then enable the pipeline slice. |

### Remaining work

- [ ] Thread sanitized, allowlisted web snippets into the core T2 tool manifest with exact source
  receipts, prompt digest replay, and negative injection tests.
- [x] The upstream second-approval step proves distinct-principal, no-self-approval, a bounded
  approval window, and replay: a redelivery refuses with `already_materialized` and materializes
  exactly once.
- [ ] Build the fork-first channel that invokes the second-approval step, then enable that pipeline
  slice.
- [ ] Retain a governed end-to-end T2 receipt proving the composed prompt, debate, citations, final
  verifier result, and zero execution authority on one pinned catalog revision.
- [ ] Retain a governed answer-continuity shadow campaign that ablates each eligible prompt layer,
  records the exact active and excluded layer manifests, keeps unsupported operational claims at
  zero, and demonstrates a measured usefulness gain over strict held responses.

## Design at a glance

Prompts are **data**, not literals in code. The composition root loads them
from `rule-catalog/prompts/` at startup, indexes them by capability, and hands
resolved bodies to the Azure OpenAI adapters. Runtime layers (rule-catalog
citations, operator-memory entries, tool outputs, web snippets, debate
transcripts) are wrapped in `trusted="false"` XML tags so the model treats
them as data. The **deterministic verifier remains the sole execution
authority** - every added role, tool, and layer produces material for that
verifier, never a shortcut around it.

Conversation routing composes two separate prompt capabilities. The compact
`conversation.preflight` prompt identifies pure social, mixed, operational, and
context-dependent turns before the capability manifest is loaded. Only an eligible fresh social
turn can terminate there. Every other result invokes the full `semantic.judgment` prompt, so
prompt reduction never bypasses operational grounding.

## Role x layer matrix

Prompts have two axes. **Layers** are what content types compose an assembled
prompt; **roles** decide which base / pack / tool set applies. The catalog now
ships reviewer, Proposer, Critic, Judge, and Rubric base prompts.

| Layer \\ Role | Proposer | Critic | Judge |
|--------------|----------|--------|-------|
| Base (role skeleton) | `base/t2-proposer.v1.yaml` | `base/t2-critic.v1.yaml` | `base/t2-judge.v1.yaml` |
| Task Skill Pack | `packs/<capability>.proposer.vN.yaml` | `packs/<capability>.critic.vN.yaml` | (usually shared with proposer pack) |
| Tool Manifest | tools + optional `web.search` | tools (read-only) | none (Judge cannot call tools) |
| Domain Context (RAG) | rule / past-incident citations | same | same |
| Web Snippets | if Proposer fetched them | read-only | read-only |
| Operator Memory | scope-bounded | scope-bounded | scope-bounded |
| Debate Transcript | (empty on first turn) | Proposer output | Proposer + Critic outputs |

The two-model reviewer remains the default T2 path. The routed Proposer / Critic /
Judge debate runs only on configured disagreements.

A fourth role, the **Rubric** judge, reuses the Base layer
(`base/t2-rubric.vN.yaml`) and the Domain Context layer; it scores the
Proposer's reasoning against fixed criteria and cannot call tools. It is a
subtractive hallucination filter, not an authority - see
[hallucination-rubric-gate.md](hallucination-rubric-gate.md).

## Layer catalog

Each layer has a fixed job and a fixed storage tier.

- **Base** - short, immutable role skeleton (output contract, verifier-as-authority
  reminder, JSON-only output rule). Wave 1 target: <= 128 tokens.
- **Task Skill Pack** - capability-scoped instructions (e.g. RCA grounding,
  action proposal, novelty classification). Each pack cites the rule-catalog
  entries a capability may reference.
- **Tool Manifest** - the subset of tools this role may call. Declaring them
  outside the base prompt keeps the base short and cache-friendly.
- **Domain Context (RAG)** - rule excerpts and prior-incident references
  selected per event. Never persisted alongside the prompt; the audit records
  the cited ids and vector-hit scores only.
- **Web Snippets** - fetched only under the [Web search policy](#web-search-policy).
  Wrapped in `<web_snippet trusted="false" url="..." hash="...">...</web_snippet>`.
- **Operator Memory** - scope-bounded, HIL-approved notes from operator
  feedback (HIL rejects, override justifications, ChatOps preferences, PR
  reviews). Never global; see [Operator memory pipeline](#operator-memory-pipeline).
- **Debate Transcript** - previous roles' outputs, threaded to later roles as
  read-only context.

## Storage

### Catalog-as-code (git-tracked)

```text
rule-catalog/
  prompts/
    schema/
      prompt.schema.json          # JSON Schema every artifact validates against
    base/
      t2-cross-check.v1.yaml      # Wave 1 (shipped)
      t2-proposer.v1.yaml         # Wave 3 (shipped, shadow)
      t2-critic.v1.yaml           # shipped, shadow
      t2-judge.v1.yaml            # shipped, shadow
      t2-rubric.v1.yaml           # rubric hallucination filter (shipped, shadow)
    packs/                        # Wave 2+
    tools/                        # Wave 2.5+
```

### Runtime data (Postgres, hash-addressed blobs)

  This is the target persistence model. `operator_memory` is shipped; dedicated
  `agent_transcript` and `web_evidence` tables remain planned. The Operator API currently
  attaches sanitized web evidence to the durable conversation turn.

```sql
CREATE TABLE operator_memory (
  id            uuid PRIMARY KEY,
  scope_kind    text NOT NULL,     -- 'resource-group' | 'resource' | 'vertical'
  scope_ref     text NOT NULL,
  category      text NOT NULL,
  body          text NOT NULL,     -- wrapped in <operator_note> at inject time
  source_event  text NOT NULL,     -- 'hil.reject' | 'override.create' | ...
  source_ref    text NOT NULL,     -- audit id / PR url / message id
  author        text NOT NULL,
  approved_by   text NOT NULL,     -- no self-approval
  created_at    timestamptz NOT NULL,
  superseded_by uuid,
  ttl           interval
);

CREATE TABLE agent_transcript (
  id             uuid PRIMARY KEY,
  event_id       text NOT NULL,
  round          smallint NOT NULL,
  role           text NOT NULL,    -- 'proposer' | 'critic' | 'judge'
  model_id       text NOT NULL,
  prompt_hash    text NOT NULL,
  layer_manifest jsonb NOT NULL,   -- ordered layer refs + version + token count
  tool_calls     jsonb NOT NULL,
  response_hash  text NOT NULL,
  cost_usd       numeric NOT NULL,
  latency_ms     integer NOT NULL,
  created_at     timestamptz NOT NULL
);

CREATE TABLE web_evidence (
  content_hash    text PRIMARY KEY,
  url             text NOT NULL,
  fetched_at      timestamptz NOT NULL,
  intent          text NOT NULL,
  sanitized_text  text NOT NULL,
  injection_flags jsonb NOT NULL
);
```

Global-scope operator memory is rejected at write time - the row would be
too broad for the [Human Override](../../../.github/instructions/architecture.instructions.md#human-override)
policy this inherits.

## Provider protocols (DI seams)

The core stays behind Protocols; the Azure adapter provides one implementation
per seam. Current and planned seams in this design are:

| Seam | Kind | Wave | Role |
|------|------|------|------|
| `PromptRegistry` | sync | 1 (shipped) | Load / index prompt YAMLs |
| `PromptComposer` | async | 2 | Assemble Role x Layer per event |
| `ToolRegistry` | sync | 2.5 | Load tool YAML manifests |
| `ToolExecutor` | async | 2.5 | Dispatch model-issued tool calls |
| `ProgrammaticPipelineRunner` | async | bounded pipeline | Run reviewed tool loops in an isolated venue |
| `OperatorMemoryStore` | async | 3 | Read / append scope-bounded notes |
| `WebSearchProvider` | async | 5 | Outbound HTTP behind allowlist |
| `EvidenceStore` | async | 5 (planned) | Persist hash-addressed web snapshots |
| `AgentTranscriptStore` | async | 4.5 (planned) | Append-only debate rows |
| `DebateOrchestrator` | async | 4.5 | Proposer -> Critic -> Judge loop |

I/O-bound seams follow the async-by-default rule for provider protocols
declared in
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety).

## Tool use subsystem

Tools are catalog-as-code, mirroring the rule catalog. Each YAML declares its
description, invocation schema, capability gate, allowlist, and output wrapper.

- **Capability and budget**: `llm-registry` selects a short Proposer/Critic allowlist, and each
  tool's `cost_budget_usd_per_call` contributes to the per-event ceiling.
- **Untrusted output**: `<tool_result trusted="false" ...>` remains data for verifier and policy
  re-check; the Judge receives no tools so it cannot collapse into a second Proposer.
- **Programmatic loops**: reviewed read/filter/aggregate Python can call a bounded subset through a
  generated client after digest, sandbox, run-capability, byte/call-limit, and receipt checks. It
  receives no provider credential or recursive/mutation authority. See
  [Programmatic Tool Pipelines](../interfaces/programmatic-tool-pipelines.md).

### Reviewed runtime skills

Runtime skills are portable Markdown instructions that teach an agent how to use already registered tools. They are separate from repository coding-agent skills and grant no tool, identity, role, or execution authority. FDAI Console displays `Installed`, `Enabled`, and `Eligible to load` as load-readiness states and marks authority promotion as not applicable.
Capability declarations separately show the deterministic operator request path; mutation declarations link to measured ActionType promotion evidence instead of inferring promotion from skill eligibility or catalog presence.

- **Three stages:** the bounded index contains metadata only; `load_skill` returns one complete selected `SKILL.md`; `read_skill_reference` returns one declared support artifact. `list_skills` and `describe_skill` are also Reader operations and never change lifecycle.
- **Signed artifact manifest:** YAML front matter covers identity, version, provenance, body digest, required tools, allowed agents, and content-addressed references. Unsafe paths, undeclared or partial files, symlink-shaped metadata, digest mismatch, and configured budget overflow fail closed.
- **Eligibility and replay:** every load rechecks enabled state, tool availability, agent allowlist, stored bytes, publisher signature, and reference digests. Prompt replay records operation, skill
  name, version, body/raw digests, reference digest, selected/rejected status, and rejection reason.
- **Progressive prompt:** the index precedes selected bodies and references. A body is trusted reviewed instruction only after verification; a reference stays untrusted data. Existing
  reference-free single-file skills stay unchanged. Explicit multi-skill composition is owned by [Governed Skill Bundles](governed-skill-bundles.md).
- **Measured benchmark:** a frozen 16-skill catalog across network incident, cost spike, and deployment failure scenarios reduced the full projection from 8194 estimated tokens to 1544-1546 with one selected complete body, a measured 81.1-81.2% reduction.
- **No dynamic code:** runtime skills cannot install binaries, inject environment secrets, load a
  provider, or bypass the tool catalog and risk gate.
- **Audited proposal workshop:** `SkillWorkshop` validates an agent draft and stores it as inert
  content-addressed data. An injected human authorizer must approve or reject with a reason; the
  proposer cannot self-review. Every transition is sent to an append-only audit sink without
  embedding the Markdown body. PostgreSQL persistence survives restart and applies review and
  materialization with expected-state compare-and-swap. Promotion re-runs digest and publisher
  trust verification, then installs the approved artifact disabled without changing an active prompt.
- **Approved source refresh:** registered GitHub sources resolve immutable commits with ETag state,
  fetch only declared files, and persist exact bytes in quarantine. Passing content becomes a
  disabled candidate. Approver installation remains disabled-first, and Owner revocation disables
  the source and durable artifacts without deleting provenance. The concrete delivery adapter
  rejects redirects, path substitution, symlinks, malformed or oversized content, authentication
  failure, and rate limits before quarantine receives any bytes. See
  [Skill Source Management](../interfaces/skill-source-management.md).

### Operator-memory review and compaction

The operator-memory store exposes a bounded review projection that includes active, expired, and
superseded entries with scope, source event/reference, author, distinct approver, TTL-derived
expiry, and supersession pointer. The Settings > Operator memory console view is GET-only. Changes
still enter through approved HIL or ChatOps workflows.

`MemoryCompactionService` can propose a shorter entry only from two or more active, unique source
entries that share scope and category and carry provenance refs. Candidate text passes injection
screening and remains inert until a distinct authorized reviewer approves it. PostgreSQL promotion
atomically appends the compacted entry, preserves source ids/refs, and supersedes the originals.
Rollback restores the original source entries and marks the compacted entry inactive without
deleting any body. Compaction grants no role, tool, action, or execution authority.

## Web search policy

Web search is the last-resort tool. It is opt-in per deployment and never a
grounding source.

- **Default off**: upstream ships a no-op `WebSearchProvider`. Set
  `FDAI_WEB_SEARCH_ENABLED=true` and provide a curated domain allowlist to
  activate the Azure Responses adapter. Production reuses the Operator API's
  managed identity; no search API key is added to the conversation surface.
- **When it may run**: T2 case, novelty score above threshold, capability's
  tool allowlist includes `web.search`, and the per-event query / cost budget
  is not exhausted. This decision is not prose - it is the pure, deterministic
  [`decide_web_search`](../../../services/core-control-plane/src/fdai/core/web_search/policy.py) policy
  (a `WebSearchPolicyConfig` + `WebSearchSignals` -> `SEARCH` / `SKIP`),
  mirroring `escalation_ladder`. It evaluates deny-first gates (disabled ->
  no provider -> capability not allowlisted -> not reasoning-tier -> query
  budget -> cost budget -> grounding-gap required -> novelty threshold) and
  records the SKIP reason in the audit log, so "when web search runs" is
  answered by a test, not a paragraph.
- **Domain allowlist**: primary sources only (vendor docs, RFCs, NVD, CVE registries). An allowlisted domain includes its DNS subdomains, while label-boundary checks reject suffix-confusion hosts. Blogs, forums, and social media are not supported.
- **Snippet handling**: HTML stripped; prompt-like patterns
  (`ignore previous`, `system:`, etc.) detected and flagged; content wrapped in
  `<web_snippet trusted="false">...</web_snippet>` before injection.
- **Not a grounding source**: `cited_rule_ids` MUST still resolve to
  rule-catalog entries. Useful web findings feed the rule-catalog discovery
  loop; they never satisfy the current event's grounding requirement.
- **Replay determinism**: results are stored by `(content_hash, url, fetched_at)`
  in `web_evidence`; audit entries reference the hash. Replay reads the
  stored snapshot instead of re-fetching, so past runs stay reproducible.
- **Controlled Azure Responses adapter**: the Azure-first implementation wraps managed
  `web_search` behind `WebSearchProvider`. Direct Responses sends `allowed_domains` on every request;
  the optional Foundry prompt-agent route uses the exact deployment allowlist and refuses runtime
  drift. Both verify `web_search_call`, reject off-allowlist citations, and store the sanitized
  evidence snapshot with the durable conversation turn. Only the bounded
  operator query leaves FDAI; the screen snapshot and conversation history are
  never sent to the search call. Provider failures become bounded reason codes such as `tool_blocked`,
  `provider_unauthorized`, or `provider_rate_limited`; raw response bodies never enter the conversation. Organization-wide and authorization failures stop model failover, while transient failures can try the next deployment.
- **Latency-routed model pool**: search candidates come from
  the dedicated `t1.web_search` registry capability and serialize as
  `web_search_candidates`; narrator candidates are never a fallback. Startup sends one actual
  managed-tool search per candidate and excludes failures before serving. Periodic model-only probes
  then update latency without search charges. Calls choose the lowest rolling p50 and fail
  over on errors; the selected deployment, p50/p95 history, and actual search
  latency are returned as provenance. The probe does not invoke web search, so
  periodic health measurement does not incur search-tool charges.
- **External data boundary**: Azure `web_search` uses Grounding with Bing. The
  Microsoft Data Protection Addendum does not apply to that transfer, and data
  can leave the deployment's compliance and geography boundary. This is why
  activation is explicit, domains are allowlisted, and GUIDs, Azure resource
  IDs, email addresses, and private IP addresses are blocked before a query is
  sent.

## Debate orchestrator (Proposer / Critic / Judge)

Debate runs only when the router asks for it - typically high-severity, high
novelty, or explicit operator-memory guidance. The default T2 path is still
the two-model cross-check documented in [llm-strategy.md](../architecture/llm-strategy.md).

```text
Proposer  -- candidate + citations + confidence
   |
   v
Critic    -- objections: [{severity, cited_rule_id, alt_action?}]
   |
   v
Judge     -- decision in {accept, revise_and_retry (<=1), escalate_hil}
   |
   +--> accept       -> deterministic verifier -> risk gate
   +--> revise       -> Proposer 1 retry (total rounds <= 2)
   +--> escalate_hil -> stop
```

Hard limits per event: `debate.max_rounds <= 2`, `debate.max_wall_seconds`,
`debate.max_cost_usd`. Any overrun aborts to HIL. The Critic MUST be a
different-publisher model from the Proposer (extension of the mixed-model
distinctness rule in
[llm-strategy.md](../architecture/llm-strategy.md#t2---reasoning-tier-quality-gate-required)).
The Judge may be a smaller / cheaper model.

Critic's role is not "another opinion"; it is a checklist against the seven safeguards
(stop-condition, rollback, blast-radius, dry-run, lock, idempotency, audit-log) plus
citation validity and contradiction against operator memory.

## Operator memory pipeline

Operator feedback becomes memory in a two-step gate:

```text
HIL reject / approve reason ------\\
Override create / modify event   --+--> operator-memory candidate
ChatOps preference message       --|         |
PR review comment on rem PR      --/         v
                                     HIL second approval (no self-approval)
                                             |
                                             v
                                  operator_memory row (append-only)
```

- **Scope MUST be resource-group or narrower.** Broader scope becomes a rule
  change, not an override, and flows through the catalog pipeline.
- **Sanitize + wrap on inject**: memory bodies enter the prompt inside
  `<operator_note author="..." scope="..." trusted="false">...</operator_note>`
  tags, and the base prompt forbids following instructions inside those tags.
- **Discovery signal**: long-lived overrides or many similar memory rows for
  the same rule feed the rule-catalog discovery loop as candidate revisions or
  retirements.

> Working-context selection is separately owned by [Context Selection Policy](context-selection-policy.md):
> immutable `deterministic-tiered-v1@1.0.0`, mandatory validation, shadow evidence, replay, and rollback.

## Recognition measurement

Long prompts silently drop instructions. We treat "the model actually reads
what we sent" as a first-class KPI, gated before promoting a prompt to enforce.

- **Hard token budget** - the composer estimates tokens per assembled prompt.
  Overrun aborts to HIL and increments `prompt.token_budget.exceeded_rate`.
  Lower-priority layers (oldest operator memory first) are dropped explicitly
  with an audit-visible reason.
- **Canary tokens** - the composer inserts tagged layer markers
  (`<layer id="pack.rca.v3">...</layer>`). Roles report which layers they
  acknowledged; unacknowledged high-priority layers surface as a defect.
- **Adherence rate** - JSON schema violations, missing required fields, and
  citation-rule-id validity are measured on a frozen scenario set every
  prompt-version bump.
- **Position sensitivity** - controlled fixtures place the same instruction at
  base vs. pack vs. end and compare adherence. Consistent dips at a position
  signal a base rewrite.
- **Mixed-model agreement rate** - existing quality-gate disagreement rate is
  tracked per prompt version so regressions surface immediately.
- **Debate economics** - `debate.rounds.p95`, `debate.cost_usd.p95`,
  `debate.timeout_to_hil_rate`, and `critic.reversal_rate` are tracked once
  the debate orchestrator lands.

Promotion gates (initial values, tuned per capability): `adherence >= 0.95`,
`citation_f1 >= 0.9`, `web.grounding_leak == 0`, `debate.timeout_to_hil_rate
<= 5%`, `critic.reversal_rate in [1%, 15%]`.

## Answer continuity and prompt ablation

Answer continuity is a configurable presentation policy for accepted conversational turns. It does
not promise a correct diagnosis. When a verified answer is unavailable, it returns a useful safe
hold that names the bounded failure, separates confirmed facts from unknowns, lists the exact
missing evidence, and suggests only registered read or simulation capabilities.

The flow remains `T0 -> T1 -> verification -> bounded T2 -> deterministic verification`. Enabling
continuity never skips a tier, changes a score, treats a retrieval rank as confidence, or grants
execution authority. A low-quality T2 result can improve the explanation of the hold, but it cannot
turn an unsupported claim into an answer.

### Runtime policy

The revisioned runtime settings surface owns two independent controls:

- `conversation.answer_continuity.enabled` enables useful safe-hold rendering after restart. The
  default is `false`.
- `conversation.prompt_ablation.profile` selects one reviewed evaluation profile. `none` is the
  production default. Other profiles can remove task packs, tool manifests, operator memory,
  runtime skills, or all optional context.

The deployment setting is a ceiling. Request text, model output, an experiment, or a user preference
cannot enable a profile that the runtime policy did not select. Every update uses the existing
revision check and append-only settings audit.

### Protected and eligible layers

| Class | Layers | Ablation behavior |
|-------|--------|-------------------|
| Protected | base role, Critic, Judge, rubric, role header | Never removable. Startup or composition fails closed if a profile targets one. |
| Eligible | task pack, tool manifest, operator memory, skill index/body/reference/bundle | Removable only by a reviewed profile. The composer avoids reading an ablated store or catalog and records each excluded layer or artifact. |
| External authority | tool call-site policy, RBAC, verifier, risk gate, approval, executor | Outside the prompt and never ablatable. Manifest omission is not an authorization control. |

Each `ComposedPrompt` and `PromptReplayManifest` carries an ablation profile plus ordered excluded
layer references. Canaries are injected only after exclusions, so recognition metrics cannot count a
removed layer as unread. An ablated tool manifest does not change the executor's deny-by-default
classification.

### Useful safe hold

With answer continuity enabled, `held` and `unsupported` turns still preserve their canonical
disposition and reason code. Only the localized answer changes. It includes:

1. the strongest supported status;
2. the exact bounded reason code;
3. a statement that no operational change was authorized;
4. a safe next step that asks for missing scope or points to registered read-only investigation;
5. a low-confidence notice when semantic or model evidence was incomplete.

No deterministic fact means no hypothesis. The response remains a hold, and the Console continues
to show `verification.status=unverified`.

## Safety invariants (extensions)

The eight invariants in
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety)
extend with ten more as this design lands:

1. Web-search output is NEVER a `cited_rule_id`.
2. Tool results and web snippets are ALWAYS wrapped in `trusted="false"` XML.
3. Debate loops have hard `max_rounds`, `max_wall_seconds`, `max_cost_usd`
   ceilings; any overrun aborts to HIL.
4. Critic and Proposer publishers MUST differ; a same-publisher pair collapses
   into a single voter.
5. Judge MUST NOT call tools; judgment and generation are separated.
6. Web evidence is hash-addressed immutable; replay reads snapshots, never
   re-fetches.
7. Prompt ablation never removes a base role, Critic, Judge, rubric, role header, deterministic
   verifier, RBAC check, or tool call-site policy.
8. Every ablated layer or artifact is present in replay evidence; silent exclusion is not supported.
9. An ablated optional source is not read and cannot leak into model context through another layer.
10. Answer continuity preserves the original terminal disposition and never upgrades an unverified
    response to `answered`.

## Rollout waves

Every wave lands in shadow first; promotion requires the previous wave's
promotion gates to hold.

| Wave | Deliverable | Shipped |
|------|-------------|---------|
| 1 | Externalize base prompt to catalog + `PromptRegistry` + composition wiring | yes |
| 2 | `PromptComposer` async Protocol + `DefaultPromptComposer` (Base + Task Pack) + `ComposedPrompt` / `LayerRef` recognition primitives + required `system_prompt` on `AzureOpenAICrossCheckModelConfig` | yes |
| 2.5-A | Shadow-vs-enforce filter in `DefaultPromptComposer` + shipped shadow-mode task pack + `tool.schema.json` + `FileSystemToolRegistry` | yes |
| 2.5-B step 1 | Composer emits an optional Tool Manifest layer + shipped shadow-mode tool YAMLs (`rule.query` / `state.query` / `audit.query`) with `trusted="false"` wrapper enforcement | yes |
| 2.5-B step 2a | Async `ToolExecutor` + `ToolProvider` seam + `DefaultToolExecutor` with schema validation, shadow guard, wrapper enforcement, and five typed fail-closed errors (`UnknownToolError`, `ShadowToolBlockedError`, `ToolArgumentValidationError`, `MissingProviderError`, `ProviderCallError`) | yes |
| 2.5-B step 2b | `AzureOpenAICrossCheckModel` emits `tools=[...]` for enforce-mode tools, routes model-issued `tool_calls` through the executor in a bounded multi-turn loop, and rejects unknown function names / malformed arguments / half-wired setups fail-closed | yes |
| 3 step A | `core/operator_memory/` types + async `OperatorMemoryStore` Protocol + `InMemoryOperatorMemoryStore` + `wrap_operator_note` / `detect_injection_markers` sanitizer + write-time policy checks (scope <= resource-group, distinct approver, append-only supersede, optional TTL, injection-marker rejection) | yes |
| 3 step B store | `PostgresOperatorMemoryStore` + alembic migration `20260706_0006_operator_memory` (append-only table, CHECK constraints mirroring the Python policy, `(scope_kind, scope_ref)` scope-lookup index, TTL + supersede semantics parity with `InMemoryOperatorMemoryStore`, integration tests skipped when `FDAI_DATABASE_URL` unset) | yes |
| 3 step B pipeline slice 1 | `HilRejectMaterializer` core module that turns a `HilResponse(decision=REJECT, reason=...)` + a distinct `second_approver` into a stored `OperatorMemoryEntry` via the injected `OperatorMemoryStore`; seven pipeline-level error codes (`wrong_decision`, `empty_reason`, `missing_first_approver`, `missing_second_approver`, `same_principal`, `missing_response_time`, `approval_expired`) fail-fast before the store is touched, a redelivery surfaces as `already_materialized`, and other store-side policy errors (injection marker) surface unchanged | yes |
| 3 step B pipeline slice 2 | Composition-root wire: `_build_operator_memory_store()` picks Postgres via `FDAI_OPERATOR_MEMORY_DSN` or the in-memory fake by default, and `_finalize_llm_bindings` hands the store to `DefaultPromptComposer` so the operator-memory layer is fully reachable end-to-end without a database (an entry a fork appends via `HilRejectMaterializer` becomes visible to the composer immediately) | yes |
| 3 step B pipeline slice 3 | Second-approval channel that actually invokes the materializer (Teams Adaptive Card / git PR / fork-authored CLI). Kept fork-first because the approval channel varies per deployment; upstream ships the `HilRejectMaterializer` seam and the operator-memory store, not a specific UI | planned |
| 3 step C-1 | `DefaultPromptComposer` accepts optional `operator_memory_store` + `scope` and emits an operator-memory layer; every entry is wrapped via `wrap_operator_note`, hierarchy resolution places resource-group notes before resource notes | yes |
| 3 step C-2 | `AzureOpenAICrossCheckModel` calls the composer per-event (with an optional fork-supplied `ScopeResolver` deriving the `OperatorScope` from the candidate) instead of once at startup, so operator memory actually reaches the model | yes |
| 3 step D-1 | Recognition-probe primitives (`RequiredField`, `ExpectedResponse`, `CitationScores`, `RecognitionResult`) + pure evaluator functions (`evaluate_adherence`, `evaluate_canary_echoes`, `evaluate_citations`, `score_recognition`) in `core/measurement/prompt_probe.py` | yes |
| 3 step D-2a | `CanaryGenerator` Protocol + `SecretsCanaryGenerator` / `DeterministicCanaryGenerator` + `ComposedPrompt.canary_tokens` field + composer per-layer head-marker injection (opt-in via `canary_generator=` param, empty mapping by default so production behavior unchanged) | yes |
| 3 step D-2b-i | `RecognitionKpiSummary` dataclass + `summarize_recognition` aggregate (adherence pass rate, per-code violation counts, per-layer canary echo rate with measured denominator, citation F1 mean over scored samples only) | yes |
| 3 step D-2b-ii-alpha | `RecognitionScenario` / `RecognitionSample` / `RecognitionRunReport` + `ScenarioResponder` Protocol + `score_batch` (pure) + `run_scenarios` (composer + responder orchestration; composer canaries auto-promoted into scoring) | yes |
| 3 step D-2b-ii-beta | `rule-catalog/prompts/scenarios/` scaffold + `scenario.schema.json` + `load_scenarios(catalog_root)` file-system loader (aggregate-error surface, filename `<id>.v<version>.yaml`, empty catalog legal) | yes |
| 3 step D-2b-ii-gamma-1 | `emit_kpi_rows(report)` target-neutral KPI row emitter + `KpiRow` / `RowUnit` types + stable metric name constants (`prompt.recognition.*`) | yes |
| 3 step D-2b-ii-gamma-2 | `AbstainResponder` + `RecordingResponder` testing helpers + `python -m fdai.core.measurement.prompt_probe_cli` (loads scenarios + composer, runs against AbstainResponder, prints one JSON KpiRow per line to stdout) | yes |
| 4 alpha | Critic role scaffolding: `CriticStance` / `CriticSeverity` / `CriticObjection` / `CriticOutput` / `CriticVerdict` types + `CriticModel` Protocol + `evaluate_critic_output()` pure evaluator + `rule-catalog/prompts/base/t2-critic.v1.yaml` (`default_mode: shadow`, `applies_to: [t2.critic]`). No live wire into the QualityGate; sits dormant until Wave 4.5 lands the debate orchestrator | yes |
| 4 beta-1 | `AzureOpenAICriticModel` httpx adapter implementing the `CriticModel` Protocol via Azure OpenAI ``chat/completions`` with structured JSON output; strict fail-closed parser (unknown stance / severity / missing fields / non-string citation / blank description all raise). Not yet wired into composition root - the shipped catalog seed stays `default_mode: shadow` | yes |
| 4 beta-2 | `t2.critic` capability added to `rule-catalog/llm-registry.yaml` (`invocation: on_disagreement`, Anthropic-first preference so publisher stays distinct from the Proposer). `LlmBindings` gains an optional `critic_model` field; `bind_azure_llm_bindings` binds `AzureOpenAICriticModel` when the capability resolves AND the caller supplied a `critic_system_prompt` (composed from the shipped catalog seed). Startup log gains a `critic_prompt_composed` structured entry when the compose step succeeds | yes |
| 4.5 alpha | Judge role scaffolding: `JudgeDecision` / `JudgeOutput` / `JudgeVerdict` types + `JudgeModel` Protocol + `evaluate_judge_output()` pure evaluator + `rule-catalog/prompts/base/t2-judge.v1.yaml` (`default_mode: shadow`, `applies_to: [t1.judge]`). Judge stays a smaller / cheaper model per the debate orchestrator design | yes |
| 4.5 beta | `AzureOpenAIJudgeModel` httpx adapter implementing the `JudgeModel` Protocol; strict fail-closed parser mirroring the Critic adapter shape | yes |
| 4.5 gamma | `DebateOrchestrator` core module orchestrates Proposer / Critic / Judge with `max_rounds = 1`; fail-closed on any adapter exception (returns `DebateVerdict.ABORT` with the error class preserved), preserves debate transcript in `DebateOutcome` for the audit log, short-circuits Judge when Critic already ABORTs (token-cost guard) | yes |
| 4.5 delta-1 | Composition-root wire: `LlmBindings` gains optional `judge_model` and `debate_orchestrator` fields. `bind_azure_llm_bindings(judge_system_prompt=)` binds `AzureOpenAIJudgeModel` when `t1.judge` capability resolves AND the prompt is supplied. When BOTH `critic_model` AND `judge_model` are bound, a default `DebateOrchestrator(max_rounds=1)` is auto-constructed; `__post_init__` refuses an inconsistent manual construction. `__main__` composes the `t2.judge` prompt from the shipped seed with `LookupError`-graceful degradation | yes |
| 4.5 delta-2a | `DebateRouter` pure policy module in `core/quality_gate/debate_router.py`: `DebateRoutingDecision` + `DebateRouterConfig` (`enabled` killswitch, `on_cross_check_disagreement` axis, `always_for_action_types` / `never_for_action_types` allow/deny lists) + `decide_debate_route()` fail-closed predicate. Orchestrator unavailability short-circuits to SKIP; killswitch dominates the allowlist; denylist wins over allowlist | yes |
| 4.5 delta-2b | `QualityGate` accepts optional `debate_orchestrator` + `debate_router_config`. On cross-check disagreement, calls `decide_debate_route()`; if `DEBATE`, runs the orchestrator with a no-directive `retry_proposer` that re-invokes the primary cross-check model. `DebateOutcome.PROCEED` flips the disagreement to `ELIGIBLE` (provided no other soft issues remain); `ABORT` keeps `DISAGREE`. Half-wiring (only one of the two params) raises at construction | yes |
| 5 alpha | Web search seam in `core/web_search/`: `WebSearchQuery` / `WebSnippet` / `WebSearchResult` types, `WebSearchProvider` async Protocol, `NoOpWebSearchProvider` deny-by-default fake (returns zero snippets on every query with `reasons=("no_op_provider",)`), and sanitizer helpers (`validate_snippet_domain`, `detect_snippet_injection_markers`, `wrap_web_snippet`) that produce a `<web_snippet trusted="false" ...>...</web_snippet>` envelope after refusing off-allowlist domains and injection markers | yes |
| 5 beta-A | Azure Responses provider + latency-routed model pool + Operator API chat opt-in wiring | yes |
| 5 beta-B | Core T2 composition wire that threads sanitized snippets into the tool manifest per policy | planned |

### Wave 4.5 delta-2a - what shipped

The rollout table records this shipment. The current routing contract is in
[Debate orchestrator](#debate-orchestrator-proposer--critic--judge).

## Related docs

| To learn about | Read |
|----------------|------|
| Tier boundaries and quality gate | [llm-strategy.md](../architecture/llm-strategy.md) |
| Trust routing and control loop | [../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
| Human override policy this design extends | [../../.github/instructions/architecture.instructions.md#human-override](../../../.github/instructions/architecture.instructions.md#human-override) |
| Safety invariants and coding conventions | [../../.github/instructions/coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) |
| Prompt-injection threat model | [security-and-identity.md](../architecture/security-and-identity.md) |
| Rule catalog and provenance rule | [rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md) |
