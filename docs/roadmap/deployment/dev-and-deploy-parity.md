---
title: Dev/Deploy Parity - Test Fakes and Azure-Backed Local Development
---
# Dev/Deploy Parity - Test Fakes and Azure-Backed Local Development

**Goal**: automated tests remain deterministic and secret-free, while every interactive local
Console session shows the operator's actual Azure development environment. Azure deployment
still uses the **deployer's Azure permissions + region catalog to decide which LLM and other
resources are provisioned**. Three truths hold at the same time:

- **Automated-test truth**: pytest and committed mocks may bind deterministic fakes. They use an
  explicit test-fixture builder and never represent observed Azure state.
- **Full-stack local truth**: `Console Web: Full Stack` requires the current Azure CLI identity.
  Inventory and model availability come from Azure. Audit, Incidents, Approvals, Agent activity,
  live control-loop state, cost, promotion evidence, scope, and scheduler data appear only when
  their authoritative FDAI Azure data plane is deployed and configured. Missing sources render
  unavailable or explicitly empty; the Console never substitutes generated examples.
- **Deploy truth**: `terraform apply` provisions the Azure-side realizations of the
  CSP-neutral contracts. The **LLM subset is deployer-scoped**: the bootstrap resolver
  queries the deployer's identity against the target region's catalog, provisions
  **only what the deployer has permission to create**, and records the resolved
  `{capability → deployment}` mapping in the audit log.

Both modes share **one code path**: only the composition-root bindings differ
([project-structure.md § Customization via Dependency Injection](../architecture/project-structure.md#customization-via-dependency-injection)).
Adding a real Azure client is a fork-side injection; it MUST NOT edit `core/`.

## Audit - What Works Local, What Needs Azure

Snapshot as of 2026-07-19. "Automated test" means pytest or a committed mock invoked by the
test runner. "Full-stack local" means the VS Code compound launch using the current Azure CLI
context. Test fixtures are never enabled by that launch profile.

### Fully working in automated tests (no Azure needed)

| Subsystem | Local backend | Notes |
|-----------|---------------|-------|
| T0 deterministic engine | `opa` binary + Rego policies + rule catalog | 100% offline; the CI parity gate proves this |
| Rule catalog loader + shadow eval pipeline | filesystem YAML | no cloud calls |
| Risk gate + promotion registry | in-memory `ActionPromotionRegistry` | seam swappable |
| Executor + resource lock | in-process | no PR delivery in dev-mode |
| Audit store | `InMemoryStateStore` (hash-chain verified) | prod backend = Postgres |
| Event ingest + trust router | in-process | no bus wired |
| Verticals (Resilience / FinOps / Change Safety) | pure decision modules | no cloud |
| Quality gate | `StaticVerifier` + `MatchTypeCrossCheckModel` + `InMemoryGroundingSource` | see [llm-strategy.md § T2](../architecture/llm-strategy.md#t2--reasoning-tier-quality-gate-required) |
| T1 similarity | `DeterministicEmbeddingModel` + `InMemoryPatternLibrary` | hash-based, no real embeddings |

### Backed by dev-up.sh (still local)

| Subsystem | Local backend | Prod backend |
|-----------|---------------|--------------|
| State store (integration tests) | `pgvector/pgvector:pg16` on `:5432` | Azure PostgreSQL Flexible + pgvector |
| Event bus (integration tests) | Redpanda on `:19092` (Kafka wire) | Event Hubs Kafka on `:9093` |

### Console data in local development

The local read API authenticates with `FDAI_READ_API_LOCAL_AZURE_CLI=1`; the SPA pairs it with
`VITE_LOCAL_AZURE_CLI_AUTH=1`. The access token remains server-side. The inventory graph reads
the selected Azure subscription through `AzureCliInventory`, and the model catalog reads actual
Azure model availability.

The local factory does not start a local Pantheon runtime, scenario replay, synthetic Live or
Agents emitter, seeded audit model, demo findings, generated Process, synthetic scheduler,
synthetic cost meter, scope template, or blast-radius graph. When FDAI's Azure PostgreSQL/Event
Hubs/runtime resources are absent, those panels are unavailable or empty with no runtime claim.
Repository catalogs and schemas remain visible because they are configuration-as-code, not
observed runtime evidence.

### Azure-backed integrations

| Subsystem | Status | Gap |
|-----------|--------|-----|
| Azure Resource Graph inventory | Production adapter exists (`delivery/azure/inventory.py`) | Full-stack local always uses read-only `AzureCliInventory`; synthetic opt-out is rejected |
| Managed Identity token (`WorkloadIdentity`) | Protocol only, no adapter | Dev-mode MUST use a deterministic in-memory token issuer |
| Key Vault secret provider (`SecretProvider`) | Protocol only, no adapter | Dev-mode MUST read secrets from `.env` (already the fork pattern; formalise it as a `EnvSecretProvider`) |
| GitOps PR publisher | Real GitHub adapter exists | Dev-mode already has a `RecordingRemediationPrPublisher` fake ✅ |

### Not yet built at all

| Subsystem | Missing artifact | Consequence |
|-----------|------------------|-------------|
| Azure OpenAI / AI Foundry Terraform module | `infra/modules/llm/azure-openai/` | `T2_MODEL_ENDPOINT` env var is documented but never populated |
| `rule-catalog/llm-registry.yaml` | designed in [llm-strategy.md § Capability Preferences Registry](../architecture/llm-strategy.md#capability-preferences-registry) | no capability→family preference source |
| Bootstrap resolver CLI | designed in [llm-strategy.md § Bootstrap Provisioner](../architecture/llm-strategy.md#bootstrap-provisioner) | nothing queries deployer identity + region catalog |
| `resolved-models.json` writer / reader | designed | no runtime `capability → deployment` map |
| Azure OpenAI adapter (`AzureOpenAIEmbeddingModel`, `AzureOpenAICrossCheckModel`) | not written | prod cannot bind real LLMs |
| `LlmConfig` in `AppConfig` | not in `schema.json` / `models.py` | no way to declare mode / endpoint / capabilities |
| Reconciler weekly Job | designed | no drift / deprecation surfacer |

## Parity Contract (MUST)

Every seam that touches an out-of-process dependency MUST provide:

1. **A Protocol in `shared/providers/`** - the neutral wire contract. `core/` imports the
   Protocol only. This already holds for `EventBus`, `StateStore`, `SecretProvider`,
   `WorkloadIdentity`, `Inventory`, and the LLM seams (`EmbeddingModel`,
   `CrossCheckModel`, `VerifierPolicy`, `GroundingSource`).
2. **A test-fake implementation** - deterministic, in-process, and secret-free. It is selected
  only by automated tests or committed mock/example applications through an explicit fixture
  builder, never by the interactive local Console.
3. **An Azure adapter** - under `delivery/azure/` (never `core/`). It is selected for both the
  interactive local profile and deployed environments when the identity and source exist.
4. **Fail-fast or unavailable in the mismatch case** - an interactive or deployed runtime never
  falls back to a test fake. A required startup source fails startup; an optional read panel
  renders unavailable. Silent fallback is **prohibited** (matches the "no HIL-silent fallback" rule in
   [llm-strategy.md § Bootstrap Provisioner](../architecture/llm-strategy.md#bootstrap-provisioner)).

Every test that exercises the pipeline runs in mode (1)+(2) so the CI parity gate never
needs an Azure token.

## Deployer-Scoped LLM Provisioning

At `terraform apply` time the resolver behaves like this:

```mermaid
flowchart LR
    START([terraform apply]) --> WHOAMI["az account show<br/>+ resolve deployer principal"]
    WHOAMI --> AUDIT[Bootstrap audit entry:<br/>deployer_object_id, sub, region]
    AUDIT --> REG[read rule-catalog/llm-registry.yaml]
    REG --> CAT["query Azure catalog:<br/>Foundry / AOAI SKUs available<br/>in var.region"]
    CAT --> RBAC{deployer has<br/>Cognitive Services Contributor<br/>on target subscription?}
    RBAC -->|no| SKIP1[emit warning:<br/>skip LLM provisioning<br/>mark T2 capability = HIL-only]
    RBAC -->|yes| MATCH{"preferred family available<br/>AND deployer sub has quota?"}
    MATCH -->|no for capability| SKIP2["mark this capability HIL-only<br/>continue with remaining"]
    MATCH -->|yes| DEPLOY["provision deployment<br/>cap_tpm from registry"]
    DEPLOY --> INV{"mixed-model invariant:<br/>primary.publisher != secondary.publisher?"}
    INV -->|violated| ABORT["abort with clear error<br/>(fork must expand preferences)"]
    INV -->|ok| WRITE[write resolved-models.json to Key Vault]
    SKIP1 --> WRITE
    SKIP2 --> WRITE
    WRITE --> ROLE[role-assign executor MI:<br/>Cognitive Services OpenAI User]
    ROLE --> DONE([done])
```

**Deployer permission gates** (checked by the resolver before touching the catalog):

| Check | Failure mode | Follow-up |
|-------|--------------|-----------|
| `az account show` returns a signed-in principal | abort - deployer must run `az login` | one-line diagnostic |
| Principal has `Cognitive Services Contributor` (or `Owner`) on the target subscription | skip LLM provisioning, mark all `t2.*` and `t1.judge` capabilities as `hil-only`, emit warning | fork can grant the role and re-run |
| Region exposes at least one family from each capability's preferences | mark just the affected capability `hil-only`, warn | fork can expand preferences in `llm-registry.yaml` and re-run |
| Deployer's subscription has quota for the requested `capacity_tpm` | reduce to the largest available capacity ≥ 20% of requested; refuse below that | fork requests quota increase |
| Mixed-model invariant (`t2.reasoner.primary.publisher != t2.reasoner.secondary.publisher`) after resolution | **abort** - do NOT partially deploy a T2 tier that would fail the quality gate | fork adjusts preferences |

The resolver's decisions are recorded as **one bootstrap audit entry** with the deployer's
`object_id`, the region, and the resolved capability map. This entry replays cleanly:
re-running the resolver on the same sub + region + registry yields the same mapping (idempotent).

## Work Plan (phased, additive)

Every phase leaves the tree buildable + testable at `head`. Multi-cloud is **TBD**
throughout ([copilot-instructions § Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).

**Status as of 2026-07-05**: W-A through W-G are **shipped**; W-H (docs sync) shipped
alongside the initial draft of this document; W-I (reconciler weekly job) remains deferred.
Each work item below reflects what actually landed - code, tests, and gate coverage.

### W-A: Config schema for LLM + dev-mode flag ✅ *(baseline, shipped)*

- Add `LlmConfig` to `src/fdai/shared/config/schema.json` + `models.py`:
  - `mode`: `local-fake` | `azure` (default `local-fake` when `runtime.env == "dev"`).
  - `resolved_models_path`: optional KV secret name or filesystem path.
  - `capabilities`: list of capability names (`t1.embedding`, `t1.judge`,
    `t2.reasoner.primary`, `t2.reasoner.secondary`) - mirrors the registry.
  - `t2_primary_latency_routing`: bool, default `true`. Latency routing of
    the T2 primary proposer among its same-publisher candidate pool
    (invariant-safe; enforced on). Takes effect only when the resolver emits
    a >= 2 pool (`--emit-primary-pool`); set `false` to pin the single
    primary. See [llm-strategy.md](../architecture/llm-strategy.md) section
    "T2 Primary Latency Pool".
- Fail-fast validator: `mode == "azure"` requires `resolved_models_path` present.
- Tests: schema + pydantic validators.

### W-B: `rule-catalog/llm-registry.yaml` + schema  ✅ *(catalog-as-code, shipped)*

- New file: `rule-catalog/llm-registry.yaml` with upstream defaults (mini → Opus tier).
- JSON Schema: `rule-catalog/schema/llm-registry.schema.json`.
- Python loader: `fdai.rule_catalog.schema.llm_registry` with the aggregating
  fail-close pattern used elsewhere (see `exemption.py`).
- Tests: schema validation, mixed-model invariant check.

### W-C: Bootstrap resolver CLI  ✅ *(deployer-scoped, shipped)*

- New: `src/fdai/rule_catalog/schema/llm_resolver_cli.py`.
- Inputs: `--registry`, `--region`, `--subscription-id`, `--dry-run`, `--out`.
- Uses `DefaultAzureCredential` (deployer's cached CLI creds).
- Queries:
  - `az cognitiveservices account list-models --location <region>` (via SDK) for
    available families.
  - Role assignments on the target subscription (via `azure-mgmt-authorization`) for
    the permission gate.
- Emits `resolved-models.json` (or `--dry-run` prints to stdout).
- Enforces every check in [Deployer-Scoped LLM Provisioning](#deployer-scoped-llm-provisioning).
- Tests: mock the two SDK clients; assert precedence + mixed-model invariant + `hil-only`
  fallback + idempotent output on same inputs.

### W-D: Azure OpenAI Terraform module + preflight  ✅ *(infra, shipped)*

- New: `infra/modules/llm/azure-openai/`.
  - `main.tf`: `azurerm_cognitive_account` (kind=`OpenAI`) + N
    `azurerm_cognitive_deployment` from `resolved_models.json` as input variable.
  - `variables.tf`: `enable_llm` (default `false` so bare-minimum deploys still succeed),
    `resolved_models` (object list from resolver).
  - `outputs.tf`: `endpoint`, `deployments` map, `resource_id`.
- Role assignment: executor MI → `Cognitive Services OpenAI User` on the account.
- Root `infra/main.tf` wires the module conditionally on `var.enable_llm`.
- Update `infra/README.md` with the deploy flow: resolver first → `terraform apply` with
  `enable_llm=true`.

### W-E: Azure OpenAI adapter classes  ✅ *(delivery, shipped)*

- `src/fdai/delivery/azure/llm/embeddings.py` - `AzureOpenAIEmbeddingModel`
  implementing `EmbeddingModel`, using `openai.AzureOpenAI` (async client) +
  `DefaultAzureCredential`.
- `src/fdai/delivery/azure/llm/cross_check.py` - `AzureOpenAICrossCheckModel`
  implementing `CrossCheckModel`.
- Timeout, retry-after honouring, structured output (`response_format={"type":"json_schema"}`)
  - see [llm-strategy.md § Provider Abstraction](../architecture/llm-strategy.md#provider-abstraction).
- Tests: use `httpx.MockTransport` + recorded fixtures - no live network.

### W-F: Composition-root wiring  ✅ *(binding, shipped)*

- Extend `Container` with `embedding_model: EmbeddingModel`, `cross_check_models`,
  `verifier_policy`, `grounding_source` fields.
- `default_container(config)` inspects `config.llm.mode`:
  - `local-fake` → bind the deterministic fakes.
  - `azure` → import the adapters from `delivery/azure/llm/`, load `resolved-models.json`,
    bind per capability. A missing entry raises `ConfigError` (fail-fast).
- Tests: both branches; assert `local-fake` never imports `delivery.azure.llm`.

### W-G: Dev-mode identity + secret + inventory adapters  ✅ *(parity fillers, shipped)*

- `EnvSecretProvider` in `shared/providers/testing/` (renamed to
  `shared/providers/local/` to reflect dev usage).
- `LocalWorkloadIdentity` - issues an in-memory OIDC token that adapters accept in
  dev-mode (no network).
- `FileFixtureInventory` - reads `Resource` records from any YAML fixture the fork passes to its constructor (`fixture=Path(...)`); upstream ships zero seed fixtures, and the recommended convention is `tests/scenarios/inventory/*.yaml` alongside the frozen scenario replay so verticals can dry-run without ARG.
- Tests + docstrings show the exact fork-side pattern.

### W-H: Docs sync  *(this phase)*

- ✅ This document itself.
- Update [deploy-and-onboard.md § Runtime Configuration Matrix](deploy-and-onboard.md#runtime-configuration-matrix)
  to add `LLM_MODE`, `LLM_RESOLVED_MODELS_PATH`.
- Update [deploy-and-onboard.md § Azure Resource Inventory](deploy-and-onboard.md#azure-resource-inventory-minimum-set)
  to add row 11 (Azure OpenAI, opt-in).
- Update [tech-stack.md § Local Development](../architecture/tech-stack.md#local-development) to
  explicitly state "LLM stays fake in dev by default".
- Update [llm-strategy.md § Bootstrap Provisioner](../architecture/llm-strategy.md#bootstrap-provisioner)
  to reference this doc for the deployer-permission gates.

### W-I: Reconciler weekly Job  *(later phase - deferred)*

Kept as future work. Full design already in
[llm-strategy.md § Reconciler Job](../architecture/llm-strategy.md#reconciler-job); ships as a
`infra/modules/compute/container-apps-job/` reuse plus a Python entry point.

## Fork-Side Override Points

Everything above stays customer-agnostic. A fork customises without touching `core/` by:

- Providing its own `llm-registry.yaml` with region/compliance overrides.
- Supplying `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID` env pointing at the fork's
  subscription. **This repo never stores those values.**
- Registering additional LLM providers (e.g. Anthropic direct API) by binding a fork-owned
  `CrossCheckModel` implementation in its composition root - the `azure-foundry` /
  `external` / `hil-only` toggle in
  [llm-strategy.md § Mixed-Model Family Strategies](../architecture/llm-strategy.md#mixed-model-family-strategies).

## Verification Gates

Each work item MUST be provable at CI time:

- `runtime.env == "dev"` end-to-end pytest run **imports zero `delivery.azure.*` modules**
  (enforced by `scripts/quality/architecture/check-core-imports.sh` - extend it to gate `delivery.azure.llm.*`
  imports on `dev-mode` fixtures).
- Terraform plan with `enable_llm=false` succeeds on a fresh subscription with only
  `Reader` role - proving the LLM module is truly opt-in.
- Resolver dry-run against a recorded region catalog produces a stable
  `resolved-models.json` hash - proving idempotency.

## Open Questions

- **Where does `resolved-models.json` live at runtime?** Options: Key Vault secret, ACR
  attestation, filesystem in the container image. Preference: Key Vault (fits the existing
  secret contract).
- **Is a local Ollama / LM Studio path worth adding as a second dev mode?** Not now - the
  deterministic fake already gives full parity for correctness tests; a "semantic" dev mode
  can land later without churning the composition root.
- **Reconciler alerts channel** - assumed Teams; confirm at W-I time.
