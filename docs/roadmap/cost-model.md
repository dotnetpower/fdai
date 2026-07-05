# Cost Model (Illustrative)

Estimated monthly cost of the minimum Azure resource inventory defined in
[deploy-and-onboard.md](deploy-and-onboard.md#azure-resource-inventory-minimum-set), broken
down by fixed vs variable spend and by traffic scenario. Cost-efficiency principles come from
[deploy-and-onboard.md](deploy-and-onboard.md#cost-efficiency-principles).

> **Illustrative — not a quote.** Azure list prices change by region, over time, and by
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
  reduce these by 5–20%; Reserved Instances / Savings Plans can reduce compute + database
  spend by 30–60% on 1-year / 3-year terms.
- **Traffic (baseline)**: **low traffic** — events in the thousands to tens of thousands per
  month, KEDA holds the core Container App at zero replicas most of the time.
- **Retention**: Log Analytics 30-day default
  ([deploy-and-onboard.md](deploy-and-onboard.md#azure-resource-inventory-minimum-set)).
- **Free tier**: assume the free grants for Container Apps monthly compute and Log Analytics
  first-GB ingestion are **not** consumed by unrelated workloads.
- **LLM cost (T2 inference)**: **excluded from the infrastructure envelope** and reported
  separately in [T2 LLM Cost](#t2-llm-cost). LLM spend is bounded by the model budget cap in
  [llm-strategy.md](llm-strategy.md); overflow degrades to HIL, never uncapped inference.
- **Non-Azure targets**: TBD per
  [Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must);
  cost estimates for other CSPs are not modeled here.

Every subsequent figure is subject to these assumptions.

## Cost Categories

Costs split into two categories; the shape of each resource's spend is stable even if the
absolute number moves:

- **Fixed** — accrues even when the system is idle (managed service base charges, standing
  storage).
- **Variable** — proportional to traffic (compute-seconds, ingestion GB, delivery
  operations).

## Per-Resource Estimate

Every row cites the resource in [deploy-and-onboard.md](deploy-and-onboard.md#azure-resource-inventory-minimum-set).
Ranges are the expected month-to-month band under baseline traffic; the upper bound reflects
a moderately busier month.

| # | Resource | Cost model | Baseline monthly (USD) | Category | Notes |
|---|----------|-----------|------------------------|----------|-------|
| 1 | Container Apps environment | environment fee = $0; vCPU-second + GB-second consumption | **$0 – $10** | variable | free monthly grant (≈180k vCPU-s + 360k GB-s) often absorbs low traffic |
| 2 | Container App (unified core, 4 sidecars) | rolled into #1 | rolled into #1 | variable | KEDA scale-to-zero |
| 3 | Container Apps Job (probes) | rolled into #1 | **$0 – $2** | variable | short scheduled runs share the free grant |
| 4 | Event Hubs **Standard** namespace (1 TU, auto-inflate off) | throughput unit hourly (~$0.03/hr × 730h) + ingress events (~$0.028/million) | **≈ $22** | fixed | consumed as the Kafka wire event bus on `:9093`; DLQ is a Kafka `<topic>.dlq` convention, no extra resource |
| 5 | Diagnostic Settings forwarders (Activity Log / resource events) | free plumbing; the destination Event Hubs TU cost sits in row 4 | **$0** | — | replaces standalone Service Bus + Event Grid custom topics from the previous inventory |
| 6 | PostgreSQL Flexible **Burstable B1ms** (1 vCore, 2 GB) | compute + storage + backup | **≈ $20 – $25** | fixed | compute ≈$15, 32 GB SSD ≈$4, 7-day backup ≈$3–5 |
| 7 | Key Vault Standard | ~$0.03 per 10k operations | **≈ $1** | variable (bounded) | low at baseline |
| 8 | User-assigned Managed Identity | free | **$0** | — | |
| 9 | Log Analytics workspace | ingestion ~$2.30/GB (Analytics logs); retention within 30 days is free | **$5 – $15** | variable | ingestion volume is the main driver |
| 10 | Azure Container Registry (Basic) | fixed daily fee (~$0.167) + 10 GB storage included | **≈ $5** | fixed | Standard tier ≈$20 if geo-replication or higher storage is later needed |

Non-billable elements included in the deployment (see
[deploy-and-onboard.md](deploy-and-onboard.md#azure-resource-inventory-minimum-set)):

- Azure Bot Free tier (Teams Adaptive Cards for HIL).
- Static Web Apps Free tier (read-only console hosting).
- App registration + workload identity federation.
- Diagnostic Settings forwarders themselves (cost sits in the Event Hubs row).

## Monthly Envelope (Baseline, T2 LLM Excluded)

Combining the categories above under the baseline assumptions:

| Bucket | Contents | Monthly (USD) |
|--------|----------|---------------|
| **Fixed** | Event Hubs + PostgreSQL + Key Vault + ACR + Log Analytics baseline | **≈ $53** |
| **Variable** | Container Apps compute + Log Analytics ingestion above baseline | **$5 – $20** |
| **Total (infrastructure only)** | | **≈ $58 – $75 / month** |

A deployment that stays idle for most of the month (KEDA at 0 replicas, no ingest bursts) is
closer to the lower bound; a deployment absorbing steady event traffic and telemetry lands
mid-range.

## T2 LLM Cost

Reasoning-tier (T2) inference is **not an Azure resource line** — it is external model API
spend governed by [llm-strategy.md](llm-strategy.md). Reported separately because:

- It varies by orders of magnitude with the model family and the mixed-model cross-check
  requirement (each T2 judgment invokes at least two distinct models per
  [architecture.instructions.md](../../.github/instructions/architecture.instructions.md)).
- It is capped by a budget in configuration; overflow **degrades to HIL**, never to uncapped
  inference.

Rough envelope, keyed to monthly event volume, assuming ~10% of events reach T2, each T2
judgment invokes 2 distinct models, and average prompts fit in ~3 k input + ~500 output
tokens:

| Monthly events | T2 judgments (10%) | Small-model tier | Mid-model tier | Frontier tier |
|----------------|--------------------|------------------|----------------|---------------|
| 10 k | ~1 k | **$5 – $15** | **$30 – $100** | **$100 – $500** |
| 100 k | ~10 k | **$50 – $150** | **$300 – $1,000** | **$1,000 – $5,000** |

Rules that hold regardless of model choice:

- The **budget cap is the ceiling**; exceeding it does not spend more, it queues findings to
  HIL.
- Model choice is **configuration**, not code
  ([llm-strategy.md](llm-strategy.md)); a swap by measured cost/quality is safe.
- Provider-side rate limits and per-request timeout keep any single event from blowing the
  cap in isolation.

## Traffic Scaling

How the envelope moves as event volume grows. This is the trigger set for revisiting the
inventory, not a hard SLA.

| Scenario | Expected infra monthly | First items to press | Recommended action |
|----------|------------------------|----------------------|--------------------|
| **Baseline (≤10 k events/mo)** | $45 – $70 | (none) | keep the minimum set |
| **10 k – 100 k events/mo** | $70 – $150 | Log Analytics ingestion, Container Apps compute | keep tiers; set a Log Analytics **daily cap**; watch ingestion budget alert |
| **100 k – 1 M events/mo** | $200 – $500 | Log Analytics ingestion (dominant), Container Apps compute, PostgreSQL storage | consider **Basic Logs** for audit stream (~74% ingestion saving vs Analytics logs), PostgreSQL storage tier up, review sidecar → separate Container App graduation |
| **≥ 1 M events/mo** | re-model | most rows | re-run the inventory review; evaluate Event Hubs additional TUs or Dedicated, PostgreSQL General Purpose, dedicated vector store |

The graduation triggers (sidecar → separate Container App, PostgreSQL tier up, Log Analytics
split) are captured in [Open Decisions](#open-decisions).

## Optimization Options

Applied opportunistically as spend approaches the envelope's upper bound. Each option has a
specific trade-off documented so the choice is not made blind.

| Option | Savings | Trade-off |
|--------|---------|-----------|
| **Reserved Instance / Savings Plan** on PostgreSQL (1-year or 3-year) | 30–55% off compute | commitment to the tier; downgrade needs early-termination |
| **Log Analytics daily cap** | prevents runaway ingestion months | over-cap logs are dropped or throttled per the workspace policy |
| **Basic Logs tier** for the audit stream | ~74% off Analytics-tier ingestion | slower / paid queries against Basic Logs (kept as-is for archival + occasional replay) |
| **ACR retention policy** on untagged manifests | small storage savings | old debug images are pruned; keep signed release digests explicitly |
| **Container Apps min-replicas = 0 everywhere** | already the default; keep it | cold-start latency counted per [operating-and-verification.md](operating-and-verification.md#self-health-signals) |
| **MCAPS / Founder Hub / free trial credits** | offsets first months entirely | eligibility is time-boxed; not a durable lever |
| **Move console images to GHCR** | saves ACR Basic (~$5/mo) | mixes registries — only worth it if the fork is not tightly Azure-integrated (fork chose ACR — see [deploy-and-onboard.md](deploy-and-onboard.md#azure-resource-inventory-minimum-set)) |

## What the Envelope Does Not Cover

Costs deliberately outside this document:

- **T2 LLM API spend** — reported separately in [T2 LLM Cost](#t2-llm-cost).
- **Human labor** — operator on-call time, HIL approver time.
- **GitHub / Azure DevOps** — GitOps host is a non-Azure cost (see the same category note in
  [deploy-and-onboard.md](deploy-and-onboard.md#prerequisites)).
- **DR / secondary-region resources** — deferred to Phase 4 (TBD) per
  [Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must).
- **Network egress at scale** — assumed negligible at baseline; revisit when traffic reaches
  the 100 k / month tier.

## Related Documents

- [deploy-and-onboard.md](deploy-and-onboard.md) — the inventory this document estimates.
- [tech-stack.md](tech-stack.md) — the service selection rationale.
- [llm-strategy.md](llm-strategy.md) — T2 model choice, budget cap.
- [goals-and-metrics.md](goals-and-metrics.md) — the measurement-first rule that governs any
  cost-per-unit claim.

## Open Decisions

- [ ] Concrete tier values within the minimum set (PostgreSQL storage, Log Analytics daily
      cap, ACR retention window, Event Hubs throughput-unit ceiling).
- [ ] Graduation triggers: **numeric thresholds** at which each cost row is re-tiered
      (event/month rate that triggers PostgreSQL step-up, Basic Logs split, sidecar → its
      own Container App).
- [ ] T2 model tier choice (small / mid / frontier) and the per-tenant monthly budget cap.
- [ ] `pricing.confirmed_at` mechanism on the fork's cost dashboard — how and how often the
      numbers in this document are re-verified against the Azure Pricing Calculator.
- [ ] Whether Reserved Instances / Savings Plans are procured on day zero or after the first
      30-day live baseline.
