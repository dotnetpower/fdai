---
title: Cost Model (Illustrative)
---
# Cost Model (Illustrative)

Estimated monthly cost of the minimum Azure resource inventory defined in
[deploy-and-onboard.md](../deployment/deploy-and-onboard.md#azure-resource-inventory-minimum-set), broken
down by fixed vs variable spend and by traffic scenario. Cost-efficiency principles come from
[deploy-and-onboard.md](../deployment/deploy-and-onboard.md#cost-efficiency-principles).

> **Historical planning example - not a deployment estimate.** The bands below are a planning
> snapshot for the original minimum set, not a total from the current Terraform plan. Azure list prices change by region, over time, and by
> subscription agreement (EA / CSP / MCAPS / Reserved Instances / Savings Plans). Every
> number in this document is an **approximation** and MUST be reconfirmed against the
> [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) before any
> commitment. Nothing here is a guarantee. Figures reflect list prices at the time the
> document was authored; a `pricing.confirmed_at` field on the fork's cost dashboard MUST
> record when they were last verified.

## Assumptions

- **Region**: a single Azure region equivalent to Korea Central for order-of-magnitude
  figures; regional differences of ±20% are normal.
- **Currency**: USD list price, PAYG (Pay-As-You-Go) tier. Enterprise agreements typically
  reduce these by 5-20%; Reserved Instances / Savings Plans can reduce compute + database
  spend by 30-60% on 1-year / 3-year terms.
- **Traffic (baseline)**: **low traffic** - events in the thousands to tens of thousands per
  month. The current core Container App uses `min_replicas = 1` because no Event Hubs lag scaler
  is configured. Scheduled jobs return to zero between executions.
- **Retention**: Log Analytics 30-day default
  ([deploy-and-onboard.md](../deployment/deploy-and-onboard.md#azure-resource-inventory-minimum-set)).
- **Free tier**: assume the free grants for Container Apps monthly compute and Log Analytics
  first-GB ingestion are **not** consumed by unrelated workloads.
- **Model cost (T1/T2 inference)**: when `enable_llm=true`, Azure OpenAI/Foundry token or
  provisioned-capacity cost is added and reported separately in [T2 LLM Cost](#t2-llm-cost).
  Model spend is bounded by the model budget cap in
  [llm-strategy.md](../architecture/llm-strategy.md); overflow degrades to HIL, never uncapped inference.
- **Non-Azure targets**: Azure is the current implementation target; this document does not model
  costs for other CSPs.

Every subsequent figure is subject to these assumptions.

## Cost Categories

Costs split into two categories; the shape of each resource's spend is stable even if the
absolute number moves:

- **Fixed** - accrues even when the system is idle (managed service base charges, standing
  storage).
- **Variable** - proportional to traffic (compute-seconds, ingestion GB, delivery
  operations).

## Per-Resource Estimate

Every row cites the resource in [deploy-and-onboard.md](../deployment/deploy-and-onboard.md#azure-resource-inventory-minimum-set).
Ranges are the expected month-to-month band under baseline traffic; the upper bound reflects
a moderately busier month.

| # | Resource | Cost model | Baseline monthly (USD) | Category | Notes |
|---|----------|-----------|------------------------|----------|-------|
| 1 | Container Apps environment | environment fee = $0; vCPU-second + GB-second consumption | **recalculate from current plan** | variable | depends on the core replica floor and enabled app count |
| 2 | Container App (unified core, one Python process) | rolled into #1 | rolled into #1 | variable | default `min_replicas = 1`, `max_replicas = 3`; zero requires a verified lag scaler |
| 3 | Container Apps Jobs | rolled into #1 | **recalculate from current plan** | variable | scheduler, out-of-band, inventory, canary, and enabled worker jobs share Consumption usage |
| 4 | Event Hubs **Standard** namespace (1 TU, auto-inflate off) | throughput unit hourly (~$0.03/hr × 730h) + ingress events (~$0.028/million) | **≈ $22** | fixed | consumed as the Kafka wire event bus on `:9093`; DLQ is a Kafka `<topic>.dlq` convention, no extra resource |
| 5 | Event Grid inventory subscription + Diagnostic Settings | Event Grid delivery operations plus destination-service usage | **recalculate from current plan** | variable | no custom topic; inventory events go to Event Hubs and diagnostics to Log Analytics |
| 6 | PostgreSQL Flexible **Burstable B1ms** (1 vCore, 2 GB) | compute + storage + backup | **≈ $20 - $25** | fixed | compute ≈$15, 32 GB SSD ≈$4, 7-day backup ≈$3-5 |
| 7 | Key Vault Standard | ~$0.03 per 10k operations | **≈ $1** | variable (bounded) | low at baseline |
| 8 | User-assigned Managed Identity | free | **$0** | - | |
| 9 | Log Analytics workspace | ingestion ~$2.30/GB (Analytics logs); retention within 30 days is free | **$5 - $15** | variable | ingestion volume is the main driver |
| 10 | Azure Container Registry (Basic) | fixed daily fee (~$0.167) + 10 GB storage included | **≈ $5** | fixed | Standard tier ≈$20 if geo-replication or higher storage is later needed |

Non-billable elements included in the deployment (see
[deploy-and-onboard.md](../deployment/deploy-and-onboard.md#azure-resource-inventory-minimum-set)):

- Azure Bot Free tier is supplied separately by downstream deployments that enable Teams; upstream
  Terraform does not provision it by default.
- Static Web Apps Free tier (read-only console hosting).
- App registration + workload identity federation.
- Diagnostic Settings forwarders themselves (cost sits in the Event Hubs row).

## Monthly Envelope (Historical Planning Snapshot, Model Cost Excluded)

Combining the categories above under the baseline assumptions:

| Bucket | Contents | Monthly (USD) |
|--------|----------|---------------|
| **Fixed** | Event Hubs + PostgreSQL + ACR | **≈ $47 - $52** |
| **Variable** | Container Apps/jobs under the original scale-to-zero assumption + Key Vault + Log Analytics | **≈ $6 - $28** |
| **Total (original minimum-set example)** | not an estimate of the current Terraform topology | **≈ $53 - $80 / month (historical)** |

This total assumes the original scale-to-zero topology and MUST NOT be used as the budget for the
current core with `min_replicas = 1`. Before deployment, extract enabled resources and SKUs from
`terraform plan` and recalculate them with Azure Pricing Calculator or the Retail Prices API.
Production HA PostgreSQL, private networking, Azure OpenAI, document ingestion, the read
API/console, and email channels are separate line items.

### Current Terraform inventory reconciliation

| Scope | Current resources | Estimate treatment |
|-------|-------------------|--------------------|
| Base | Container Apps environment, one core replica, scheduled jobs, Event Hubs, Event Grid inventory subscription, PostgreSQL, Key Vault, identities, Log Analytics/Application Insights, ACR, canary | Recalculate every enabled SKU and replica/resource usage from the plan. |
| Production delta | Zone-redundant PostgreSQL HA, 35-day geo backup, private networking/DNS, and private runner path | Price separately from the dev B1ms band. |
| `enable_llm` | Azure OpenAI/Foundry account and capability deployments | Add token/PTU and embedding usage to the model budget. |
| `enable_document_ingestion` | ADLS Gen2 ZRS/HNS, blob/dfs private endpoints, ingestion app + ClamAV, migration worker | Price storage capacity/operations, endpoints, and always-on replicas separately. |
| Channel/console opt-in | Read API/channel app, Static Web Apps, ACS Email/SMS, and other enabled adapters | Price from actual enablement and delivery volume. |

## T2 LLM Cost

Reasoning-tier (T2) inference is a **usage or provisioned-capacity cost** separated from the fixed
infrastructure total. The current implementation supports opt-in Azure OpenAI/Foundry deployments;
[llm-strategy.md](../architecture/llm-strategy.md) governs model choice and the budget gate. It is reported separately because:

- It varies by orders of magnitude with the model family and the mixed-model cross-check
  requirement (each T2 judgment invokes at least two distinct models per
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).
- It is capped by a budget in configuration; overflow **degrades to HIL**, never to uncapped
  inference.

Rough envelope, keyed to monthly event volume, assuming ~10% of events reach T2, each T2
judgment invokes 2 distinct models, and average prompts fit in ~3 k input + ~500 output
tokens:

| Monthly events | T2 judgments (10%) | Small-model tier | Mid-model tier | Frontier tier |
|----------------|--------------------|------------------|----------------|---------------|
| 10 k | ~1 k | **$5 - $15** | **$30 - $100** | **$100 - $500** |
| 100 k | ~10 k | **$50 - $150** | **$300 - $1,000** | **$1,000 - $5,000** |

Rules that hold regardless of model choice:

- The **budget cap is the ceiling**; exceeding it does not spend more, it queues findings to
  HIL.
- Model choice is **configuration**, not code
  ([llm-strategy.md](../architecture/llm-strategy.md)); a swap by measured cost/quality is safe.
- Provider-side rate limits and per-request timeout keep any single event from blowing the
  cap in isolation.

**Measuring provider usage.** The figures above are an *envelope*, not an invoice. Each
model call's provider-measured `usage` (prompt + completion tokens) is captured by a
`MeteringSink`. `LlmCostPanel` retains the compatibility path `GET /kpi/llm-cost`, but its
operator projection exposes tokens only: by workload scope, model, invocation,
conversation, day, and month. Configured pricing can still support an internal budget gate;
the console doesn't present it as actual spend because regional and negotiated rates vary (see
[operator-console.md § 4.4](operator-console.md#44-cost-and-rate-limits)).

## Traffic Scaling

How the envelope moves as event volume grows. This is the trigger set for revisiting the
inventory, not a hard SLA.

| Scenario | Expected infra monthly | First items to press | Recommended action |
|----------|------------------------|----------------------|--------------------|
| **Baseline (≤10 k events/mo)** | current plan + measured usage | core replica floor, standing services | validate the enabled minimum set and budgets |
| **10 k - 100 k events/mo** | recalculate from plan + telemetry | Log Analytics ingestion, Container Apps compute | keep tiers; set a Log Analytics **daily cap**; watch ingestion budget alert |
| **100 k - 1 M events/mo** | recalculate from plan + telemetry | Log Analytics ingestion, Container Apps compute, PostgreSQL storage | consider **Basic Logs** for audit stream, PostgreSQL storage tier up, and core replica/resource sizing |
| **≥ 1 M events/mo** | re-model | most rows | re-run the inventory review; evaluate Event Hubs additional TUs or Dedicated, PostgreSQL General Purpose, dedicated vector store |

The graduation triggers (core replica/resource sizing, PostgreSQL tier up, Log Analytics
split) are captured in [Open Decisions](#open-decisions).

## Optimization Options

Applied opportunistically as spend approaches the envelope's upper bound. Each option has a
specific trade-off documented so the choice is not made blind.

| Option | Savings | Trade-off |
|--------|---------|-----------|
| **Reserved Instance / Savings Plan** on PostgreSQL (1-year or 3-year) | 30-55% off compute | commitment to the tier; downgrade needs early-termination |
| **Log Analytics daily cap** | prevents runaway ingestion months | over-cap logs are dropped or throttled per the workspace policy |
| **Basic Logs tier** for the audit stream | ~74% off Analytics-tier ingestion | slower / paid queries against Basic Logs (kept as-is for archival + occasional replay) |
| **ACR retention policy** on untagged manifests | small storage savings | old debug images are pruned; keep signed release digests explicitly |
| **Set replica floors per workload** | scheduled jobs return to zero; core defaults to 1 | core needs an Event Hubs lag scaler and wake-up verification before using 0 |
| **MCAPS / Founder Hub / free trial credits** | offsets first months entirely | eligibility is time-boxed; not a durable lever |
| **Move console images to GHCR** | saves ACR Basic (~$5/mo) | mixes registries - only worth it if the fork is not tightly Azure-integrated (fork chose ACR - see [deploy-and-onboard.md](../deployment/deploy-and-onboard.md#azure-resource-inventory-minimum-set)) |

### Warm-capacity policy (cold-start vs MTTR)

Scale-to-zero is a target for eligible jobs and lanes, not the current core default. Blanket min-replicas = 0 pushes cold-start
latency onto MTTR for urgent recovery - a SEV1 failover cannot wait for a
container to boot. `core/capacity/warm_pool.py` (`WarmCapacityPolicy`) resolves
the tension deterministically: it recommends a **warm** lane (min-replicas > 0)
only for the work that cannot absorb a cold start - incidents at or above a
configured severity (default SEV2), an active event storm (a burst of
remediations that would otherwise serialize on cold starts), and off-hours (when
no human is already warm at the console so autonomous recovery is the only fast
path) - and leaves scaler-backed, wake-up-verified lanes on scale-to-zero. The thresholds are
fork-tunable config, and the policy is a pure recommendation: the deployment
layer reads the `min_replicas` floor at plan time and the runtime reads
`warm_required` per action class. This keeps the idle-cost envelope intact while
protecting recovery latency where it matters.

## What the Envelope Does Not Cover

Costs deliberately outside this document:

- **T1/T2 model usage or provisioned capacity** - reported separately in [T2 LLM Cost](#t2-llm-cost).
- **Human labor** - operator on-call time, HIL approver time.
- **GitHub / Azure DevOps** - GitOps host is a non-Azure cost (see the same category note in
  [deploy-and-onboard.md](../deployment/deploy-and-onboard.md#prerequisites)).
- **DR / secondary-region resources** - outside the current minimum inventory and estimated from a
  separate deployment topology and plan.
- **Network egress at scale** - assumed negligible at baseline; revisit when traffic reaches
  the 100 k / month tier.

## Related Documents

- [deploy-and-onboard.md](../deployment/deploy-and-onboard.md) - the inventory this document estimates.
- [tech-stack.md](../architecture/tech-stack.md) - the service selection rationale.
- [llm-strategy.md](../architecture/llm-strategy.md) - T2 model choice, budget cap.
- [goals-and-metrics.md](../architecture/goals-and-metrics.md) - the measurement-first rule that governs any
  cost-per-unit claim.

## Open Decisions

- [ ] Concrete tier values within the minimum set (PostgreSQL storage, Log Analytics daily
      cap, ACR retention window, Event Hubs throughput-unit ceiling).
- [ ] Graduation triggers: **numeric thresholds** at which each cost row is re-tiered
      (event/month rate that triggers PostgreSQL step-up, Basic Logs split, or core replica/resource
      resizing).
- [ ] T2 model tier choice (small / mid / frontier) and the per-tenant monthly budget cap.
- [ ] `pricing.confirmed_at` mechanism on the fork's cost dashboard - how and how often the
      numbers in this document are re-verified against the Azure Pricing Calculator.
- [ ] Whether Reserved Instances / Savings Plans are procured on day zero or after the first
      30-day live baseline.
