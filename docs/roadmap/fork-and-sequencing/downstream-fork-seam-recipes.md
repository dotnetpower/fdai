---
title: Fork Seam Recipes
---

# Fork Seam Recipes

Cookbook of per-seam recipes for a downstream FDAI fork. Each entry
follows the same shape: **when to override**, **the seam**, **how
to bind**, **how to test**. All snippets assume Python 3.12+ and
the upstream package is importable as `fdai`.

This file is a companion to
[downstream-fork-guide.md](downstream-fork-guide.md), which owns
the fork model, Day-1 checklist, one-hard-rule, repo layout,
upstream sync, and anti-patterns. If you have not read that hub
first, start there - the recipes below assume the fork's
composition root and repo layout already follow the guide.

For a full "new business-object vertical from scratch" walkthrough
that stitches these recipes together, see
[downstream-fork-example-vertical.md](downstream-fork-example-vertical.md).

### 5.1 Azure OpenAI adapters (LlmBindings)

**When to override**: pointing at a different Azure OpenAI endpoint,
a different set of deployments, or a non-Azure LLM provider.

**The seam**: `fdai.composition.LlmBindings` holds
`embedding_model`, `cross_check_models`, `critic_model`,
`judge_model`, and `debate_orchestrator`. The upstream
`bind_azure_llm_bindings()` factory reads `resolved-models.json` and
wires Azure OpenAI adapters.

**Live `resolved-models.json` is a deployment artifact.** The bootstrap resolver emits it, and
`LLM_RESOLVED_MODELS_PATH` accepts a filesystem path or inline JSON. Never commit a live result:
it carries deployer/subscription/deployment/region provenance. Upstream's tracked
`resolved-models*.json` files are synthetic generated baselines with all-zero identities and must
not be hand-edited. A direct Key Vault loader is deferred with the reconciler; day zero uses a
secretRef env value or mounted file.

**How to bind (Azure endpoint override)**:

Upstream ships a **public composition API** for the full Azure wire-
up: [`wire_azure_container`](../../../src/fdai/composition/__init__.py) +
the declarative [`AzureWireOverrides`](../../../src/fdai/composition/__init__.py)
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

**Backwards compatibility**: upstream's `runtime.configuration._finalize_llm_bindings`
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

**Control-loop wiring (upstream-assisted)**: `__main__` auto-binds a
`HilResumeCoordinator` (park the action + push an A1 approval card) as
soon as `FDAI_CHATOPS_WEBHOOK_URL` is set - a fork supplies only the
webhook, no code change. For A2 operational-alert push on every terminal
decision, assemble a `NotificationRouter` (`fdai.core.notifications`)
from your channel adapters (`fdai.delivery.notifications.*`), the
upstream `StateStoreHilEscalationSink` (the `on_all_fail` fail-safe
queue), and your matrix override (real channel ids for the placeholders
in `config/notifications-matrix.yaml`), then pass it as
`notification_router=` into the control loop.

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
[`rule-catalog/llm-registry.yaml`](../../../rule-catalog/llm-registry.yaml):
`t2.critic` (already declared by upstream) and `t1.judge` (already
declared). A fork's `resolved-models.json` MUST include both for
`bind_azure_llm_bindings` to auto-construct the
`DebateOrchestrator`.

**How to bind**: run the LLM resolver CLI against your regional
catalog fixture so both capabilities appear in
`resolved-models.json`. The upstream CLI lives at
[`src/fdai/rule_catalog/schema/llm_resolver_cli.py`](../../../src/fdai/rule_catalog/schema/llm_resolver_cli.py);
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
[prompt-composition.md § Wave 4.5 delta-2a](../decisioning/prompt-composition.md#wave-45-delta-2a---what-shipped)
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

**Duplicate `id` is a hard error**. `load_rule_catalog` rejects duplicates within one root;
`RuleIndex.build` rejects cross-root duplicates after concatenation. The ontology dispatch relies
on globally unique ids. This
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
  ([`rule-catalog/exemptions/`](../../../rule-catalog/exemptions) +
  [`docs/runbooks/exemption-workflow.md`](../../runbooks/exemption-workflow.md))
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

`RuleIndex.build` is the final cross-root uniqueness check. A consumer that doesn't build the
index must perform the same id check over the combined tuple.

**How to test**: reuse the shipped rule-loader tests as a template
(`tests/rule_catalog/test_rule_catalog.py`); add a fork-specific
fixture directory and a smoke test that both catalogs load without
id conflicts.

### 5.8a Ontology ObjectType / LinkType additions

**When to override**: adding a first-class business object that is
not a `Resource` - for example, an architecture-review proposal, a
change ticket, a compliance-attestation record. If your fork only
customizes rules against existing Resource subtypes, skip this
section; 5.8 alone is enough.

**The seams**:
- `fdai.rule_catalog.schema.object_type.load_object_type_catalog(root, *, schema_registry)`
- `fdai.rule_catalog.schema.link_type.load_link_type_catalog(root, *, schema_registry, object_types=...)`

Both return immutable tuples validated against the shipped JSON Schemas and pydantic models. Each
loader rejects duplicates within its own root. The composition root must separately validate
cross-root name uniqueness before combining upstream and fork tuples.

**How to add a new ObjectType**:

1. Ship one YAML per ObjectType under a fork-local directory (e.g.
   `fork/vocabulary/object-types/GovernanceProposal.yaml`). Follow
   the shipped built-ins under
   [`rule-catalog/vocabulary/object-types/`](../../../rule-catalog/vocabulary/object-types)
   for shape. `name` is PascalCase (`^[A-Z][A-Za-z0-9]{0,63}$`);
   `key` MUST name a declared property.
2. Ship one YAML per LinkType under `fork/vocabulary/link-types/`
   (e.g. `assigned_reviewer.yaml`). `from_type` / `to_type` MUST
   resolve against the combined ObjectType registry (upstream +
   fork); the loader fails-closed on a typo. `name` is snake_case
   (`^[a-z][a-z0-9_]{0,63}$`).
3. Load both roots at your composition root and inject via
   `dataclasses.replace`:

   ```python
   from dataclasses import replace
   from pathlib import Path

   from fdai.rule_catalog.schema.object_type import load_object_type_catalog
   from fdai.rule_catalog.schema.link_type import load_link_type_catalog

   upstream_objects = load_object_type_catalog(
       Path("rule-catalog/vocabulary/object-types"),
       schema_registry=registry,
   )
   fork_objects = load_object_type_catalog(
       Path("fork/vocabulary/object-types"),
       schema_registry=registry,
   )
   objects = upstream_objects + fork_objects
     object_names = [item.name for item in objects]
     if len(object_names) != len(set(object_names)):
       raise ValueError("duplicate ObjectType name across upstream and fork roots")

   upstream_links = load_link_type_catalog(
       Path("rule-catalog/vocabulary/link-types"),
       schema_registry=registry,
       object_types=objects,
   )
   fork_links = load_link_type_catalog(
       Path("fork/vocabulary/link-types"),
       schema_registry=registry,
       object_types=objects,
   )
     links = upstream_links + fork_links
     link_names = [item.name for item in links]
     if len(link_names) != len(set(link_names)):
       raise ValueError("duplicate LinkType name across upstream and fork roots")
   container = replace(
       container,
       ontology_object_types=objects,
       ontology_link_types=links,
   )
   ```

**Rule dispatch caveat**: the shipped `Rule.resource_type` field is
cross-checked against the `ResourceType` registry (a subtype registry
of the `Resource` ObjectType) at load time. A rule that targets a
non-Resource ObjectType requires either:

- modeling your business object's subtypes as ResourceType entries so
  the existing dispatch works (works fine for many governance flows),
  OR
- opening an upstream issue to generalize `Rule.applies_to` beyond
  the Resource ObjectType. Do NOT fork-patch the rule loader; the
  cross-reference is the safety boundary that catches typos at load.

**How to test**: mirror
`tests/rule_catalog/test_object_type_catalog.py` and
`tests/rule_catalog/test_link_type_catalog.py`. A fork's tests focus
on the joint load (upstream + fork roots) plus one assertion that
each new ObjectType is dispatchable by whatever consumer needs it
(assurance twin, operator console, custom delivery adapter).

**Working reference**: upstream ships `ChangeSummary` (see
[`rule-catalog/vocabulary/object-types/ChangeSummary.yaml`](../../../rule-catalog/vocabulary/object-types/ChangeSummary.yaml))
and its `summarizes` LinkType (see
[`rule-catalog/vocabulary/link-types/summarizes.yaml`](../../../rule-catalog/vocabulary/link-types/summarizes.yaml))
as a copy-ready reference for a fork's first business ObjectType. The
full scaffold is walked in
[downstream-fork-example-vertical.md](downstream-fork-example-vertical.md).

**Anti-patterns**:
- Editing shipped `rule-catalog/vocabulary/object-types/*.yaml` -
  changes to a built-in ObjectType go upstream, not into a fork.
- Loading only your fork root - the LinkType loader validates
  endpoints against the *combined* registry, so a fork LinkType
  that points at a built-in ObjectType (e.g. `assigned_reviewer:
  Reviewer -> Resource`) fails-closed when upstream is missing.

### 5.9 Risk overlays (Rego)

**When to override**: tightening the RiskGate ceiling per
environment / customer (a Rego overlay can only lower autonomy,
never raise it, per
[execution-model.md § Unified RiskGate](../decisioning/execution-model.md#3-unified-riskgate)).

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

### 5.10 Runtime failure modes and hold for review contracts

Every seam has a documented behaviour when its live adapter fails
at runtime. A fork's adapters MUST honour these contracts so the
control loop degrades to HIL rather than into an ungated action.

| Seam | Live adapter fails | Expected behaviour |
|------|--------------------|--------------------|
| `EmbeddingModel` / `CrossCheckModel` | HTTP error, timeout | Raise; upstream catches and abstains the quality candidate (HIL). Never return a synthesised empty response. |
| `CriticModel` / `JudgeModel` | HTTP error, quota | Raise; `DebateOrchestrator` returns `DebateVerdict.ABORT` with `error_class`, which routes to HIL. |
| `WebSearchProvider` | HTTP error, timeout | May raise or return an empty result. The caller converts exceptions into sanitized `provider_error` evidence without raising action authority. |
| `HilChannel.send` | Delivery fails | Raise; upstream logs and the audit trail marks the approval as `dispatch_failed`. The action stays pending; no auto-execute. |
| `HilChannel.poll` | Backend unreachable | Raise; upstream keeps the approval in `pending` on next tick. |
| `OperatorMemoryStore` | DB down at write | Raise; no entry is stored and the caller fails the approval workflow closed. |
| `OperatorMemoryStore` | DB down at read | Raise; the composer fails the current request closed instead of silently using stale or empty memory. |
| `SecretProvider.get` | Secret missing / KV down | Raise `SecretNotFoundError`; startup fails fast. A missing secret is never silently defaulted. |
| `ScopeResolver` | Cannot parse the resource ref | Return `None`; the materializer skips operator-memory attachment for that event but the action itself is not blocked. |
| `RemediationPrPublisher` (5.13) | PR host down | Raise; the executor records an `execution_failed` audit entry and the action stays in shadow. Never fabricate a `PublishReceipt`. |
| `ReadPanel.render` (5.14) | Data source down | Return an empty panel body plus a `reasons=("<source-error>",)` marker if your panel model supports it, or raise HTTP 503. A panel MUST NOT execute an action on any code path. |

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

### 5.12 ActionType catalog additions

**When to override**: introducing a new mutation category the shipped
catalog does not cover. Typical examples: `governance.assign-reviewers`
(routes a proposal to a Reviewer set), `governance.publish-decision`
(records an approval outcome), `remediate.rotate-fork-signing-key`
(fork-owned rotation with a custom rollback path). If you only need a
new rule that reuses an existing ActionType (e.g. `remediate.tag-add`),
skip this recipe; 5.8 alone is enough.

**The seam**: `rule-catalog/action-types/` YAML files consumed by
`fdai.rule_catalog.schema.action_type.load_action_type_catalog(...)`.
A fork ships its own directory (e.g. `fork/action-types/`) and either
concatenates the two catalogs the way 5.8 concatenates rules, or - when
adjusting a shipped ActionType - drops a same-name overlay under a
sibling directory (see "Fork-side overlays" below).

**Required schema fields** (validated at load, `default_mode=shadow`
enforced for every upstream ActionType and any fork ActionType you
promote through the same pipeline):

- `name` - stable id, snake / dot / dash tokens (e.g.
  `governance.assign-reviewers`). Globally unique across all catalog
  roots.
- `operation` - CSP-neutral verb from the `Operation` enum in
  `fdai.shared.contracts.models` (`tag`, `create`, `update`, `delete`,
  `scale`, `restart`, `rotate`, `revert`, ...). `configure` is not a current enum value. If you need
  a verb that does not exist, open an upstream issue - the enum is the
  audit vocabulary and MUST NOT be forked.
- `interfaces` - list of `ActionInterface` names the executor honours
  (e.g. `ControlPlane`, `DataPlaneMutating`, `IdempotentByKey`,
  `RequiresInventoryFresh`). `DataPlane` and `Governance` are not current enum values. Risk-gate composes
  its feature vector from this set.
- `rollback_contract` - one of `pr_revert`, `scripted`, `pitr`,
  `snapshot_restore`, `state_forward_only`. The legacy `none` value is
  gone; a genuinely one-way mutation sets `irreversible: true` and is
  routed HIL+quorum by the risk-gate, but still MUST declare a
  best-effort rollback description.
- `default_mode` - MUST be `shadow` for every upstream and fork catalog entry. The loader rejects
  `enforce`; authoritative promotion state is stored separately.
- `promotion_gate` - `min_shadow_days`, `min_samples`, `min_accuracy`,
  `max_policy_escapes`. Rule assignments MAY tighten these, never
  loosen.
- `preconditions[]` / `stop_conditions[]` - deterministic checks the T0
  verifier evaluates before the risk-gate. Empty lists are allowed only
  when the executor has independent invariants (e.g. an idempotent tag
  set); most `governance.*` ActionTypes declare at least one.
- `trigger_kind` (optional) - an object with `kind: rule_violation`,
  `kind: operator_request`, or `kind: both`. For `operator_request` or `both`, declare
  `argument_schema` (JSON Schema) so the console can validate arguments
  at the coordinator boundary.

**How to bind (concatenation)**:

```python
from pathlib import Path
from dataclasses import replace

from fdai.rule_catalog.schema.action_type import load_action_type_catalog

upstream_actions = load_action_type_catalog(
    Path("rule-catalog/action-types"),
    schema_registry=registry,
    probes_root=Path("rule-catalog/probes"),
)
fork_actions = load_action_type_catalog(
    Path("fork/action-types"),
    schema_registry=registry,
    probes_root=None,   # fork MAY ship its own probes; None skips the cross-check
)
action_types = upstream_actions + fork_actions
action_names = [item.name for item in action_types]
if len(action_names) != len(set(action_names)):
  raise ValueError("duplicate ActionType name across upstream and fork roots")
```

The Rule loader (5.8) then receives `action_types=action_types` and
resolves every `remediates:` reference across the combined set.

**Fork-side overlays** (adjusting a shipped ActionType without editing
its YAML): `load_action_type_catalog` accepts an optional
`overlay_root=Path("fork/action-types-overrides")`. Every YAML in that
directory carries a `name:` that MUST match an upstream ActionType;
declared keys deep-merge onto the upstream mapping before the pydantic
model is validated. Lists are replaced wholesale (preconditions,
stop_conditions), so a fork that wants to add a precondition ships the
full precondition list under the overlay name. An overlay whose `name`
has no upstream match is rejected - a typo cannot silently introduce a
phantom ActionType.

**How to test**: reuse `tests/rule_catalog/test_action_type_catalog.py`
as a template. A fork's tests SHOULD assert:

- every fork ActionType round-trips through
  `load_action_type_from_mapping` without error,
- `default_mode` matches the fork's shadow-first policy,
- `promotion_gate` values are non-degenerate,
- `argument_schema` is present when `trigger_kind` allows
  operator-request.

**Working reference**: upstream ships
[`ops.publish-change-summary`](../../../rule-catalog/action-types/ops.publish-change-summary.yaml)
as a shadow-mode ActionType with an operator-request `argument_schema`,
a `pr_revert` rollback contract, and a paired rule + Rego + Markdown
template. Copy the six-file scaffold, including ObjectType and LinkType, as your starting point for any
new mutation category.

**Anti-patterns**:

- Editing shipped `rule-catalog/action-types/*.yaml` - the same rule as
  ObjectType edits: shipped ActionTypes go upstream, fork ships new
  ones or overlays.
- Silencing rollback with `irreversible: true` alone. The
  `rollback_contract` is mandatory even when reversal is best-effort.
- Setting `default_mode: enforce` on a brand-new ActionType category
  without a measured shadow window - even in a fork.

### 5.13 Delivery adapter (custom publisher)

**When to override**: publishing action output to a channel other than
a Git remediation PR. Typical fork examples: a Confluence page
publisher for governance decisions, a Slack notification adapter that
files a change ticket, a ServiceNow bridge that opens a CAB request. If
your fork only reuses the shipped `gitops-pr` publisher against a
different owner/repo, no code is needed - just set `FDAI_GITOPS_TOKEN`,
`FDAI_GITOPS_OWNER`, and `FDAI_GITOPS_REPO`.

**The seam**: `fdai.shared.providers.remediation_pr.RemediationPrPublisher`
Protocol with one async method:

```python
class RemediationPrPublisher(Protocol):
    async def publish(self, pr: RemediationPr) -> PublishReceipt: ...
```

`RemediationPr` carries the fully-rendered payload (title, body, patch, patch path, labels,
action/idempotency ids), and `PublishReceipt` must include a stable `pr_ref` the audit log can cite. The upstream
executor is Protocol-typed; a fork constructs the publisher and
injects it via the composition root.

**Naming**: the type is called `RemediationPrPublisher` for historical
reasons (Git PR was the first channel), but the Protocol shape is
channel-agnostic. A fork adapter targeting a Confluence page or a
ServiceNow ticket is a first-class implementation - not a workaround.

**How to bind (Confluence page publisher example)**:

```python
# fork/adapters/confluence_publisher.py
from fdai.shared.providers.remediation_pr import (
    PublishReceipt, RemediationPr, RemediationPrPublisher,
)
from fdai.shared.providers.secret_provider import SecretProvider

class ConfluencePagePublisher(RemediationPrPublisher):
    """Publishes rendered governance-decision pages to a Confluence space."""

    def __init__(
        self,
        *,
        secret_provider: SecretProvider,
        api_token_secret: str,
        base_url: str,
        space_key: str,
    ) -> None:
        self._secret_provider = secret_provider
        self._api_token_secret = api_token_secret
        self._base_url = base_url
        self._space_key = space_key

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        token = await self._secret_provider.get(self._api_token_secret)
        # 1. Translate pr.title / pr.body / pr.patch into a Confluence body.
        # 2. POST to <base_url>/wiki/rest/api/content with self._space_key.
        # 3. Extract the page id and self-link from the response.
        # 4. Return a PublishReceipt whose pr_ref cites the page id
        #    so the audit log links back to the exact revision.
        return PublishReceipt(
            pr_ref="confluence:page:<id>",
            url="<page-url>",
            already_existed=False,
        )
```

**Composition-root wiring** (replace the default publisher):

```python
# fork/composition_root.py
from fork.adapters.confluence_publisher import ConfluencePagePublisher
from fdai.core.executor import ShadowExecutor
# ... in your build_control_loop() ...

publisher = ConfluencePagePublisher(
    secret_provider=secret_provider,  # constructed separately by fork composition
    api_token_secret="confluence.api.token",
    base_url="https://example.atlassian.net",
    space_key="ARB",
)
executor = ShadowExecutor(
    publisher=publisher,
    audit_store=audit_store,
    renderer=renderer,
    resource_lock=resource_lock,
)
```

The `ShadowExecutor` takes the publisher directly; the ActionType
(5.12) declares the mutation category and its `rollback_contract`
governs how the executor unwinds. For a Confluence page, the natural
rollback is `pr_revert` if you also publish a "retract" companion page
that supersedes the original, or `state_forward_only` if the space
policy is append-only. Do NOT pick `none` - it is no longer a valid
value.

**How to test**: mirror
`tests/delivery/gitops_pr/test_adapter.py`. Wire tests use
`httpx.MockTransport` against the vendor API; contract tests assert
`isinstance(adapter, RemediationPrPublisher)` at runtime because the
Protocol is `@runtime_checkable`.

**Anti-patterns**:

- Making the publisher execute a mutation on the Resource itself.
  Delivery is a projection surface; the executor + risk-gate own the
  mutation contract. A publisher that side-effects on the Resource is
  a policy bypass.
- Logging or persisting the resolved secret. `SecretProvider.get`
  returns a live string; keep it call-scoped, never on `self` beyond
  one request lifetime.
- Bundling the delivery adapter with fork-owned rule logic. Keep the
  adapter under `fork/adapters/` and the rule catalog under
  `fork/rules/` so each side has an isolated test surface.

### 5.14 Console ReadPanel additions

**When to override**: adding a vertical dashboard to the read-only
console - a FinOps cost summary, a drift board, a governance-decision
history, a DR-drill run log. If you only consume the shipped
`/audit`, `/kpi`, `/hil-queue` routes, skip this recipe.

**The seam**: `fdai.delivery.read_api.routes.panels.ReadPanel` Protocol plus
the `ReadApiConfig.extra_panels` tuple in
[`fdai.delivery.read_api.main`](../../../src/fdai/delivery/read_api/main.py).
A `ReadPanel` declares its own HTTP path and returns a serialised
model on `render()`; the read-API mounts each panel as a GET-only
route with the path validated at build (starts with `/`, no `..`
traversal).

**Read-only contract (MUST)**:

- `ReadPanel.render` MUST NOT mutate state or trigger any action -
  it is a projection surface only. A panel that wants to trigger a
  workflow does it by emitting a `Signal` to the event bus, never by
  calling into an executor.
- The upstream `ExampleFinOpsPanel` under
  [`panels.py`](../../../src/fdai/delivery/read_api/routes/panels.py) is a
  reference implementation and is **not** registered by default. Copy
  its shape, do not import and re-register it - upstream keeps the UI
  minimal on purpose.

**How to bind (fork panel example)**:

```python
# fork/adapters/read_panels.py
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.delivery.read_api.routes.panels import ReadPanel

@dataclass(frozen=True)
class GovernanceDecisionsPanel(ReadPanel):
    """Recent governance decisions with their reviewer set + outcome."""

    path: str = "/panels/governance/decisions"
    name: str = "governance-decisions"

    async def render(self, *, params: Mapping[str, str]) -> dict[str, Any]:
        # 1. Query the fork's projection store (Postgres view, read model, ...).
        # 2. Redact any identity value that is not console-safe.
        # 3. Return a JSON-serialisable dict; the read-API serialises it.
        return {
            "items": [],           # list of {proposal_id, decided_at, reviewers, outcome}
            "generated_at": "...",
        }
```

**Composition-root wiring** (register in the fork's `entry.py`):

```python
# fork/entry.py
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fork.adapters.read_panels import GovernanceDecisionsPanel

app = build_app(
  authenticator=authenticator,
  read_model=read_model,
    config=ReadApiConfig(
        extra_panels=(GovernanceDecisionsPanel(),),
    ),
)
```

**Console UI (frontend)**: the shipped console (`console/`) is a
minimal read-only SPA. A fork that ships a new panel MUST also
register it in `console/src/panels.tsx` (or the equivalent registry
for its UI stack) so the panel appears in the sidebar. That console
edit lives entirely under `console/` in the fork's repo; upstream
`console/` stays generic.

**How to test**: `tests/delivery/read_api/test_main.py` covers the
mount / path-validation logic upstream. A fork adds:

1. A unit test over your panel's `render()` with a stubbed data
   source.
2. An HTTP-level test that boots `build_app(authenticator=..., read_model=...,
  config=ReadApiConfig(extra_panels=(YourPanel(),)))` with Starlette's test client and asserts the panel is reachable via
   GET at its declared path.
3. A negative test asserting the panel refuses to accept non-GET
   verbs (the mount code enforces this; the test protects against
   fork drift).

**Anti-patterns**:

- Executing an action from a panel (form POST that calls an executor
  method). The console is a read surface; approvals flow through
  ChatOps or PR, never a panel button.
- Panels that read a live cloud SDK. Use the shipped inventory /
  projection stores; a panel that talks to the vendor API directly
  duplicates state and creates split-brain drift.
- Skipping the frontend registry edit. A backend-only panel that has
  no UI entry becomes an undocumented HTTP surface - trace-worthy but
  unusable.

### 5.15 Fork entry point (`entry.py`)

**When to override**: every real fork. The Day-1 checklist calls for
"rename your process entry point to import from this module instead
of upstream's `__main__`"; this recipe shows what a working
`fork/entry.py` looks like.

**The seam**: upstream's [`src/fdai/__main__.py`](../../../src/fdai/__main__.py) is a
compatibility facade over `fdai.runtime.*` helpers such as `_resolve_catalog_root`,
`_build_audit_store`, `_build_operator_memory_store`,
`_build_pattern_library`, `_build_publisher`, `_build_hil_channel`,
`_finalize_llm_bindings`, `_build_control_loop`, `_consume`, `_run` -
so a fork's `entry.py` composes the same shape while substituting the
helpers it owns.

**What to reuse as compatibility helpers** (import from upstream, do not redefine):

- `_resolve_catalog_root` / `_resolve_policies_root` -
  environment / filesystem discovery.
- `_finalize_llm_bindings` - compatibility wrapper for the env-driven upstream entry. A
  programmatic fork should call public `wire_azure_container` with `AzureWireOverrides` directly.
- `_consume` / `_run` - the Kafka event loop and top-level
  signal-handling scaffolding.

**What to swap** (fork owns each of these):

- `_build_publisher` - if your fork ships a delivery adapter (5.13),
  replace this helper with one that returns your publisher.
- `_build_hil_channel` - if your fork ships a HilChannel adapter
  (5.5), replace this helper.
- `_build_control_loop` - the composition of catalogs, ActionTypes,
  ontology (5.8a), and rules. A fork typically calls the upstream
  helper and then wraps its return value, or copies the body and adds
  fork-catalog concatenation.

**Skeleton**:

```python
# fork/entry.py
"""Fork process entrypoint - wraps upstream's __main__ helpers.

Adds:
- fork rule catalog + ActionType catalog + ObjectType/LinkType catalog
  concatenation,
- Confluence publisher (5.13),
- Teams HilChannel adapter (5.5),
- Governance dashboards (5.14).

Everything the fork does NOT own is imported straight from upstream so
`main` continues to receive the same signal-handling contract.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import replace
from pathlib import Path

import httpx

from fdai.__main__ import (
    _consume,
    _finalize_llm_bindings,
    _resolve_catalog_root,
    _resolve_policies_root,
    _run,
)
from fdai.composition import Container, default_container_from_env
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.rule import load_rule_catalog

from fork.adapters.confluence_publisher import ConfluencePagePublisher
from fork.adapters.hil_channel_teams import TeamsHilChannel

_LOGGER = logging.getLogger("fork.startup")


async def build_container_with_fork_catalogs(
    *, http_client: httpx.AsyncClient,
) -> Container:
    container = default_container_from_env()

    catalog_root = _resolve_catalog_root()
    fork_root = Path("fork")
    registry = container.schema_registry

    # ObjectType / LinkType concatenation (recipe 5.8a).
    upstream_objects = load_object_type_catalog(
        catalog_root / "vocabulary" / "object-types", schema_registry=registry,
    )
    fork_objects = load_object_type_catalog(
        fork_root / "vocabulary" / "object-types", schema_registry=registry,
    )
    objects = upstream_objects + fork_objects
    upstream_links = load_link_type_catalog(
        catalog_root / "vocabulary" / "link-types",
        schema_registry=registry, object_types=objects,
    )
    fork_links = load_link_type_catalog(
        fork_root / "vocabulary" / "link-types",
        schema_registry=registry, object_types=objects,
    )
    container = replace(
        container,
        ontology_object_types=objects,
        ontology_link_types=upstream_links + fork_links,
    )

    # ActionType concatenation (recipe 5.12) then Rule concatenation (5.8)
    # happen inside your own _build_control_loop wrapper below.

    return await _finalize_llm_bindings(container, http_client=http_client)


async def _fork_run() -> int:
    async with httpx.AsyncClient(timeout=30.0) as http:
        container = await build_container_with_fork_catalogs(http_client=http)
        # ... build fork publisher + HIL channel here, then hand off to _consume.
        # See fork/composition_root.py for the full wiring.
        return await _consume(container=container, http_client=http)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(_fork_run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
```

**pyproject.toml script entry** (register the fork's entry point so
`uv run` / container CMD lands here):

```toml
[project.scripts]
fdai = "fork.entry:main"
```

Upstream ships the same `fdai` script pointed at `fdai.__main__:main`;
overriding the script name means the container image built from the
fork's Dockerfile runs the fork entry point automatically without
changing the CMD.

**How to test**: `tests/composition/test_entry.py` (fork-local)
should exercise `build_container_with_fork_catalogs` against the
in-memory fakes and assert:

1. `container.ontology_object_types` contains both upstream and fork
   names.
2. `container.llm_bindings` is non-None after `_finalize_llm_bindings`
   in `local-fake` mode.
3. A configuration-error env produces a fail-fast startup, not a
   silently-degraded container.

**Anti-patterns**:

- Copy-pasting the entire `__main__.py` and editing in place. You
  lose the upstream sync line-of-defence. Wrap or import; never
  fork-clone the whole file.
- Binding Azure twice by mixing env-driven `_finalize_llm_bindings` with programmatic
  `wire_azure_container`. Choose one path and never bypass `AzureWireOverrides` validation.
- Registering the fork's `entry.py` under a different script name
  than `fdai` and forgetting to update the container CMD. Result:
  the image runs upstream's `__main__` and none of your fork wiring
  runs.

### 5.16 Manual distillation (`ManualSource` / `ManualClassifier` / `Distiller`)

**When to override**: to absorb an adopting company's operational /
deployment manuals by compiling them into deterministic rules,
workflows, and policies (see
[manual-distillation.md](../rules-and-detection/manual-distillation.md)).
Skip this section if your fork has no prose manuals to distill.

**The seams** (all three abstain upstream, so an unwired fork distills
nothing rather than fabricating a rule):

- `fdai.shared.providers.manual_source.ManualSource` - discovers
  manuals and delivers each as a `ManualDocument`. Default
  `EmptyManualSource` offers none. The upstream generic
  `DropDirectoryManualSource` reads a local drop directory and thereby
  covers every credential-free access mode at once (operator drop,
  console upload, email-in, iPaaS / Power Automate webhook). Bind it
  with `bind_drop_directory_manual_source(container, root=...)`. A
  connector to SharePoint / Confluence / Notion, or a delegated-token
  fetch, is customer data and lives in the fork behind this same
  Protocol.
- `fdai.shared.providers.manual_classifier.ManualClassifier` - the
  cheap "is this an operational procedure?" call. Default
  `AbstainingManualClassifier` marks every candidate `UNCERTAIN`, so
  they route to HIL triage instead of auto-distilling. A fork binds a
  small-model classifier via `replace(container, manual_classifier=...)`.
- `fdai.shared.providers.distiller.Distiller` - the LLM extractor.
  Default `AbstainingDistiller` extracts nothing. A fork binds an
  LLM-backed distiller via `replace(container, distiller=...)`.

The deterministic stages (triage filter, exact dedupe, sensitivity
secret / PII guard, freshness diff, coverage) are upstream and need no
fork work. The build-time orchestrator
`fdai.rule_catalog.pipeline.distill.orchestrator.build_distillation_plan`
stitches them into one inert `DistillationPlan`; run a pass with
`python -m fdai.rule_catalog.pipeline.distill_cli --drop-dir <dir>
--snapshot <file>`. The plan is inert - distilled candidates still face
the grounding / shadow / regression / promotion gates before enforce.

**How to test**: reuse the shipped distill tests as templates
(`tests/rule_catalog/pipeline/distill/*`); add a fork fixture directory
and assert that (1) your `ManualSource.list_candidates` returns the
expected candidates, (2) a sensitivity-tripping fixture routes to
`held`, not `distilled`, and (3) your `Distiller` output cites
`source_ref` provenance and clears the coverage diff.

**Anti-patterns**:

- Holding a broad standing service-principal read credential over a
  whole tenant. Distillation is build-time and runs once per manual
  revision, so invert to push / delegate and hold no standing
  credential (see the design doc's access table).
- Auto-distilling a manual that trips the sensitivity guard. A
  `HOLD` disposition MUST route to HIL, never straight to the
  distiller.
- Committing manuals or distilled rules upstream. They are customer
  data and live only in the fork, exactly like the rule catalog
  additions in 5.8.

### 5.17 Capability bundle registration

**When to use**: when one fork feature needs operator-facing discovery plus a
reasoning tool, `ActionType`, or `Workflow` binding. Use the narrower recipes
above when you only replace one infrastructure provider.

**The seam**: `CapabilityBundle` groups `Capability` metadata,
`CapabilityBinding` references, and reasoning-tool providers. Install it with
`fdai.composition.install_capability_bundle(...)`. The installer returns a new
`Container`; the original remains unchanged. An `ActionType` or `Workflow`
binding is only a typed reference and never invokes the target directly.

**How to bind**:

1. Load the combined upstream and fork tool, ActionType, and Workflow catalogs.
2. Construct the fork-owned provider and `CapabilityBundle`.
3. Pass the loaded catalog objects to `install_capability_bundle`.
4. In Azure mode, pass the returned container to `wire_azure_container`.
   Installed reasoning-tool providers are included automatically.

The installer blocks startup on unknown targets, missing or duplicate
providers, mismatches between a tool artifact's declared provider and the
bundle, and unreferenced providers. See
[`fdai.fork_examples.capability_bundle`](../../../src/fdai/fork_examples/capability_bundle.py)
for a copy-ready state-query provider and composition helper.

**How to test**: assert that the original container has no fork binding, the
returned container resolves the capability, malformed references fail before
provider I/O, and the provider output satisfies the tool artifact's output
contract. Keep mutating capabilities in shadow mode and test them through the
normal risk-gate and executor path rather than calling the resolved target.

**Anti-patterns**:

- Registering the same provider through both a bundle and
  `AzureWireOverrides.tool_providers`. Duplicate ids are a startup error.
- Using a bundle as a generic function dispatcher for mutations. Mutations
  remain `ActionType` invocations governed by the control loop.
