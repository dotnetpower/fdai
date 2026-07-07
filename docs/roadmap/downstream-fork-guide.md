---
title: Downstream Fork Guide
---

# Downstream Fork Guide

How to fork this repo, keep the fork clean, and customize per customer.
This is the single entry point for **fork maintainers** - engineers
who take the upstream FDAI and adapt it to one specific
deployment (a customer tenant, a compliance regime, or a proof-of-
concept environment).

The upstream repo is deliberately generic and customer-agnostic
([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).
A fork is where every customer-specific value, rule, adapter, and
secret lives. The rules below exist so a fork can sync with
upstream without conflict pain and so upstream sees zero
customer values.

Prerequisites: read
[project-structure.md § Customization via Dependency Injection](project-structure.md#customization-via-dependency-injection)
first for the DI seam catalog, plus
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)
for the T0/T1/T2 trust router and quality-gate concepts referenced
throughout this guide. This document turns those references into
procedural recipes.

**Contents**

1. [Fork model at a glance](#1-fork-model-at-a-glance)
2. [Day-1 checklist](#2-day-1-checklist)
3. [The one hard rule](#3-the-one-hard-rule)
4. [Repo layout for a fork](#4-repo-layout-for-a-fork)
5. [Seam recipes](#5-seam-recipes)
   (LLM · OperatorMemoryStore · HilRejectMaterializer · WebSearch ·
   HilChannel · ScopeResolver · Critic+Judge · Rule catalog · Rego
   overlays · Runtime failure modes · Testing end-to-end)
6. [Upstream sync + version-pinning strategy](#6-upstream-sync-procedure)
7. [Anti-patterns](#7-anti-patterns)
8. [Where to go next](#8-where-to-go-next)

**Recurring terms.** "Deny-by-default fake" = an upstream in-memory
Protocol implementation that returns empty / rejected on every call
(e.g., `NoOpWebSearchProvider`, `InMemoryHilChannel`), so a fork that
forgets to bind a real adapter fails safe rather than silently opening
a hole. "Shadow-before-enforce" = the invariant that every new
ActionType ships with `default_mode: shadow` (judge and log only, no
execution) and is promoted to `enforce` only after its declared
`promotion_gate` is measured green - defined in
[coding-conventions.instructions.md § Safety](../../.github/instructions/coding-conventions.instructions.md#safety).

## 1. Fork model at a glance

- **Upstream** = this repository. Ships the generic control plane
  (core engine, DI seams, deny-by-default fakes, catalog schemas).
- **Fork** = a separate repository the customer team owns. Contains
  the tenant identity, secret refs, allowlists, per-customer rules,
  and any concrete adapters the deny-by-default fakes replace.
- **Direction of contribution**: upstream never pulls from a fork.
  A fork pulls from upstream `main` for improvements. When a fork
  produces a change that would be useful for every customer, the
  change is **scrubbed of customer values** and shipped as a
  standalone upstream PR.

## 2. Day-1 checklist

Do these before your first `git commit` on the fork.

1. **Confirm the baseline is green on your fresh clone**:
   `uv sync` then `uv run pytest -q`. If the upstream test suite
   fails on an untouched checkout, stop and diagnose before adding
   any fork code - the fork must never inherit a red baseline.
2. **Clone with a distinct default branch name** (optional but
   recommended): `fork/main` or `customer-x/main` so no `git push`
   accidentally targets upstream.
3. **Verify `git remote -v`**: `origin` MUST point at your fork
   repository, NOT at `dotnetpower/fdai`. Getting this wrong
   once has a chance of leaking customer commits upstream.
4. **Enable secret scanning** in the fork's CI - reuse the upstream
   `scripts/check-english-only.sh`, `scripts/check-punctuation.sh`,
   `scripts/check-guids.sh`, `scripts/check-core-imports.sh`, and
   `scripts/check-translations.sh`. **These are not sufficient on
   their own.** `check-guids.sh` matches the `8-4-4-4-12` hex shape
   only; it does not know about your customer's resource names,
   endpoints, bearer-token prefixes, or short account ids. Add
   fork-specific regex patterns (a `check-customer-tokens.sh` in
   the same style) covering: resource-name prefixes your customer
   uses (`acme-prod-*`), hostname suffixes (`*.customer.example`),
   API token prefixes if any (`sk-...`, `xoxb-...`, `Bearer eyJ`),
   and short account ids (12-digit AWS, 6-hex GCP project prefix).
   Run an OSS secret scanner (`gitleaks`, `trufflehog`) alongside.
5. **Never commit** an Azure tenant / subscription id, a customer
   resource name, an endpoint, or a secret. Load them from
   environment or Key Vault at runtime. Every SDK-family secret
   (API key, connection string, DSN with password) goes through
   `fdai.shared.providers.secret_provider.SecretProvider` -
   the Protocol contract forbids logging or persisting the value.
6. **Create a `fork/` (or `customer/`) top-level directory** for
   fork-owned modules. This is where your composition-root override,
   adapters, and rule additions live. `core/` stays 100% upstream.
7. **Register your fork package in `pyproject.toml`**: add your
   `fork/` directory to `[tool.setuptools.packages.find]` (or the
   equivalent for your build backend) and register your process
   entry point under `[project.scripts]`. The upstream `pyproject`
   ships a working baseline; the fork edit is a minimal delta.
8. **Wire your composition root**: a thin Python module that imports
   upstream `default_container(...)` and applies `dataclasses.replace`
   to swap the seams your fork owns. Rename your process entry point
   to import from this module instead of upstream's `__main__`.
9. **Set up upstream sync**: `git remote add upstream
   https://github.com/dotnetpower/fdai.git`. Rehearse the
   [Upstream sync procedure](#upstream-sync-procedure) once before
   the first divergence.

## 3. The one hard rule

**Never edit files under `src/fdai/core/`.** Everything a
fork wants to customize has a seam. If you find yourself wanting to
edit `core/`, one of two things is happening:

1. You are trying to inject a value that belongs in configuration
   or a fake. Find the seam that already exists.
2. You have found a genuine gap in the upstream design. Open an
   upstream issue OR ship your change as a fork-local wrapper that
   composes around `core/` without patching it. Then contribute
   the wrapper upstream, scrubbed.

The rule is enforced by two invariants:

- Upstream's `scripts/check-core-imports.sh` refuses any `core/`
  file that imports from `delivery/*` or from a cloud SDK.
- The composition root
  ([`src/fdai/composition.py`](../../src/fdai/composition.py))
  is the only place where concrete implementations bind to
  Protocols in `shared/providers/`. A fork writes its own
  composition root; it does not edit this file.

## 4. Repo layout for a fork

Recommended shape:

```
customer-x-fork/
  fork/
    __init__.py
    composition_root.py    # calls upstream default_container() + replace()
    entry.py               # customer process entry (was __main__.py upstream)
    adapters/
      web_search.py        # concrete WebSearchProvider
      hil_channel.py       # concrete HilChannel (Teams / Slack)
      scope_resolver.py    # ARM-id -> OperatorScope parser
    rules/
      customer.yaml        # per-customer rule catalog additions
    overlays/
      risk_gate.rego       # per-customer risk ceiling overlays
  <upstream tree, unchanged>
```

Everything under `fork/` is customer-owned. Upstream files remain
byte-identical except for `pyproject.toml` (a fork MAY add its own
package + entry point).

## 5. Seam recipes

Each recipe follows the same shape: **when to override**, **the
seam**, **how to bind**, **how to test**. All snippets assume Python
3.12+ and the upstream package is importable as `fdai`.

### 5.1 Azure OpenAI adapters (LlmBindings)

**When to override**: pointing at a different Azure OpenAI endpoint,
a different set of deployments, or a non-Azure LLM provider.

**The seam**: `fdai.composition.LlmBindings` holds
`embedding_model`, `cross_check_models`, `critic_model`,
`judge_model`, and `debate_orchestrator`. The upstream
`bind_azure_llm_bindings()` factory reads `resolved-models.json` and
wires Azure OpenAI adapters.

**`resolved-models.json` is a runtime secret, not a checked-in
artifact.** It is produced by the bootstrap `llm_resolver_cli`
(see 5.7), stored in Key Vault, and mounted at the container path
named by `LLM_RESOLVED_MODELS_PATH` (e.g.
`/mnt/secrets/resolved-models.json`). A fork MUST NOT commit this
file: it embeds the deployer's subscription id, deployment names,
and region metadata. Regenerate it when the llm-registry, quota,
or region availability changes; the resolver is idempotent -
re-running it with unchanged inputs produces the same file.

**How to bind (Azure endpoint override)**:

Upstream ships a **public composition API** for the full Azure wire-
up: [`wire_azure_container`](../../src/fdai/composition.py) +
the declarative [`AzureWireOverrides`](../../src/fdai/composition.py)
dataclass. A fork constructs one `AzureWireOverrides` with its
concrete adapters and passes it in - the function handles the
composer, tool registry, prompt composition (base / critic / judge),
and the underlying `bind_azure_llm_bindings()` call in one step.

```python
# fork/composition_root.py
from pathlib import Path
from fdai.composition import (
    AzureWireOverrides, default_container, wire_azure_container,
)
from fdai.core.operator_memory import InMemoryOperatorMemoryStore
from fork.adapters.scope_resolver import resolve_azure_scope

async def build_container(config, *, identity, http_client):
    container = default_container(config)
    return await wire_azure_container(
        container,
        http_client=http_client,
        identity=identity,
        overrides=AzureWireOverrides(
            endpoint="https://oai-customer-x.openai.azure.com",
            catalog_root=Path("rule-catalog"),
            operator_memory_store=InMemoryOperatorMemoryStore(),
            scope_resolver=resolve_azure_scope,   # fork-owned (see 5.6)
            # tool_providers=... to light up function calling (see below)
        ),
    )
```

The `AzureWireOverrides` `__post_init__` fail-closes on an empty
`endpoint` or a `None` `operator_memory_store` so the fork bug is
caught at construction time, not deep inside the composer on the
first event. A fork that does not use operator memory MUST still
pass `InMemoryOperatorMemoryStore()` explicitly - the API refuses
to default a required seam.

**Backwards compatibility**: upstream's `__main__._finalize_llm_bindings`
is now a thin wrapper that reads env vars (`FDAI_LLM_ENDPOINT`,
`FDAI_CATALOG_ROOT`, `FDAI_OPERATOR_MEMORY_DSN`) and
delegates to `wire_azure_container`. Existing tests and the
upstream entry point continue to work unchanged. A fork that
prefers env-driven wiring MAY call the wrapper; a fork that wants
programmatic composition uses `wire_azure_container` directly.

**How to bind (non-Azure LLM)**: implement the four Protocols
(`EmbeddingModel`, `CrossCheckModel`, `CriticModel`, `JudgeModel`),
construct an `LlmBindings` directly, and swap it in:

```python
new_bindings = LlmBindings(
    embedding_model=MyBedrockEmbeddings(),
    cross_check_models=(MyProposer(), MyDoubleChecker()),
)
return replace(container, llm_bindings=new_bindings)
```

**How to test**: reuse the upstream in-memory fakes
(`MatchTypeCrossCheckModel`, `DeterministicEmbeddingModel`) for
unit tests; run your live adapters against
`httpx.MockTransport` for wire-level checks (see
`tests/delivery/azure/llm/test_adapters.py`).

### 5.2 OperatorMemoryStore (in-memory / Postgres / custom)

**When to override**: switching from the shipped `InMemoryOperatorMemoryStore`
to durable storage.

**The seam**: `fdai.core.operator_memory.OperatorMemoryStore`
Protocol with three async methods: `append`, `list_active_for_scope`,
`supersede`.

**How to bind (Postgres)**: set the `FDAI_OPERATOR_MEMORY_DSN`
environment variable; upstream's `_build_operator_memory_store()`
picks `PostgresOperatorMemoryStore` automatically. No code change
needed.

**How to bind (custom store)**: implement the Protocol, pass the
instance into `DefaultPromptComposer(operator_memory_store=...)` at
your composition root.

**How to test**: reuse `InMemoryOperatorMemoryStore` in unit tests;
if you shipped a custom store, mirror the shape of
`tests/persistence/test_postgres_operator_memory.py` (offline
policy tests + integration tests gated on a DSN env var).

### 5.3 HilRejectMaterializer + second-approval channel

**When to override**: activating the operator-memory pipeline. The
materializer is a pure domain module shipped by upstream; the
"second approval" channel that triggers it is fork-first because
the UI varies per deployment (Teams button, git PR, custom CLI).

**The seam**: `fdai.core.operator_memory.HilRejectMaterializer`.
Construct it with your `OperatorMemoryStore` and call
`await materializer.materialize(hil_response, second_approver,
material)` from whatever channel your fork uses.

**How to bind (Teams Adaptive Card callback)**:

A Teams webhook delivers raw JSON, not a Python `HilResponse`
object - the callback reconstructs the response from the payload
fields before calling the materializer.

```python
# fork/adapters/hil_second_approval.py
from datetime import UTC, datetime

from fdai.core.operator_memory import (
    HilRejectMaterial, HilRejectMaterializer, MemoryCategory, ScopeKind,
)
from fdai.shared.providers.hil_channel import HilDecision, HilResponse

async def handle_teams_approval_click(payload, *, materializer, second_approver_oid):
    hil_response = HilResponse(
        approval_id=payload["approval_id"],
        decision=HilDecision.REJECT,        # only rejected reasons materialise
        approver_id=payload["first_approver_oid"],
        received_at=datetime.now(tz=UTC),
        reason=payload["reject_reason"],    # pre-redacted upstream
    )
    material = HilRejectMaterial(
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref=payload["resource_group_ref"],
        category=MemoryCategory.PREFERENCE,
        source_ref=f"hil.reject:{payload['approval_id']}",
    )
    return await materializer.materialize(
        hil_response=hil_response,
        second_approver=second_approver_oid,
        material=material,
    )
```

**How to test**: mirror `tests/core/operator_memory/test_hil_pipeline.py`
using `InMemoryOperatorMemoryStore` + a synthetic `HilResponse`.

### 5.4 WebSearchProvider

**When to override**: activating web search. Upstream ships
`NoOpWebSearchProvider` which returns zero snippets on every query,
so a fork that does nothing has web search silently disabled.

**The seam**: `fdai.core.web_search.WebSearchProvider`
Protocol with one async `search(query) -> WebSearchResult` method.

**How to bind (Bing example)**:

**Two allowlists layer**: `query.allowed_domains` (per-event scope,
set by the caller) and `self._deploy_allowlist` (deploy-time
curated primary sources set by the fork's platform team). The
provider MUST return snippets whose `domain` sits in the
**intersection** of both - the query narrows a per-event slice,
the deploy allowlist puts an absolute upper bound.

The Bing API key is a live secret: resolve it through the shipped
`SecretProvider` seam at composition time, never as a checked-in
literal. The provider's Protocol contract forbids logging the
returned string.

```python
# fork/adapters/web_search.py
from fdai.core.web_search import (
    WebSearchProvider, WebSearchQuery, WebSearchResult, WebSnippet
)
from fdai.shared.providers.secret_provider import SecretProvider

class BingWebSearchProvider(WebSearchProvider):
    def __init__(
        self,
        *,
        secret_provider: SecretProvider,
        secret_name: str,
        deploy_allowlist: frozenset[str],
    ) -> None:
        self._secret_provider = secret_provider
        self._secret_name = secret_name
        self._deploy_allowlist = deploy_allowlist  # curated primary sources

    async def search(self, query: WebSearchQuery) -> WebSearchResult:
        api_key = await self._secret_provider.get(self._secret_name)
        # `api_key` is scoped to this call; never log it, never store it
        # on `self`, never include it in a WebSearchResult reasons tuple.
        effective = self._deploy_allowlist & set(query.allowed_domains)
        if not effective:
            return WebSearchResult(
                query=query, reasons=("allowlist_intersection_empty",),
            )
        # 1. POST query.text to Bing API with self._api_key.
        # 2. Drop every hit whose domain is not in ``effective``.
        # 3. Build a WebSnippet tuple, respecting query.max_results and
        #    query.budget_ms as a soft deadline.
        # 4. Return WebSearchResult(query=query, snippets=(...)).
        return WebSearchResult(query=query, snippets=())  # fork fills the body
```

**Every snippet MUST pass through `wrap_web_snippet(snippet=...,
allowed_domains=query.allowed_domains)` before injection into a
model turn** - the shipped sanitizer runs the domain allowlist,
injection-marker detection, and `trusted="false"` XML envelope.

**How to test**: mirror `tests/core/web_search/test_web_search.py`.
The upstream tests cover the sanitizer + `NoOpWebSearchProvider`; a
fork adds its own adapter-level tests using `httpx.MockTransport`.

### 5.5 HilChannel (Teams / Slack / custom)

**When to override**: activating any HIL flow. Upstream ships an
in-memory fake; a real deployment MUST bind a live channel.

**The seam**: `fdai.shared.providers.hil_channel.HilChannel`
Protocol with `send` (dispatch Adaptive Card) and `poll` (observe
decision).

**How to bind**: implement the two methods against Teams Incoming
Webhook / Bot Framework REST / Slack Web API / anything you like.
Pass the instance into your composition root and wire it into the
control loop where HIL approvals are dispatched.

**How to test**: reuse `fdai.shared.providers.testing.hil_channel.InMemoryHilChannel`
for the pipeline tests; add wire-level tests for your adapter with
`httpx.MockTransport`.

### 5.6 ScopeResolver (ARM id -> OperatorScope)

**When to override**: activating operator memory for real events.
Upstream stays CSP-neutral so the parser that turns a
`QualityCandidate.target_resource_ref` into an
`OperatorScope(resource_group_ref, resource_ref)` is fork-first.

**The seam**: a plain callable
`Callable[[QualityCandidate], OperatorScope | None]` passed as
`scope_resolver=` to `bind_azure_llm_bindings()`.

**How to bind**:

```python
# fork/adapters/scope_resolver.py
import re
from fdai.core.operator_memory import OperatorScope
from fdai.core.quality_gate.gate import QualityCandidate

_ARM_RE = re.compile(
    r"^/subscriptions/[^/]+/resourceGroups/(?P<rg>[^/]+)"
    r"(?:/providers/[^/]+/[^/]+/(?P<name>[^/]+))?"
)

def resolve_azure_scope(candidate: QualityCandidate) -> OperatorScope | None:
    match = _ARM_RE.match(candidate.target_resource_ref)
    if match is None:
        return None
    return OperatorScope(
        resource_group_ref=match.group("rg"),
        resource_ref=match.group("name"),  # None when the id stops at the RG
    )
```

Then at your composition root:

```python
return bind_azure_llm_bindings(
    ..., scope_resolver=resolve_azure_scope,
)
```

**How to test**: pure unit tests over your parser (ARM id in,
`OperatorScope` out); no upstream test dependency.

### 5.7 CriticModel + JudgeModel (debate activation)

**When to override**: activating the debate loop.

**The seam**: two capabilities in
[`rule-catalog/llm-registry.yaml`](../../rule-catalog/llm-registry.yaml):
`t2.critic` (already declared by upstream) and `t1.judge` (already
declared). A fork's `resolved-models.json` MUST include both for
`bind_azure_llm_bindings` to auto-construct the
`DebateOrchestrator`.

**How to bind**: run the LLM resolver CLI against your regional
catalog fixture so both capabilities appear in
`resolved-models.json`. The upstream CLI lives at
[`src/fdai/rule_catalog/schema/llm_resolver_cli.py`](../../src/fdai/rule_catalog/schema/llm_resolver_cli.py);
invoke it as `uv run python -m fdai.rule_catalog.schema.llm_resolver_cli
--registry rule-catalog/llm-registry.yaml --region <your-region>
--subscription-id <sub> --deployer-object-id <oid> --catalog-fixture
<fixture.json> --permission-fixture <perm.json> --quota-fixture
<quota.json> --out /path/to/resolved-models.json`. If your region
cannot host one of the capabilities, the capability lands in
`hil-only` status and the orchestrator stays unbound - graceful
degrade.

**Router config**: an opt-in denylist / allowlist of ActionType ids
lives on `DebateRouterConfig`. Construct one at composition time and
pass it to `QualityGate(debate_router_config=...)` alongside the
orchestrator. See
[prompt-composition.md § Wave 4.5 delta-2a](prompt-composition.md#wave-45-delta-2a---what-shipped)
for the precedence rules.

**How to test**: reuse `_StubCritic` / `_StubJudge` patterns from
`tests/core/quality_gate/test_gate.py`. The escalation matrix
(PROCEED / ABORT / router killswitch) is already covered upstream;
a fork's tests focus on its live adapters.

### 5.8 Rule catalog additions

**When to override**: adding customer-specific rules.

**The seam**: `rule-catalog/catalog/` YAML files consumed by
`load_rule_catalog(...)`. A fork ships its own directory (say,
`fork/rules/`) and passes it to a **separate** `load_rule_catalog`
call.

**Duplicate `id` is a hard error**. `load_rule_catalog` fail-
closes on same-id entries across files, even across roots - the
ontology dispatch relies on `id` being globally unique. This
means:

- To ADD a rule: give it a fork-unique id (e.g. prefix with your
  fork's namespace, `customer-x.storage.owner-tag.required`) and
  ship it in `fork/rules/`. This is the only supported case.
  **Managed-service teams maintaining multiple forks** SHOULD adopt a
  two-level convention: `<tenant-code>.<domain>.<name>` where
  `<tenant-code>` is a short opaque code (never the customer name),
  registered once at the top of the fork's rule catalog as a
  reserved namespace. Two forks that pick the same `<tenant-code>`
  are a merge-time id collision, which is why the code should be a
  short random string, not a semantic label.
- To DISABLE an upstream rule: do not ship a same-id override.
  Use the exemption workflow
  ([`rule-catalog/exemptions/`](../../rule-catalog/exemptions/) +
  [`docs/runbooks/exemption-workflow.md`](../runbooks/exemption-workflow.md))
  which is the audited, time-boxed way to suppress a rule for a
  scope.
- To CHANGE an upstream rule's behaviour: open an upstream issue -
  do not fork-patch. The upstream rule catalog is customer-
  agnostic; a customer-specific change to its behaviour is a
  signal the rule needs a config knob upstream.

**How to bind**: extend your composition root to load both catalogs
and concatenate. `load_rule_catalog` returns `tuple[Rule, ...]`:

```python
from pathlib import Path
from fdai.core.tiers.t0_deterministic.index import RuleIndex
from fdai.rule_catalog.schema.rule import load_rule_catalog

upstream_rules = load_rule_catalog(
    Path("rule-catalog/catalog"),
    schema_registry=registry,
    action_types=action_types,
    resource_types=resource_types,
    policies_root=Path("policies"),
    remediation_root=Path("rule-catalog/remediation"),
)
fork_rules = load_rule_catalog(
    Path("fork/rules"),
    schema_registry=registry,
    action_types=action_types,
    resource_types=resource_types,
)
index = RuleIndex.build(upstream_rules + fork_rules)
```

**How to test**: reuse the shipped rule-loader tests as a template
(`tests/rule_catalog/schema/test_rule.py`); add a fork-specific
fixture directory and a smoke test that both catalogs load without
id conflicts.

### 5.9 Risk overlays (Rego)

**When to override**: tightening the RiskGate ceiling per
environment / customer (a Rego overlay can only lower autonomy,
never raise it, per
[execution-model.md § Unified RiskGate](execution-model.md#3-unified-riskgate)).

**Current state**: **the Rego overlay wire is scoped in the
execution-model design but the RiskGate module in
`src/fdai/core/risk_gate/` does not yet load overlay files.**
The two authoritative decision surfaces today are (a) the
ActionType schema's `ceiling_by_tier` block (edit the shipped
ontology YAML directly and open an upstream PR if the change is
customer-agnostic) and (b) `DebateRouterConfig`'s
`always_for_action_types` / `never_for_action_types` (see 5.7).

**Fork guidance until the overlay wire lands**: encode the
intended tighter ceiling as an ActionType-level `ceiling_by_tier`
override in your fork's rule catalog additions (5.8), OR use the
`never_for_action_types` denylist on `DebateRouterConfig` to block
debate promotion for the ActionType entirely.

**Tracking**: the overlay wire is planned as a follow-up to Wave
4.5 delta-2b; when it lands this section will document the
`RiskGate(overlay_path=...)` binding.

### 5.10 Runtime failure modes and abstain contracts

Every seam has a documented behaviour when its live adapter fails
at runtime. A fork's adapters MUST honour these contracts so the
control loop degrades to HIL rather than into an ungated action.

| Seam | Live adapter fails | Expected behaviour |
|------|--------------------|--------------------|
| `EmbeddingModel` / `CrossCheckModel` | HTTP error, timeout | Raise; upstream catches and abstains the quality candidate (HIL). Never return a synthesised empty response. |
| `CriticModel` / `JudgeModel` | HTTP error, quota | Raise; `DebateOrchestrator` catches and returns `debate_status="unresolved"` which routes to HIL. |
| `WebSearchProvider` | HTTP error, timeout | Return `WebSearchResult(query=query, snippets=(), reasons=("<provider-error>",))`. Do not raise - snippets are supplementary evidence, not a gate. |
| `HilChannel.send` | Delivery fails | Raise; upstream logs and the audit trail marks the approval as `dispatch_failed`. The action stays pending; no auto-execute. |
| `HilChannel.poll` | Backend unreachable | Raise; upstream keeps the approval in `pending` on next tick. |
| `OperatorMemoryStore` | DB down at write | Raise; the materializer rolls back the second-approver record and the reject stays as an audit-only event. |
| `OperatorMemoryStore` | DB down at read | Return `()`; the composer proceeds with an empty operator-memory block. Prompt composition MUST survive an empty store. |
| `SecretProvider.get` | Secret missing / KV down | Raise `SecretNotFoundError`; startup fails fast. A missing secret is never silently defaulted. |
| `ScopeResolver` | Cannot parse the resource ref | Return `None`; the materializer skips operator-memory attachment for that event but the action itself is not blocked. |

The common invariant: **never fabricate a success on a live-adapter
error**. If the fork's adapter cannot honour the contract row above,
escalate to HIL at the earliest observable point.

### 5.11 Testing your fork end-to-end

A fork's test suite has two roles: (a) prove the fork's live
adapters honour their Protocols, (b) prove upstream contracts still
hold after any composition-root changes. Keep the two separated so
CI can triage which side broke.

**Recommended layout**:

```
fork/
  tests/
    adapters/        # wire-level tests for your live adapters
    composition/     # tests that exercise your composition_root end-to-end
    contract/        # thin Protocol conformance tests (see below)
```

**Protocol conformance test pattern** - for every seam your fork
replaces, write a one-page test that instantiates your adapter with
test doubles and asserts it satisfies the Protocol shape at
runtime:

```python
from fdai.core.web_search import WebSearchProvider

def test_bing_provider_is_websearch_protocol():
    provider = BingWebSearchProvider(
        secret_provider=StubSecretProvider({"bing": "test"}),
        secret_name="bing",
        deploy_allowlist=frozenset({"example.com"}),
    )
    assert isinstance(provider, WebSearchProvider)  # runtime_checkable
```

**Running both suites**:

```bash
uv run pytest -q tests/ fork/tests/       # full CI run
uv run pytest -q tests/                   # upstream contract regression only
uv run pytest -q fork/tests/              # fork adapter check only
```

**Inherit pytest-asyncio auto-mode** in your fork's `pyproject.toml`
under `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`. Upstream
sets this to keep async seam tests marker-free; a fork that omits it
will see mysterious "async function not awaited" warnings.

## 6. Upstream sync procedure

The fork stays healthy by pulling upstream `main` on a schedule
(weekly is a good default). Because a fork never edits `core/` and
never commits customer values, merges are typically clean.

### 6.1 Version-pinning strategy

"Track upstream `main` weekly" is aspirational; in practice a fork
SHOULD pin to a **known-good upstream ref** and advance the pin
deliberately. Two acceptable strategies:

1. **Pin to a tag** (recommended). Upstream cuts semver-adjacent
   tags at milestone boundaries. The fork's `pyproject.toml`
   dependency on the upstream package (if it uses one) or the
   fork's `git subtree` / submodule pointer references that tag.
   Advancing the pin is a reviewed PR: read the upstream CHANGELOG,
   run the fork test suite, then advance.
2. **Pin to a SHA on `upstream/main`** with a stated cadence. Same
   idea, coarser granularity. Suitable while upstream is pre-1.0.

**Breaking Protocol changes**. Any upstream change that alters a
seam Protocol's method signature is treated as a breaking change
even if not tagged as such. The upstream policy is to ship the new
Protocol alongside the old one for one release, then remove the
old; a fork should complete the migration within that window.
Watch `src/fdai/shared/providers/**` and
`src/fdai/composition.py` diffs on every sync.

### 6.2 Sync workflow

```bash
# One-time setup
git remote add upstream https://github.com/dotnetpower/fdai.git

# Every sync
git fetch upstream --tags
git checkout main
git merge upstream/main            # or rebase - team choice
# Resolve conflicts (usually zero if the fork rule is honored)
./scripts/check-english-only.sh    # sanity gates
./scripts/check-translations.sh
uv run pytest -q tests/ fork/tests/  # full suite
git push origin main
```

If a merge lands a conflict inside `core/`, that is a signal your
fork has silently violated the hard rule. Revert the fork-side
edit, move the change into your composition root or an adapter, and
re-run the sync.

## 7. Anti-patterns

Hard don'ts. Any of these is a merge-blocker:

- **Committing an Azure tenant id, subscription id, resource name,
  endpoint, or secret** anywhere in the fork. Load them from
  environment or Key Vault via `SecretProvider`. Upstream's
  `check-guids.sh` only catches the `8-4-4-4-12` GUID shape - it
  does not catch customer resource names, hostnames, or bearer
  tokens. The fork MUST layer its own regex gate + an OSS secret
  scanner (see §2 item 4).
- **Modifying files under `src/fdai/core/**` or
  `src/fdai/composition.py` in place**. A fork MUST `import`
  from these modules (that is the whole point of the seams), but
  MUST NOT edit them. Every customization goes through
  `dataclasses.replace()` on a container returned by
  `default_container(...)`. See
  [The one hard rule](#3-the-one-hard-rule).
- **Editing `rule-catalog/schema/**`**. Extend by adding new
  catalog entries under a fork-unique id namespace, not by widening
  the schema.
- **Disabling upstream tests to make a green CI**. If an upstream
  test blocks your fork, that is a signal upstream needs a design
  change - open an issue.
- **Auto-executing a fork-added action without shadow mode first**.
  The shadow-before-enforce invariant applies to every fork-added
  ActionType exactly as it does to upstream ones.
- **Contributing back a change that carries customer identity**.
  Every upstream PR from a fork MUST be scrubbed of customer names,
  ids, endpoints, and any private dataset references.
- **Committing a `-ko.md` translation without updating the paired
  English source's `translation_source_sha`**. The upstream
  `check-translations.sh` gate applies to fork-added user-facing
  docs too.

## 8. Where to go next

- [project-structure.md § Customization via Dependency Injection](project-structure.md#customization-via-dependency-injection) -
  the DI seam catalog this guide operationalizes.
- [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) -
  the T0/T1/T2 trust router, quality gate, risk gate, and the
  living-rules discovery loop the fork's rules feed into.
- [coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md) -
  safety invariants, shadow-mode default, async-Protocol contracts,
  and the docs-first + docs-after rule the fork inherits.
- [deploy-and-onboard.md](deploy-and-onboard.md) - the Azure
  resource inventory a fork provisions (Container Apps, Event Hubs,
  Postgres, Key Vault, ...).
- [prompt-composition.md](prompt-composition.md) - the full design
  of the evolving system prompt (Base + Task Pack + Tool Manifest +
  Operator Memory + Debate).
- [csp-neutrality.md](csp-neutrality.md) - how a fork replaces the
  Azure resource layer with an alternative implementation.
- [`docs/runbooks/`](../runbooks/) - the operational procedures a
  fork's on-call runs (exemption workflow, HIL escalation,
  rollback, incident replay). Fork-specific runbooks live under
  `fork/runbooks/` and reference these upstream templates.
- [generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md) -
  the customer-agnostic scope contract every fork honors.
