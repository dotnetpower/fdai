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

> **Scope.** Upstream is generic and Azure-first. Web search and any
> customer-specific override arrive as fork-only bindings; the core repo ships
> deny-by-default fakes so a fork MUST opt in explicitly
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
>
> **Status.** Waves 1, 2, 2.5-A, 2.5-B step 1, 2.5-B step 2a, 2.5-B
> step 2b, 3 step A, 3 step B store, 3 step B pipeline slice 1, 3
> step B pipeline slice 2, 3 step C-1, 3 step C-2, 3 step D-1, 3
> step D-2a, 3 step D-2b-i, 3 step D-2b-ii-alpha, 3 step D-2b-ii-beta,
> 3 step D-2b-ii-gamma-1, 3 step D-2b-ii-gamma-2, 4 alpha, 4 beta-1,
> 4 beta-2, 4.5 alpha, 4.5 beta, 4.5 gamma, 4.5 delta-1, 4.5
> delta-2a, 4.5 delta-2b, and 5 alpha have landed - the
> evolving-system-prompt design is now **fully live** for T2:
> operator memory end-to-end, the recognition-probe chapter,
> per-event re-composition inside `AzureOpenAICrossCheckModel`,
> the Critic + Judge + orchestrator triangle (types + evaluators +
> Azure adapters + `max_rounds = 1` orchestrator + composition-root
> binding), the `DebateRouter` pure policy, the `QualityGate`
> escalation path that runs the debate on cross-check disagreement
> and flips a resolved `PROCEED` back to `ELIGIBLE`, and the
> `core/web_search/` seam (deny-by-default `NoOpWebSearchProvider`
> + domain-allowlist + injection-marker sanitizer + `trusted="false"`
> snippet envelope). The composer chain is Base + Task Skill Pack
> + optional Tool Manifest + optional Operator Memory + optional
> per-layer canary tokens. The dataclass fallback default is gone;
> `system_prompt` is required on
> `AzureOpenAICrossCheckModelConfig` and now serves as the
> startup-safety fallback when no composer is wired. Wave 3 step B
> **pipeline slice 3** (fork-first second-approval channel) and
> Wave 5 **beta** (fork-only concrete provider adapter +
> composition-root wire that threads snippets into the T2 tool
> manifest) are documented here but not yet implemented. Every
> wave promotes only after its shadow gate passes; see
> [Rollout waves](#rollout-waves).

## Design at a glance

Prompts are **data**, not literals in code. The composition root loads them
from `rule-catalog/prompts/` at startup, indexes them by capability, and hands
resolved bodies to the Azure OpenAI adapters. Runtime layers (rule-catalog
citations, operator-memory entries, tool outputs, web snippets, debate
transcripts) are wrapped in `trusted="false"` XML tags so the model treats
them as data. The **deterministic verifier remains the sole execution
authority** - every added role, tool, and layer produces material for that
verifier, never a shortcut around it.

## Role x layer matrix

Prompts have two axes. **Layers** are what content types compose an assembled
prompt; **roles** decide which base / pack / tool set applies. Wave 1 ships
only the reviewer role; the others are declared so future waves slot into a
stable seam.

| Layer \\ Role | Proposer | Critic | Judge |
|--------------|----------|--------|-------|
| Base (role skeleton) | `base/t2-proposer.vN.yaml` | `base/t2-critic.vN.yaml` | `base/t2-judge.vN.yaml` |
| Task Skill Pack | `packs/<capability>.proposer.vN.yaml` | `packs/<capability>.critic.vN.yaml` | (usually shared with proposer pack) |
| Tool Manifest | tools + optional `web.search` | tools (read-only) | none (Judge cannot call tools) |
| Domain Context (RAG) | rule / past-incident citations | same | same |
| Web Snippets | if Proposer fetched them | read-only | read-only |
| Operator Memory | scope-bounded | scope-bounded | scope-bounded |
| Debate Transcript | (empty on first turn) | Proposer output | Proposer + Critic outputs |

Today the reviewer role runs a two-model cross-check (Wave 2 keeps this). Wave
4 adds the Critic and Wave 4.5 promotes the loop to a Proposer / Critic / Judge
orchestrator; the matrix already reserves each cell so those additions do not
require a refactor.

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
      t2-proposer.vN.yaml         # Wave 3 (planned)
      t2-critic.vN.yaml           # Wave 4 (planned)
      t2-judge.vN.yaml            # Wave 4.5 (planned)
      t2-rubric.v1.yaml           # rubric hallucination filter (shipped, shadow)
    packs/                        # Wave 2+
    tools/                        # Wave 2.5+
    roles/                        # Wave 3+
```

### Runtime data (Postgres, hash-addressed blobs)

Two new tables land alongside the existing state / audit schema. They are
append-only and hash-addressable so replay never re-fetches external content.

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
per seam. New seams introduced by this design:

| Seam | Kind | Wave | Role |
|------|------|------|------|
| `PromptRegistry` | sync | 1 (shipped) | Load / index prompt YAMLs |
| `PromptComposer` | async | 2 | Assemble Role x Layer per event |
| `ToolRegistry` | sync | 2.5 | Load tool YAML manifests |
| `ToolExecutor` | async | 2.5 | Dispatch model-issued tool calls |
| `OperatorMemoryStore` | async | 3 | Read / append scope-bounded notes |
| `WebSearchProvider` | async | 5 | Outbound HTTP behind allowlist |
| `EvidenceStore` | async | 5 | Persist hash-addressed web snapshots |
| `AgentTranscriptStore` | async | 4.5 | Append-only debate rows |
| `DebateOrchestrator` | async | 4.5 | Proposer -> Critic -> Judge loop |

I/O-bound seams follow the async-by-default rule for provider protocols
declared in
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety).

## Tool use subsystem

Tools are catalog-as-code, mirroring the rule catalog. Each YAML declares its
description, invocation schema, capability gate, allowlist, and output wrapper.

- **Allowlist per capability**: a capability's `llm-registry` entry names the
  tools its Proposer / Critic may call. This keeps the tool manifest short so
  the "lost in the middle" failure mode does not creep in.
- **Untrusted output**: every tool result is wrapped
  (`<tool_result trusted="false" tool="..." ...>...</tool_result>`) and treated
  as data. The verifier and policy re-check remain authoritative.
- **Budget**: each tool declares `cost_budget_usd_per_call` and the composer
  enforces a per-event ceiling; overrun aborts to HIL.
- **Judge holds no tools**: judgment is separation-of-duties; a Judge that
  calls tools would collapse into a second Proposer.

## Web search policy

Web search is the last-resort tool. It is opt-in per fork and never a
grounding source.

- **Default off**: upstream ships a no-op `WebSearchProvider`. A fork provides
  an API key and a curated domain allowlist to activate it.
- **When it may run**: T2 case, novelty score above threshold, capability's
  tool allowlist includes `web.search`, and the per-event query / cost budget
  is not exhausted. This decision is not prose - it is the pure, deterministic
  [`decide_web_search`](../../../src/fdai/core/web_search/policy.py) policy
  (a `WebSearchPolicyConfig` + `WebSearchSignals` -> `SEARCH` / `SKIP`),
  mirroring `escalation_ladder`. It evaluates deny-first gates (disabled ->
  no provider -> capability not allowlisted -> not reasoning-tier -> query
  budget -> cost budget -> grounding-gap required -> novelty threshold) and
  records the SKIP reason in the audit log, so "when web search runs" is
  answered by a test, not a paragraph.
- **Domain allowlist**: primary sources only (vendor docs, RFCs, NVD, CVE
  registries). Blogs, forums, and social media are prohibited.
- **Snippet handling**: HTML stripped; prompt-like patterns
  (`ignore previous`, `system:`, etc.) detected and flagged; content wrapped in
  `<web_snippet trusted="false">...</web_snippet>` before injection.
- **Not a grounding source**: `cited_rule_ids` MUST still resolve to
  rule-catalog entries. Useful web findings feed the rule-catalog discovery
  loop; they never satisfy the current event's grounding requirement.
- **Replay determinism**: results are stored by `(content_hash, url, fetched_at)`
  in `web_evidence`; audit entries reference the hash. Replay reads the
  stored snapshot instead of re-fetching, so past runs stay reproducible.
- **No native model browsing**: FDAI never delegates search to a model's
  built-in browsing / `web_search` tool. Search is always a self-hosted
  `WebSearchProvider` invoked behind the T2 tool manifest, so the domain
  allowlist, snippet sanitization, and `web_evidence` replay determinism stay
  under core control (native browsing would hide all three inside the model).
  The capability whose allowlist carries `web.search` sets
  `tool_calling_required: true` in `rule-catalog/llm-registry.yaml`; the
  bootstrap resolver degrades it to `hil-only` when the target region has no
  function-calling-capable family, so a tool that cannot actually be called
  never ships silently.

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

Critic's role is not "another opinion"; it is a checklist against the four
safety invariants (stop-condition, rollback, blast-radius, audit-log) plus
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

## Safety invariants (extensions)

The eight invariants in
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md#safety)
extend with six more as this design lands:

1. Web-search output is NEVER a `cited_rule_id`.
2. Tool results and web snippets are ALWAYS wrapped in `trusted="false"` XML.
3. Debate loops have hard `max_rounds`, `max_wall_seconds`, `max_cost_usd`
   ceilings; any overrun aborts to HIL.
4. Critic and Proposer publishers MUST differ; a same-publisher pair collapses
   into a single voter.
5. Judge MUST NOT call tools; judgment and generation are separated.
6. Web evidence is hash-addressed immutable; replay reads snapshots, never
   re-fetches.

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
| 3 step B pipeline slice 1 | `HilRejectMaterializer` core module that turns a `HilResponse(decision=REJECT, reason=...)` + a distinct `second_approver` into a stored `OperatorMemoryEntry` via the injected `OperatorMemoryStore`; five pipeline-level error codes (`wrong_decision`, `empty_reason`, `missing_first_approver`, `missing_second_approver`, `same_principal`) fail-fast before the store is touched, and store-side policy errors (duplicate id, injection marker) surface unchanged | yes |
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
| 5 beta | Concrete provider adapter (fork-only - Bing, SerpAPI, curated crawler) + composition-root wire that binds `WebSearchProvider` when a fork opts in and threads snippets into the T2 tool manifest per the web-search policy | planned |

## Wave 1 - what shipped

Wave 1 introduces the seam without changing runtime behavior.

- `rule-catalog/prompts/schema/prompt.schema.json` - JSON Schema for prompt
  artifacts.
- `rule-catalog/prompts/base/t2-cross-check.v1.yaml` - the extracted T2 base
  prompt.
- `src/fdai/core/prompts/` - `PromptRegistry` Protocol,
  `FileSystemPromptRegistry` implementation, aggregate-error validation.
- `bind_azure_llm_bindings` accepts an optional `system_prompt` and threads it
  through every cross-check config.
- `__main__._finalize_llm_bindings` loads the base prompt via
  `FileSystemPromptRegistry` and passes it in.

## Wave 2 - what shipped

Wave 2 completes the seam by turning prompt assembly into a proper composer.

- `src/fdai/core/prompts/composer.py` - `PromptComposer` async
  Protocol + `DefaultPromptComposer` (Base + Task Skill Pack assembly).
- `src/fdai/core/prompts/testing.py` - `StaticPromptComposer` fake so
  fork tests can inject a canned prompt without touching the catalog.
- `PromptRegistry.get_packs(capability_id)` - returns every task-pack
  artifact bound to a capability, keeping only the highest version per id.
- `ComposedPrompt` + `LayerRef` types record the ordered layer manifest and
  per-layer token estimate for future recognition-probe measurement.
- `AzureOpenAICrossCheckModelConfig.system_prompt` is now a required
  field; the dataclass default is gone. Empty prompts are rejected at
  construction.
- `bind_azure_llm_bindings(..., system_prompt=)` is required and forwarded
  to both T2 reasoner configs so mixed-model cross-check sees identical
  instruction context.
- `__main__._finalize_llm_bindings` constructs `DefaultPromptComposer`,
  awaits `compose(capability_id="t2.reasoner.primary")`, and logs the
  composed layer manifest before wiring the adapters.

## Wave 2.5-A - what shipped

Wave 2.5-A adds the shadow-mode filter and the tool-catalog scaffolding.
Tool-manifest injection and the executor land in Wave 2.5-B.

- `DefaultPromptComposer(include_shadow_packs=False)` is the production
  default. Packs authored as `default_mode: shadow` live in git but never
  affect the live prompt until promoted; evaluation runs opt in with
  `include_shadow_packs=True`.
- `rule-catalog/prompts/packs/t2-cross-check-output-contract.v1.yaml` -
  a shipped shadow-mode task pack that proves the seam end-to-end and
  will land as the first `enforce` pack once Wave 3 recognition probes
  confirm it helps.
- `rule-catalog/prompts/tools/schema/tool.schema.json` - JSON Schema for
  tool artifacts. Every tool description validates against it before the
  registry accepts the file.
- `rule-catalog/prompts/tools/README.md` - directory contract mirroring
  the prompts subsystem README.
- `src/fdai/core/tools/` (renamed from the earlier
  `core/prompts/tool_registry.py`) - `ToolArtifact`, `CapabilityGate`,
  `ToolRegistry` Protocol, and `FileSystemToolRegistry` with
  aggregate-error validation. Empty catalogs load without error so a
  fork can adopt the seam before authoring its first tool. The
  `trusted="false"` invariant on `output_wrapper` is enforced at load
  time, not only at inject time.

## Wave 2.5-B step 1 - what shipped

Wave 2.5-B step 1 threads tool descriptions through the composer without
yet dispatching any call. Step 2 wires the executor and the OpenAI
function-calling parameters.

- `DefaultPromptComposer(tool_registry=...)` accepts an optional
  `ToolRegistry`. When supplied and at least one tool is eligible after
  the shadow filter, the composer emits a synthetic `tool-manifest`
  layer at the end of the assembled prompt. When absent or empty, no
  manifest layer is added - the model never sees a "no tools" phrasing.
- `include_shadow_tools=False` is the production default. Setting it to
  ``True`` mirrors `include_shadow_packs=True` for evaluation runs.
- Three shadow-mode tool YAMLs ship under
  `rule-catalog/prompts/tools/catalog/`: `rule.query.v1.yaml`,
  `state.query.v1.yaml`, `audit.query.v1.yaml`. Every one carries a
  `trusted="false"` output wrapper enforced by the registry.
- The prompt registry now skips sibling subsystems under `prompts/`
  (currently just `tools/`) so `FileSystemPromptRegistry` cannot mistake
  a tool YAML for a malformed prompt fragment.

## Wave 2.5-B step 2a - what shipped

Wave 2.5-B step 2a introduces the executor seam so a tool call can be
dispatched end-to-end without touching the Azure OpenAI adapter yet.
Step 2b threads model-issued `tool_calls` through this executor.

- `src/fdai/core/tools/executor.py` - `ToolExecutor` async
  Protocol + `DefaultToolExecutor` upstream implementation + the
  `ToolProvider` seam a fork implements per tool group. Every failure
  surfaces as one of five typed subclasses of `ToolExecutorError`
  (`UnknownToolError`, `ShadowToolBlockedError`,
  `ToolArgumentValidationError`, `MissingProviderError`,
  `ProviderCallError`) so callers route to HIL rather than swallowing
  a partial result.
- `src/fdai/core/tools/testing.py` - `InMemoryToolProvider`
  (canned responses keyed by tool id + sorted argument tuple, calls
  recorded for assertions) and `NoOpToolProvider` (refuses every call;
  the upstream default when a fork promotes a tool without wiring its
  provider).
- Fail-closed guarantees enforced at dispatch time:
  1. unknown tool id -> `UnknownToolError`,
  2. `default_mode: shadow` and `allow_shadow_dispatch=False` ->
     `ShadowToolBlockedError` (belt-and-braces behind the composer's
     manifest-layer filter),
  3. arguments failing the artifact's `input_schema` (including
     `additionalProperties=False`) -> `ToolArgumentValidationError`,
  4. tool declares a `provider` name not wired at composition time ->
     `MissingProviderError`,
  5. provider raises -> `ProviderCallError` with the original
     exception on `__cause__`.
- `ToolResult` records `wrapped_text` (ready to inject next turn),
  `raw` (for the audit writer), `cost_usd`, and `latency_ms` so the
  Wave 4.5 debate orchestrator can enforce per-event budgets.
- The circular import between `core.prompts` and `core.tools` is
  broken with a `TYPE_CHECKING` guard: `core.prompts.composer` uses
  duck typing on the runtime tool registry so it does not need to
  import from `core.tools` at module load.

## Wave 2.5-B step 2b - what shipped

Wave 2.5-B step 2b threads the executor through the Azure OpenAI
cross-check adapter so model-issued tool calls actually reach a
provider round-trip. Every shipped tool is still `default_mode: shadow`
so the adapter advertises zero tools at upstream default; production
behavior is unchanged until a fork registers a real provider and
promotes a tool.

- `AzureOpenAICrossCheckModel.__init__` accepts optional
  `tool_registry` + `tool_executor` (both, or neither - a half-wired
  setup fails fast). The adapter snapshots every enforce-mode tool at
  construction and builds an OpenAI-compatible `tools=[...]` array
  once; the manifest cannot drift under a running `propose()` call.
- `AzureOpenAICrossCheckModelConfig.max_tool_iterations` (default 3)
  bounds the tool-dispatch loop. Setting it to 0 disables tool calls
  even when the executor is injected; setting a positive value and
  reaching it aborts to HIL with a `RuntimeError` rather than burning
  more tokens.
- Tool ids like `rule.query` become OpenAI function names via a
  lossless dot-to-underscore encoding. The reverse lookup uses a map
  built at construction time from the registry snapshot, so an
  attacker cannot smuggle an alternate id by guessing the underscored
  form (`delete_everything` is not in the map -> rejected).
- The multi-turn loop preserves the assistant `tool_calls` turn plus
  a `role: "tool"` message per call so the model has full context on
  the next round.
- Fail-closed guarantees at the adapter boundary:
  1. unknown function name -> `RuntimeError` (before the executor
     ever runs),
  2. tool_calls with no executor wired -> `RuntimeError`,
  3. non-JSON arguments -> `RuntimeError`,
  4. `max_tool_iterations` reached -> `RuntimeError`,
  5. any executor failure propagates as-is so callers can distinguish
     the five `ToolExecutorError` subclasses.
- `bind_azure_llm_bindings` accepts optional `tool_registry` +
  `tool_executor` and threads them into all three cross-check
  construction sites (hil-only primary, primary reasoner, secondary
  reasoner) so mixed-model cross-check sees the same tool manifest.
- `__main__._finalize_llm_bindings` builds a `FileSystemToolRegistry`
  + `DefaultToolExecutor(providers={})` in azure mode. Upstream ships
  with an empty providers map on purpose: every shipped tool is
  shadow, so the adapter advertises zero tools and no dispatch ever
  runs. A fork provides its own providers dict to light up function
  calling.

## Wave 3 step A - what shipped

Wave 3 step A introduces the operator-memory seam so the HIL pipeline
and the composer can be built on a stable surface. The Postgres store,
the HIL second-approval workflow, and the composer integration land in
later steps of Wave 3.

- `src/fdai/core/operator_memory/types.py` - `OperatorMemoryEntry`
  frozen dataclass + three enums: `ScopeKind` (values LIMITED to
  `resource-group` and `resource`; broader scopes are rejected because
  disabling a rule org-wide is a rule retirement, not an override),
  `MemorySource`, `MemoryCategory`.
- `src/fdai/core/operator_memory/store.py` - `OperatorMemoryStore`
  async Protocol + `InMemoryOperatorMemoryStore` upstream default. Every
  write runs the same policy validator so callers cannot bypass the
  Human Override contract by touching the store directly. Policy codes
  are exposed as `OperatorMemoryPolicyError.code` for structured
  telemetry (`empty_body`, `empty_scope_ref`, `scope_too_wide`,
  `missing_author`, `missing_approver`, `self_approval`, `invalid_ttl`,
  `duplicate_id`, `already_superseded`).
- `src/fdai/core/operator_memory/sanitizer.py` -
  `detect_injection_markers` scans bodies for a curated list of
  prompt-injection patterns (case-insensitive; "ignore previous",
  "system:", role-hijack tokens); `wrap_operator_note` renders every
  accepted body inside
  `<operator_note trusted="false" author="..." scope_kind="..."
  scope_ref="..." category="...">...</operator_note>` with every
  attribute + content position XML-escaped so an entry cannot forge
  the closing tag or smuggle a new attribute.
- Append-only semantics: the store never mutates a stored entry; a
  replacement gets its own row and `supersede(entry_id, superseded_by)`
  threads the pointer. Double supersede is rejected with the
  `already_superseded` policy code.
- Long-lived entries (`ttl_seconds=None`) are permitted per the Human
  Override policy; TTL values MUST be positive when provided.
- The write path enforces the injection defense before the composer
  layer, so a malicious body cannot even land in storage - the reviewer
  fixes it at approval time or the entry is discarded.

## Wave 3 step B store - what shipped

Wave 3 step B lands the persistent Postgres backing for
`OperatorMemoryStore` so scope-narrowed operator notes survive
process restarts and can be queried by the composer on every T2
event. The second half of step B (the HIL second-approval **pipeline**
that materialises `OperatorMemoryEntry` rows from a HIL reject) is a
separate follow-up and is still `planned` in the rollout table.

- `alembic/versions/20260706_0006_operator_memory.py` - one table,
  `operator_memory`, with CHECK constraints that mirror the Python
  policy: `scope_kind IN ('resource-group', 'resource')`,
  `btrim(body) <> ''`, `btrim(scope_ref) <> ''`,
  `category IN (…)`, `ttl_seconds IS NULL OR ttl_seconds > 0`, and
  `lower(btrim(author)) <> lower(btrim(approved_by))`. Even a caller
  bypassing the Python-side validator cannot land an unreviewed or
  self-approved entry.
- `superseded_by` is a self-referential FK; the append-only invariant
  is enforced by never issuing `UPDATE ... SET body = ...` - the only
  UPDATE is on `superseded_by` inside a `FOR UPDATE`-locked
  transaction, and the store returns `already_superseded` rather than
  overwriting the pointer.
- `src/fdai/delivery/persistence/postgres_operator_memory.py` -
  `PostgresOperatorMemoryStore` realises the same async
  `OperatorMemoryStore` Protocol as the in-memory fake. The DSN +
  `statement_timeout_ms` contract matches `PostgresStateStore` so the
  two adapters can be wired from the same config surface.
- `append()` calls the shared `_reject_policy_violations` **before**
  opening a connection - policy errors surface as
  `OperatorMemoryPolicyError` with the same codes as the in-memory
  store (`empty_body`, `self_approval`, `invalid_ttl`, ...). A
  PRIMARY-KEY collision on `id` is translated to the
  `duplicate_id` code so the composer sees a single error taxonomy
  across backends.
- `list_active_for_scope()` filters superseded AND expired rows in
  one SQL query via
  `NOW() - created_at < make_interval(secs => ttl_seconds)`,
  matching the `_is_expired` helper's semantics; the composer never
  has to post-filter.
- `_row_to_entry()` coerces naive `datetime` values to UTC and
  parses ISO-8601 / UUID string columns defensively so JSON
  export/import round-trips land on the right Python types.
- Integration tests (`tests/persistence/test_postgres_operator_memory.py`)
  follow the same skip-on-`FDAI_DATABASE_URL`-unset pattern as
  the pgvector + state-store adapters; they cover append + list +
  supersede + expiry + duplicate-id + unknown-id-lookup on a live
  Postgres. Offline unit tests exercise config validation, the
  coerce helpers, and cross-backend policy-error parity so the file
  keeps coverage even without a database.

## Wave 3 step B pipeline slice 1 - what shipped

Wave 3 step B pipeline slice 1 lands the pure domain module that
turns a HIL reject reason into a persisted `OperatorMemoryEntry`
after a second, distinct operator approves. The HTTP / ChatOps
callback that actually invokes it lives in a follow-up slice; this
step is the "brain" - the same class handles the second-approval
logic whether the trigger is a Teams Adaptive Card button, a
reconciler poll, or a fork-authored CLI.

- `src/fdai/core/operator_memory/hil_pipeline.py` -
  `HilRejectMaterializer(*, store, entry_id_fn=uuid4, now_fn=None)`
  exposes one async method, `materialize(*, hil_response,
  second_approver, material)`. Deterministic hooks
  (`entry_id_fn`, `now_fn`) let tests pin the id and the timestamp
  without monkey-patching a global.
- `HilRejectMaterial(scope_kind, scope_ref, category, source_ref,
  ttl_seconds=None, metadata=...)` carries the workflow-supplied
  context (from a ChatOps command, an HTTP endpoint, or a
  reconciler poll). `source_ref` is conventionally
  `hil.reject:<approval_id>` so an auditor can trace the entry
  back to the exact HIL run.
- Five fail-fast error codes on `HilMaterializationError` short-
  circuit before the store is touched:
  `wrong_decision` (not a REJECT), `empty_reason` (no memory-
  worthy content), `missing_first_approver` (no
  `HilResponse.approver_id`), `missing_second_approver` (no
  reviewer), and `same_principal` (the rejecter tried to self-
  approve after `strip().lower()` normalization). The last one is
  intentionally distinct from the store's `self_approval` code so
  the UI can distinguish "you cannot self-approve at this stage"
  from "the store's deeper policy refused for a different
  reason".
- Store-side policy errors flow through unchanged. When the
  sanitizer detects a prompt-injection marker in the reason, or
  when the caller's `entry_id_fn` returns a duplicate id, the
  store's `OperatorMemoryPolicyError` (with codes like
  `injection_marker_detected`, `duplicate_id`) is what the caller
  sees - the materializer never swallows or re-codes those.
- Kept `core/`-safe: the module imports only from
  `fdai.core.operator_memory` and
  `fdai.shared.providers.hil_channel` (a Protocol package),
  so `scripts/check-core-imports.sh` continues to pass. No
  `delivery.*` import lands.

## Wave 3 step B pipeline slice 2 - what shipped

Wave 3 step B pipeline slice 2 wires the `OperatorMemoryStore` into
the composition root so the operator-memory layer is actually
reachable end-to-end at runtime. Slice 1 shipped the
`HilRejectMaterializer` and slice 3 will ship a specific
second-approval channel; this slice is the connecting tissue that
makes an entry appended by one path immediately visible to the
composer on the next event.

- `_build_operator_memory_store()` in `src/fdai/__main__.py`
  mirrors the existing `_build_audit_store()` pattern: when
  `FDAI_OPERATOR_MEMORY_DSN` is set (populated by the
  container's Key Vault secret ref) the wire returns a
  `PostgresOperatorMemoryStore`; otherwise the deterministic
  `InMemoryOperatorMemoryStore` fake is used so the composer's
  operator-memory layer is fully wired end-to-end even without a
  database. A fork that seeds an entry via `HilRejectMaterializer`
  sees the layer materialize on the next `compose()` call without
  any additional plumbing.
- `_finalize_llm_bindings()` now constructs the store and hands it
  to `DefaultPromptComposer(registry=..., operator_memory_store=...)`.
  The startup `prompt_composed` structured log gains an
  `operator_memory_store` field carrying the concrete class name so
  a deployment can grep the log to verify which backend the process
  bound.
- Backend selection is defense-in-depth: an empty-string DSN is
  treated as "unset" (`if dsn:` is falsy on `""`) so a mis-quoted
  env var falls back to the in-memory fake rather than
  instantiating a broken Postgres adapter. A test pins this
  behaviour against regression.
- Three offline tests in `tests/test_main_helpers.py` prove the
  helper wires the right backend for each env-var state; the
  composer-side of the seam is already covered by
  `tests/core/prompts/test_composer.py`, so the end-to-end wire is
  proven by composition.

## Wave 3 step C-1 - what shipped

Wave 3 step C-1 threads operator memory through the composer without
touching the delivery adapter yet. Step C-2 moves composition into the
per-event request path so the notes actually reach the model at
runtime.

- `PromptLayer.OPERATOR_MEMORY` - new synthetic layer value used by
  the composer's memory layer. The JSON Schema for prompt artifacts
  intentionally does NOT list this value: operator-memory content is a
  data layer materialized from the store, never authored as a YAML
  fragment.
- `OperatorScope(resource_group_ref, resource_ref=None)` - the tuple
  the composer resolves against. A ``None`` scope means "no operator
  memory this call"; production per-event dispatch supplies a real
  scope drawn from the normalized event payload.
- `DefaultPromptComposer(operator_memory_store=..., scope=...)`
  queries the store twice (RG level always, resource level when the
  scope carries a resource ref) and concatenates the results with
  resource-group notes first, resource notes second, so the most
  specific guidance sits closest to the user turn.
- Each retrieved entry is wrapped via `wrap_operator_note`, preserving
  the `trusted="false"` invariant. Superseded / expired entries are
  filtered by the store's `list_active_for_scope`; the composer
  never re-checks lifecycle state.
- `StaticPromptComposer` (test fake) tracks `(capability_id, scope)`
  pairs on every call so tests can assert the composition context
  without inspecting the assembled prompt.
- The composer emits **no memory layer** in three explicit cases:
  1. `operator_memory_store` is not injected,
  2. `scope` is `None` at call time (startup composition path),
  3. store returns zero active entries for the resolved scope.

## Wave 3 step C-2 - what shipped

Wave 3 step C-2 moves prompt composition from startup-only to per-event
so operator-memory entries (via a fork-supplied resolver) and canary
tokens rotate on every model call. The change is additive: composition
roots that never pass a composer keep sending the static
`config.system_prompt` as before.

- `AzureOpenAICrossCheckModel.__init__` grows three optional keyword
  arguments: `prompt_composer` (a `PromptComposer` instance),
  `capability_id` (the role key looked up in the composer), and
  `scope_resolver` (a `Callable[[QualityCandidate], OperatorScope | None]`).
- Cross-consistency is enforced at construction: `prompt_composer` and
  `capability_id` MUST be provided together, `capability_id` MUST be
  non-empty, and `scope_resolver` MUST NOT appear without a composer
  (a resolver with nothing to feed is a wiring bug).
- `_resolve_system_prompt(candidate)` is called first on every
  `propose()` turn. When a composer is wired it re-composes via
  `await composer.compose(capability_id=..., scope=resolver(candidate))`;
  otherwise it returns the snapshot in `config.system_prompt`.
- **Composer failures raise `RuntimeError`** with the capability id
  in the message. This routes the run to HIL through the existing
  quality-gate error paths; the adapter never silently degrades to
  the fallback text, which would ship a stale prompt without the
  operator memory or fresh canary tokens the loop depends on.
- `bind_azure_llm_bindings` grows matching `prompt_composer` and
  `scope_resolver` parameters and constructs both T2 reasoners with
  their own role-specific capability id
  (`t2.reasoner.primary` / `t2.reasoner.secondary`) so cross-check
  quorum sees consistent instruction context per role rather than a
  single shared prompt.
- `__main__._finalize_llm_bindings` now passes the upstream composer
  through with `scope_resolver=None`. The ARM-id parser that maps a
  `QualityCandidate.target_resource_ref` to an `OperatorScope` lives
  in a fork's composition root; the upstream repo stays CSP-neutral.
- The startup `composer.compose(capability_id="t2.reasoner.primary")`
  call stays: it validates the catalog + schemas at process start
  and emits the `prompt_composed` structured log for observability,
  even though the resulting `system_text` is no longer the one the
  model sees for a live event.

## Wave 3 step D-1 - what shipped

Wave 3 step D-1 lands the pure evaluator half of the recognition-probe
KPI. Step D-2 teaches the composer to insert canary tokens per layer
and wires the numbers into a dashboard scenario runner.

- `src/fdai/core/measurement/prompt_probe.py` - four typed
  input / output dataclasses (`RequiredField`, `ExpectedResponse`,
  `CitationScores`, `RecognitionResult`) plus four pure evaluators:
  `evaluate_adherence` (JSON validity + per-field
  presence / type / non-emptiness with structured violation codes),
  `evaluate_canary_echoes` (case-sensitive substring match against the
  raw response so a lower-cased echo does NOT count as recognition),
  `evaluate_citations` (precision / recall / F1 on cited rule ids as
  sets - duplicates and empty strings ignored), and the
  `score_recognition` aggregate that ties them together.
- Structured violation codes: `not-a-json-object`, `missing-field:X`,
  `wrong-type:X`, `empty-field:X` so a KPI dashboard buckets them
  without regex-matching free text.
- Non-JSON responses report exactly one aggregate `not-a-json-object`
  violation instead of fanning out per-field failures (double-counting
  the same underlying defect would corrupt the KPI).
- `_extract_cited_ids` reads the response tolerantly: a missing
  field, a wrong-type value, and non-string members all surface as
  zero recall on citations rather than raising - the recognition
  probe never turns into a source of hard failures.

## Wave 3 step D-2a - what shipped

Wave 3 step D-2a puts a canary token at the head of every composed
layer so the recognition probe's canary-echo evaluator has real
markers to score. Step D-2b adds a scenario runner that consumes those
tokens and the D-1 evaluators to publish dashboard rows.

- `CanaryGenerator` Protocol lives in
  `core/measurement/prompt_probe.py` next to the evaluators.
  `SecretsCanaryGenerator` uses :mod:`secrets` for production
  unpredictability; `DeterministicCanaryGenerator` accepts a
  pre-seeded ``{layer_id: token}`` mapping for tests and replay runs.
- `ComposedPrompt.canary_tokens: Mapping[str, str]` records the
  ``layer_id -> injected token`` pairs. Defaults to an empty mapping
  so composers without a generator produce the same output shape as
  Wave 3 step C-1.
- `DefaultPromptComposer(canary_generator=...)` is the new opt-in.
  When injected, the composer prepends
  ``[canary:<layer_id>=<TOKEN>]\n`` to every layer body (base, task
  packs, tool manifest, operator memory) and refreshes each
  ``LayerRef.token_estimate`` so the manifest reflects what the
  model actually sees.
- Production behavior is unchanged: `__main__._finalize_llm_bindings`
  does not pass a canary generator, so the current wire prompt stays
  identical to the pre-D-2a shape.
- The token estimate update after canary injection is a first
  concrete input to the recognition-probe KPI - a layer whose
  post-canary token budget crosses a ceiling is a candidate
  ``prompt.token_budget.exceeded_rate`` signal for D-2b.

## Wave 3 step D-2b-i - what shipped

Wave 3 step D-2b-i lands the KPI aggregate that turns a batch of
per-sample `RecognitionResult` values into one publishable summary.
Step D-2b-ii adds the scenario fixture format, the runner CLI, and
the actual dashboard row emission.

- `RecognitionKpiSummary` frozen dataclass carries the four KPIs the
  design doc calls for: `adherence_pass_rate`, per-code
  `adherence_violation_counts`, `per_layer_canary_echo_rate`, and
  `mean_citation_f1`.
- `summarize_recognition(results)` is the pure aggregate function.
  It's testable in isolation and stays agnostic of how the results
  were produced - a shadow-mode runner, an offline fixture replay, or
  a CI batch all consume the same shape.
- **Measured denominator per layer**: the echo rate for a layer is
  computed against the number of samples that actually measured
  that layer (its id was present in `canary_echoes`), not against
  the batch size. A run that only exercised half of a capability
  cannot silently halve every echo rate.
- **Citation mean excludes non-scored samples**: samples where the
  caller passed no `expected_cited_rule_ids` have
  `result.citations is None` and are excluded from
  `mean_citation_f1`. Only scored samples contribute so citation
  coverage is not diluted by non-scored runs.
- **Empty batch is neutral, not zero**: an empty result list returns
  a summary with `mean_citation_f1 is None` so a dashboard emitter
  skips publishing a citation row rather than reporting a
  misleading 0.0.
- **Layers never measured never appear**: the map keeps a clean
  distinction between "measured, never echoed" (rate 0.0) and "not
  measured at all" (key absent), so an alerting rule on `< 50% echo`
  cannot fire on a layer nobody looked at.

## Wave 3 step D-2b-ii-alpha - what shipped

Wave 3 step D-2b-ii-alpha delivers the runtime API for batch scoring
and live scenario execution. The catalog-as-code YAML format, the
CLI, and the dashboard emission ship in the ``beta`` / ``gamma`` sub
-steps.

- `src/fdai/core/measurement/prompt_probe_runner.py` -
  `RecognitionSample` (composed prompt + response + expected),
  `RecognitionRunReport` (per-sample results + KPI summary in one
  bundle), `RecognitionScenario` (composable spec: capability id +
  optional scope + expected contract), `ScenarioResponder` async
  Protocol (fork wires a real model; tests supply canned
  responders).
- `score_batch(samples)` is the pure aggregate that turns a
  pre-composed batch into a report. When
  `sample.expected.canary_tokens` is unset AND the composer stamped
  canaries onto `composed_prompt.canary_tokens`, the scorer
  auto-promotes the composer tokens - scenario authors do not
  duplicate the canary map, and drift between the two shapes is
  impossible.
- Explicit `expected.canary_tokens` values override the auto-
  promotion so regression fixtures can pin the original run's tokens
  even if the composer changes.
- `run_scenarios(composer, responder, scenarios)` is the live-runner
  entry point. For each scenario it composes with the scenario's
  `capability_id` + `scope`, awaits the responder, then delegates to
  `score_batch`. Scope is threaded through verbatim so a
  scope-bound operator-memory layer is actually reachable by the
  recognition run.
- No I/O providers or YAML fixtures ship yet - upstream keeps the
  runtime seam pure so fork tests can drive it against any composer
  and any responder without a dependency on Azure.

## Wave 3 step D-2b-ii-beta - what shipped

Wave 3 step D-2b-ii-beta lands the catalog-as-code half of the
recognition-probe surface: an on-disk scenario format that a fork
can author independently of any live composer or responder.

- `rule-catalog/prompts/scenarios/schema/scenario.schema.json` -
  JSON Schema every scenario YAML validates against.
  `capability_id` is required, `scope` is optional (with a required
  `resource_group_ref` and an optional `resource_ref` when present),
  and `expected.required_fields` requires at least one field with a
  known `expected_type` (`string` / `object` / `array`).
- `rule-catalog/prompts/scenarios/README.md` - directory contract
  mirroring the prompts + tools subsystem READMEs.
- `src/fdai/core/measurement/prompt_probe_loader.py` -
  `load_scenarios(catalog_root) -> tuple[RecognitionScenario, ...]`
  with the same aggregate-error surface as the prompt and tool
  registries. Empty catalog is legal so a fork can adopt the seam
  before authoring its first scenario.
- `FileSystemPromptRegistry` now skips both `tools/` AND `scenarios/`
  peer subsystems so a scenario YAML cannot accidentally trip the
  prompt-schema validator.

## Wave 3 step D-2b-ii-gamma-1 - what shipped

Wave 3 step D-2b-ii-gamma-1 lands the pure KPI row emitter that turns
a `RecognitionRunReport` into a target-neutral list of metric rows.
Step gamma-2 wires the CLI to consume them.

- `src/fdai/core/measurement/prompt_probe_emit.py` -
  `KpiRow(metric, value, unit, dimensions)` + `RowUnit` enum
  (`ratio`, `count`) + five metric name constants
  (`prompt.recognition.sample_count`,
  `prompt.recognition.adherence.pass_rate`,
  `prompt.recognition.adherence.violation_count`,
  `prompt.recognition.canary_echo_rate`,
  `prompt.recognition.citation_f1.mean`).
- `emit_kpi_rows(report, *, dimensions=None)` merges caller-supplied
  base dimensions (typical use:
  `{"capability": "t2.reasoner.primary"}`) into every emitted row so
  a per-capability run publishes rows that are distinguishable in
  the sink.
- Emission rules baked in and tested:
  - **Empty batch** still emits `sample_count = 0` so a dashboard
    series that always publishes at least the sample count does
    not silently disappear;
  - **Adherence pass rate** is emitted only when `sample_count > 0`
    (avoids a misleading `0/0`);
  - **Violation counts** are one row per code, dimensioned by
    `code`, sorted alphabetically for stable dashboard ordering;
  - **Per-layer echo rates** are one row per layer id, dimensioned
    by `layer_id`, using the aggregate's measured denominator so a
    layer measured in only half the batch is not silently diluted;
  - **Citation F1** is emitted only when at least one sample was
    scored (`mean_citation_f1 is not None`) - a batch that opted
    out of citation scoring never publishes a misleading `0.0`.
- Metric-specific labels (`code`, `layer_id`) never leak across
  metric families - each row's dimension set is scoped to its own
  metric.

## Wave 3 step D-2b-ii-gamma-2 - what shipped

Wave 3 step D-2b-ii-gamma-2 closes the recognition-probe chapter with
the smoke-runnable CLI and its responder helpers. Dashboard panels
that name the recognition metrics land alongside the P0 KPI dashboard
in a follow-up doc edit; this step focuses on the runtime.

- `src/fdai/core/measurement/prompt_probe_testing.py` -
  `AbstainResponder` returns a canned ``hil.escalate`` JSON action
  on every call so the upstream CLI is smoke-runnable without any
  live model, and `RecordingResponder` pops canned answers from a
  queue while recording `(capability_id, composed_system_text)`
  pairs for after-the-fact assertions.
- `AbstainResponder` serialises its JSON body ONCE at construction
  so every ``respond`` call returns byte-identical text; a shadow
  run comparing responses across time cannot see spurious
  variation.
- `src/fdai/core/measurement/prompt_probe_cli.py` -
  `run_from_catalog(catalog_root, responder)` wires a
  `FileSystemPromptRegistry` + `DefaultPromptComposer`, calls
  `load_scenarios(catalog_root)`, and delegates to
  `run_scenarios`. `main()` is the sync entry point behind
  ``python -m fdai.core.measurement.prompt_probe_cli``.
- CLI exit codes match the existing `runners_cli.py` contract:
  ``0`` = run completed (empty catalog is a valid outcome, prints
  the ``sample_count = 0`` row), ``2`` = catalog root missing,
  ``3`` = unexpected exception with traceback on stderr.
- Output shape: one JSON object per line on stdout, sorted keys,
  ready for a `jq`/`awk`/observability pipeline to ingest without
  further parsing.
- The CLI never touches an Azure endpoint. A fork imports
  `run_from_catalog` from a live composition root and passes a
  real `ScenarioResponder` (that wires the Azure OpenAI adapter
  built in Wave 2.5-B).

## Wave 4 alpha - what shipped

Wave 4 alpha lands the typed shape for the Critic role plus a
shadow-mode prompt seed - the "brain" of the Critic without any
live wiring. Wave 4 beta will ship the Azure adapter and Wave 4.5
will orchestrate the Proposer / Critic / Judge loop; this alpha
step is deliberately dormant so the types + evaluator can be
consumed by fork-authored probes and future orchestrator code
without any risk to the current T2 flow.

- `src/fdai/core/quality_gate/critic.py` -
  `CriticStance` (`agree` / `challenge` / `abstain`),
  `CriticSeverity` (`low` / `medium` / `high`),
  `CriticObjection` (frozen dataclass with `__post_init__` refusing
  blank citation or description),
  `CriticOutput` (stance + objections + citations + optional
  confidence signals following the same "no model self-report"
  contract as `QualityCandidate`),
  `CriticVerdict` (`endorse` / `retry` / `abort` / `abstain`),
  and the `CriticModel` Protocol.
- `evaluate_critic_output(output, *, known_rule_ids)` reduces one
  `CriticOutput` to one verdict. Rules baked into the tests:
  - `ABSTAIN` stance short-circuits to `ABSTAIN` verdict (no
    objection inspection);
  - `AGREE` with any HIGH-severity objection returns `ABORT` -
    self-contradiction is never honored;
  - `AGREE` otherwise returns `ENDORSE` (a LOW-severity nit
    alongside AGREE is still an endorsement);
  - `CHALLENGE` with an empty objections list returns `ABSTAIN`
    (challenge without evidence is a defect);
  - `CHALLENGE` with any objection citing an unknown rule id
    returns `ABSTAIN` (ungrounded objection breaks the audit
    trail);
  - `CHALLENGE` with any HIGH-severity objection returns
    `ABORT`;
  - otherwise `CHALLENGE` returns `RETRY`.
- `rule-catalog/prompts/base/t2-critic.v1.yaml` - `layer: critic`,
  `applies_to: [t2.critic]`, `default_mode: shadow`. The body
  narrates the structured JSON contract the evaluator enforces
  (stance + grounded objections + citations) so a live Critic
  emits parseable output. The `t2.critic` capability is not yet
  in `llm-registry.yaml`; the seed sits dormant, ready for Wave 4
  beta to add the capability and wire the adapter.
- The Critic is not wired into `QualityGate` in this alpha. The
  deterministic verifier remains the sole execution authority;
  the Critic (once wired) surfaces objections the orchestrator
  threads into the audit trail and into a Wave 4.5 Proposer
  retry.
- Kept `core/`-safe: the module imports only from
  `fdai.core.quality_gate.gate` and stdlib; no
  `delivery.*`, no LLM SDK. `scripts/check-core-imports.sh`
  continues to pass at 74 files.

## Wave 4 beta-1 - what shipped

Wave 4 beta-1 lands the Azure adapter that makes a real Critic call
against Azure OpenAI. It is deliberately **not** wired into the
composition root yet - the shipped
`rule-catalog/prompts/base/t2-critic.v1.yaml` seed stays
`default_mode: shadow`, so a running deployment sees no behaviour
change. Wave 4 beta-2 will add the `t2.critic` capability entry to
`llm-registry.yaml` and thread the adapter through the composition
root.

- `src/fdai/delivery/azure/llm/critic.py` -
  `AzureOpenAICriticModelConfig` (endpoint, deployment,
  **required** `system_prompt`, api_version, temperature,
  max_tokens, timeout_seconds) + `AzureOpenAICriticModel` with a
  single async `critique(candidate, proposer_output)` method that
  POSTs to `/openai/deployments/{deployment}/chat/completions`
  with `response_format={"type": "json_object"}`.
- Config validation mirrors the cross-check adapter's fail-fast
  contract: non-https endpoint, empty deployment, empty
  system_prompt, zero / out-of-range temperature, zero max_tokens,
  and zero timeout all raise `ValueError` at construction time.
- User-turn envelope contains both the candidate and the Proposer
  output in a canonical `(sort_keys=True)` JSON shape so replay
  and audit are deterministic.
- The response parser is the safety surface. Every failure raises
  `RuntimeError` with a descriptive message so the future debate
  orchestrator routes the run to HIL rather than silently
  accepting a malformed critique:
  - non-string / empty `content`;
  - `content` that is not valid JSON;
  - `content` that decodes to a non-object;
  - missing or non-string `stance`;
  - `stance` outside the `CriticStance` enum;
  - non-array `objections`;
  - non-object entry in the objections list;
  - missing / non-string `severity` in an objection;
  - `severity` outside the `CriticSeverity` enum;
  - non-string `cited_rule_id` / `description`;
  - non-string / non-null `alt_action_type` (empty string is
    normalized to `None` so downstream code has a single "no
    alternate" representation);
  - non-string / blank citation entry.
- `CriticObjection.__post_init__` is the second line of defense -
  even if the parser missed a whitespace-only description, the
  dataclass raises `ValueError` before the object escapes the
  adapter.
- `tests/delivery/azure/llm/test_critic.py` covers all 6 config
  validation paths + 4 successful parses + 10 fail-closed parses +
  HTTP status propagation. Uses `httpx.MockTransport` throughout;
  no live network required.
- Registered in `delivery/azure/llm/__init__.py` alongside the
  cross-check adapter; both classes are ready for the composition
  root to import when beta-2 lands.

## Wave 4 beta-2 - what shipped

Wave 4 beta-2 wires the Critic adapter into the composition root
via an opt-in binding. A fork that adds no `t2.critic` capability
to its registry keeps the pre-Wave-4 shape; a fork that DOES resolve
the capability gets `LlmBindings.critic_model` bound to a live
`AzureOpenAICriticModel` ready for the Wave 4.5 debate orchestrator.

- `rule-catalog/llm-registry.yaml` gains a `t2.critic` entry with
  `invocation: on_disagreement` and Anthropic-first preference so
  the Critic publisher stays distinct from the OpenAI-first
  Proposer per the debate design.
- `composition.LlmBindings` gains an optional `critic_model` field
  (`CriticModel | None`) so the seam surface is uniform across the
  Critic-off and Critic-on paths.
- `bind_azure_llm_bindings` grows an optional `critic_system_prompt`
  parameter. The Critic model is bound only when the capability
  resolves AND the prompt is supplied - two conditions, both
  required, so a partial fork configuration (capability without
  prompt, or vice versa) never lands a half-wired adapter.
- `__main__._finalize_llm_bindings` composes the Critic system
  prompt via `composer.compose(capability_id="t2.critic")`. When
  the compose step raises `LookupError` (no critic base prompt in
  the catalog), the wire silently degrades to `critic_model=None`
  and emits a `critic_prompt_missing` structured log so a
  deployment can grep for the reason. On success it emits
  `critic_prompt_composed` alongside the existing `prompt_composed`
  entry.
- Three tests in `tests/test_composition_llm.py` pin the three-way
  matrix: (capability + prompt) → bound, (capability only) → None,
  (prompt only, no capability) → None.

## Wave 4.5 alpha - what shipped

Wave 4.5 alpha lands the typed shape for the Judge role plus a
shadow-mode prompt seed - mirroring the Wave 4 alpha slice for the
Critic. The Judge is intentionally a smaller model (bound to
`t1.judge`, not a `t2.*` capability) per the debate orchestrator
design; the tier drop keeps the Judge's per-event cost bounded even
when the Proposer / Critic pair is expensive.

- `src/fdai/core/quality_gate/judge.py` -
  `JudgeDecision` (`accept` / `revise_and_retry` /
  `escalate_hil`), `JudgeOutput` (frozen dataclass whose
  `__post_init__` refuses a blank justification),
  `JudgeVerdict` (`proceed` / `retry` / `escalate`), and the
  `JudgeModel` Protocol.
- `evaluate_judge_output(output, *, known_rule_ids)` reduces one
  `JudgeOutput` to one verdict. Rules:
  - `ACCEPT` with only known citations -> `PROCEED`;
  - `ACCEPT` with any unknown citation -> `ESCALATE`
    (ungrounded acceptance is not honored);
  - `REVISE_AND_RETRY` with a non-blank `retry_directive` and
    only known citations -> `RETRY`;
  - `REVISE_AND_RETRY` with a missing / blank directive ->
    `ESCALATE` (the Proposer would not know what to change);
  - `ESCALATE_HIL` -> `ESCALATE`.
- `rule-catalog/prompts/base/t2-judge.v1.yaml` - `layer: judge`,
  `applies_to: [t1.judge]`, `default_mode: shadow`. Body narrates
  the JSON contract the evaluator enforces so a live Judge emits
  parseable output. The `t1.judge` capability already exists in
  `llm-registry.yaml` so no registry change is needed.
- Kept `core/`-safe: imports only from
  `fdai.core.quality_gate.gate` +
  `fdai.core.quality_gate.critic` (both peer modules) plus
  stdlib.

## Wave 4.5 beta - what shipped

Wave 4.5 beta lands the Azure Judge adapter, mirroring the Wave 4
beta-1 shape.

- `src/fdai/delivery/azure/llm/judge.py` -
  `AzureOpenAIJudgeModelConfig` (endpoint, deployment,
  **required** `system_prompt`, api_version, temperature,
  max_tokens, timeout_seconds) + `AzureOpenAIJudgeModel` with a
  single async `judge(candidate, proposer_output, critic_output)`
  method that POSTs to `chat/completions` with
  `response_format={"type": "json_object"}`.
- User-turn envelope carries the candidate + the Proposer output +
  the Critic's stance / objections / citations in a canonical
  `(sort_keys=True)` JSON shape so replay and audit are
  deterministic.
- Strict fail-closed parser: non-JSON content, non-object payload,
  missing / non-string / enum-invalid `decision`, non-string
  `justification`, non-string / non-null `retry_directive`,
  non-array `citations`, non-string citation entry - all raise
  `RuntimeError`. `JudgeOutput.__post_init__` catches blank
  justification as the second line of defense.
- 20 tests in `tests/delivery/azure/llm/test_judge.py` cover the
  6 config validation paths + 4 successful parses + 10
  fail-closed parses using `httpx.MockTransport`.
- Not yet wired into composition root; Wave 4.5 gamma builds the
  orchestrator and Wave 4.5 delta will thread everything through
  the live `QualityGate`.

## Wave 4.5 gamma - what shipped

Wave 4.5 gamma lands the `DebateOrchestrator` core module: one
class + one config + one `DebateOutcome` record that coordinates
the Critic and Judge around a Proposer candidate. This closes the
Wave 4.5 chapter for `core/`; Wave 4.5 delta will wire the
orchestrator into the live `QualityGate` when both capabilities
resolve.

- `src/fdai/core/quality_gate/debate.py` -
  `DebateOrchestrator(*, critic, judge, config=None)`;
  `DebateOrchestratorConfig(max_rounds=1)` with a strict
  `__post_init__` that refuses any value outside `[0, 1]` for
  Wave 4.5 (raising it later is an explicit reviewable edit);
  `ProposerRetry` type alias for the caller-supplied Proposer
  retry callback (kept as `Callable` so no `delivery.*` import
  leaks into `core/`);
  `DebateVerdict` (`proceed` / `abort`) and
  `DebateOutcome` (verdict + reason + final proposer output +
  full transcript fields + rounds counter + `error_class`).
- One `async run(...)` method drives the whole loop:
  1. Critic turn 1 -> if ABORT or ABSTAIN, short-circuit to
     `DebateVerdict.ABORT` **without spending a Judge call**
     (token-cost guard baked into the test suite);
  2. Judge turn 1 -> `PROCEED` returns immediately; `ESCALATE`
     aborts; `RETRY` runs the second round;
  3. Retry -> `retry_proposer(candidate, directive)` is invoked
     (required parameter when `max_rounds >= 1`; missing it
     raises `ValueError` at call time so a fork configuration
     bug fails fast);
  4. Critic turn 2 -> ABORT / ABSTAIN both abort;
  5. Judge turn 2 -> `PROCEED` returns with `rounds=2`; anything
     else aborts (a `RETRY` on round 2 exceeds `max_rounds` and
     is refused).
- **Fail-closed** on any adapter exception. `except Exception`
  branches catch Critic / Judge / Proposer failures on both
  rounds and produce `DebateVerdict.ABORT` with `error_class`
  preserved. The debate transcript accumulated so far
  (Critic output, Judge output, previous-round verdicts) is
  threaded into the `DebateOutcome` so the audit log can show
  exactly how far the debate got before the error.
- 14 tests in `tests/quality_gate/test_debate.py` cover: config
  validation (2), retry-argument-required (1), Round-1 happy path
  + Critic ABORT short-circuit + Critic ABSTAIN short-circuit +
  Judge escalate (4), retry round + max_rounds=0 refusal + retry
  Critic ABORT + Judge re-retry refusal (4), and three error
  paths preserving `error_class`.

## Wave 4.5 delta-1 - what shipped

Wave 4.5 delta-1 wires the Judge adapter into the composition root
and auto-constructs the `DebateOrchestrator` when both role models
are bound. The container now exposes a ready-to-use debate seam;
delta-2 will choose which live events actually flow through it
instead of the two-model cross-check quorum.

- `composition.LlmBindings` gains two optional fields:
  `judge_model: JudgeModel | None` and
  `debate_orchestrator: DebateOrchestrator | None`. The
  dataclass `__post_init__` refuses an inconsistent manual
  construction (orchestrator present without both role models
  bound) so a fork configuration bug is caught at build time,
  not deep inside the orchestrator on the first event.
- `bind_azure_llm_bindings` grows a `judge_system_prompt`
  parameter matching the Wave 4 beta-2 `critic_system_prompt`
  shape. Judge binds when the `t1.judge` capability resolves AND
  the prompt is supplied. When BOTH `critic_model` AND
  `judge_model` land, a default
  `DebateOrchestrator(critic, judge, DebateOrchestratorConfig(max_rounds=1))`
  is auto-constructed.
- `__main__._finalize_llm_bindings` composes the Judge system
  prompt via `composer.compose(capability_id="t1.judge")` with
  `LookupError`-graceful degradation (mirror of the Critic path):
  emits `judge_prompt_composed` on success or `judge_prompt_missing`
  when the catalog has no Judge base prompt.
- Five tests in `tests/test_composition_llm.py` pin the four-way
  matrix (both / critic only / judge only / neither) plus the
  manual-construction rejection: (a) both capabilities + both
  prompts -> orchestrator built; (b) judge cap only ->
  orchestrator None; (c) critic cap only -> orchestrator None;
  (d) both caps but no judge prompt -> orchestrator None; (e)
  `LlmBindings(...debate_orchestrator=orch, critic_model=None...)`
  raises at construction.
- No behaviour change on the live T2 path yet. The bound
  orchestrator sits in `LlmBindings.debate_orchestrator` waiting
  for the Wave 4.5 delta-2 caller (a router or a strategy pattern
  on the QualityGate) to decide which events to route through it.

## Wave 4.5 delta-2a - what shipped

Wave 4.5 delta-2a lands the **pure routing policy** that Wave 4.5
delta-2b will wire into the live `QualityGate`. Shipping the
predicate + config first (no `QualityGate` changes, no live wire)
lets a fork exercise the routing matrix in shadow probes and lets
the promotion gate collect signal before any event actually flows
through the debate.

- `src/fdai/core/quality_gate/debate_router.py` -
  `DebateRoute` (`debate` / `skip`) enum,
  `DebateRoutingDecision` (route + reason + snapshotted
  ``action_type`` + metadata) frozen dataclass,
  `DebateRouterConfig` (`enabled` killswitch,
  `on_cross_check_disagreement` axis,
  `always_for_action_types` / `never_for_action_types`
  allow / deny lists) with `__post_init__` that refuses
  overlapping allow / deny sets, and the pure
  `decide_debate_route(...)` predicate.
- Six-rule precedence baked into the tests:
  1. `orchestrator_available=False` -> SKIP with reason
     `orchestrator_unavailable` (fail-closed - dominates every
     other axis including the allowlist);
  2. `config.enabled=False` -> SKIP with reason `disabled`
     (killswitch - dominates the allowlist);
  3. Candidate `action_type` in `never_for_action_types` -> SKIP
     with reason `never_list` (denylist wins over allowlist so
     a fork's guardrail is not silently overridden by another
     fork's opt-in list);
  4. Candidate `action_type` in `always_for_action_types` ->
     DEBATE with reason `always_list`;
  5. Cross-check disagreed AND
     `on_cross_check_disagreement=True` -> DEBATE with reason
     `cross_check_disagreement` (the primary trigger);
  6. Otherwise -> SKIP with reason `default_skip`.
- Kept `core/`-safe: imports only from
  `fdai.core.quality_gate.gate` and stdlib; no
  `delivery.*`, no LLM SDK. `scripts/check-core-imports.sh`
  continues to pass.
- 11 tests in `tests/quality_gate/test_debate_router.py` cover
  every precedence rule + the config's overlap validator + the
  `action_type` snapshot (a future ActionType rename never breaks
  a past audit entry).

## Wave 4.5 delta-2b - what shipped

Wave 4.5 delta-2b lands the live wire: `QualityGate.evaluate()`
now consults the debate orchestrator on cross-check disagreement.
The wire is fully opt-in - the constructor keeps its historical
shape when no debate params are passed, so every existing
`QualityGate` caller stays behavior-identical.

- `QualityGate.__init__` grows two matched optional parameters -
  `debate_orchestrator` and `debate_router_config`. Passing only
  one of the two raises `ValueError("...MUST be provided
  together...")` at construction, so a fork wiring bug fails
  fast rather than silently on the first disagreement.
- `evaluate()` captures the primary cross-check model's full
  `(action_type, params)` output during the quorum loop so the
  orchestrator has the Proposer's proposal to hand to the
  Critic.
- On `cross_check_below_quorum`, when both debate seams are
  wired, the gate calls
  `decide_debate_route(cross_check_disagreed=True,
  orchestrator_available=True, ...)` and appends the router's
  `route + reason` to the audit trail as
  `debate_route:{value}:{reason}`.
- On `DebateRoute.DEBATE`, the gate awaits
  `orchestrator.run(candidate, proposer_output, known_rule_ids,
  retry_proposer=self._debate_retry_proposer)`; the outcome is
  logged as `debate_outcome:{verdict}:{reason}`.
- `_debate_retry_proposer(candidate, directive)` is a no-directive
  callback that re-invokes the primary cross-check model with
  the same candidate. The `CrossCheckModel` Protocol does not
  accept a directive; the retry acts as "give the Proposer one
  more chance under the same conditions" rather than steering
  toward a specific change. The directive stays in the debate
  transcript for audit.
- Outcome logic:
  - `PROCEED` **flips the disagreement** - the gate returns
    `ELIGIBLE` provided no other soft issues remain (verifier
    abstain, missing / ungrounded citation, low confidence);
  - `ABORT` **keeps the disagreement** - the gate returns
    `DISAGREE` and the orchestrator's reason is threaded into
    the audit trail;
  - `PROCEED` with other soft issues **degrades to `ABSTAIN`**
    - the debate is one axis; every other check still applies.
- Deferred imports (`from fdai.core.quality_gate.debate
  import DebateVerdict`, `from
  fdai.core.quality_gate.debate_router import DebateRoute,
  decide_debate_route`) live inside `evaluate()` to break the
  module-level cycle (both `debate` and `debate_router` import
  `QualityCandidate` from `gate`).
- 7 tests in `tests/core/quality_gate/test_gate.py` cover:
  half-wiring rejection (2), `PROCEED` -> `ELIGIBLE` (1),
  `ABORT` on Critic HIGH-severity keeps `DISAGREE` (1), router
  killswitch prevents orchestrator call (1), `PROCEED` +
  low-confidence degrades to `ABSTAIN` (1), Judge
  `ESCALATE_HIL` keeps `DISAGREE` (1). Existing 17 QualityGate
  tests pass unchanged - the wire is truly additive.

## Wave 5 alpha - what shipped

Wave 5 alpha lands the upstream **seam** for web search: types,
Protocol, deny-by-default fake, and sanitizer defenses. Concrete
providers (Bing, SerpAPI, curated crawler) stay fork-only per the
[Web search policy](#web-search-policy); this step ships the
contract every future adapter honors.

- `src/fdai/core/web_search/types.py` -
  `WebSearchQuery` (frozen dataclass with `__post_init__` refusing
  blank text, zero max_results, zero budget_ms; caller-supplied
  `allowed_domains` tuple + `metadata`),
  `WebSnippet` (immutable record with `url` / `domain` / `title` /
  `text` / `content_hash` / `fetched_at`; blank url / domain /
  content_hash rejected at construction),
  `WebSearchResult` (frozen envelope carrying the originating
  query, retrieved snippets, and audit-friendly `reasons` tuple
  so an operator sees why the search degraded).
- `src/fdai/core/web_search/provider.py` -
  `WebSearchProvider` `@runtime_checkable` Protocol with a single
  async `search(query) -> WebSearchResult` method (secrets like
  API keys stay in adapter constructors, out of the Protocol
  surface), and `NoOpWebSearchProvider` - the deny-by-default
  shipped fake that returns `snippets=()` with
  `reasons=("no_op_provider",)` for every query.
- `src/fdai/core/web_search/sanitizer.py` -
  `WebSnippetPolicyError` with structured codes (`off_allowlist`,
  `empty_allowlist`, `injection_markers_detected`),
  `detect_snippet_injection_markers()` that reuses the
  operator-memory marker list so any pattern blocked from memory
  is blocked from snippets too, `validate_snippet_domain()` that
  refuses off-allowlist snippets AND empty allowlists (an empty
  allowlist means the snippet has no legitimate source), and
  `wrap_web_snippet()` that renders a
  `<web_snippet trusted="false" url="..." domain="..." content_hash="...">...</web_snippet>`
  envelope with XML-escaped body + attributes so a snippet cannot
  forge the closing tag.
- Kept `core/`-safe: imports only from stdlib and
  `fdai.core.operator_memory.sanitizer` (for the shared
  marker list). No LLM SDK, no `delivery.*`.
  `scripts/check-core-imports.sh` continues to pass.
- 19 tests in `tests/core/web_search/test_web_search.py` cover
  every constructor invariant (4 + 3), NoOp provider behaviour +
  Protocol runtime-check (2), domain allowlist enforcement (3),
  injection detection (2), and `wrap_web_snippet` (5 - including
  XML-escape of body + url, off-allowlist refusal, and injection
  marker rejection).

## Related docs

| To learn about | Read |
|----------------|------|
| Tier boundaries and quality gate | [llm-strategy.md](../architecture/llm-strategy.md) |
| Trust routing and control loop | [../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
| Human override policy this design extends | [../../.github/instructions/architecture.instructions.md#human-override](../../../.github/instructions/architecture.instructions.md#human-override) |
| Safety invariants and coding conventions | [../../.github/instructions/coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) |
| Prompt-injection threat model | [security-and-identity.md](../architecture/security-and-identity.md) |
| Rule catalog and provenance rule | [rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md) |
