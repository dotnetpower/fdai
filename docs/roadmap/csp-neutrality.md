# CSP-Neutrality Contracts

Names the concrete **contracts** that keep the core CSP-neutral even though
[Azure is the only implemented target](../../.github/copilot-instructions.md#implementation-focus-must).
The contracts are wire-level (protocols, artifacts, token formats) so that a future non-Azure
adapter is **additive configuration**, not a core rewrite.

Complements the topology in
[app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md), the module
boundaries in [project-structure.md](project-structure.md), the tech choices in
[tech-stack.md](tech-stack.md), and the identity model in
[security-and-identity.md](security-and-identity.md).

## Principle

Anything the core touches from a cloud provider MUST be reached through **one wire-level
contract per concern**, not through a vendor SDK. The Azure implementation of each contract
is what we build today; a fork or a future phase adds another CSP by registering a new
implementation of the **same contract**, without editing `core/`.

Four contracts govern the CSP-touching surface:

| # | Contract | Wire / artifact | Azure implementation |
|---|----------|-----------------|----------------------|
| 1 | **Event bus** | Apache Kafka wire protocol | Event Hubs (Kafka endpoint on port `9093`) |
| 2 | **Runtime** | OCI container image + Knative-compatible manifest subset | Container Apps (Consumption, KEDA) |
| 3 | **Secret** | environment variables (or K8s Secret mount) — never a CSP secret SDK call from the app | Container Apps native secret + Key Vault reference |
| 4 | **Workload identity** | OIDC token (federated) | User-assigned Managed Identity + workload identity federation |

Every one of the four MUST NOT leak provider specifics into `core/`. See
[Anti-Patterns](#anti-patterns) for the concrete violations to reject.

## 1. Event Bus Contract — Kafka Wire Protocol

The event bus is expressed as a **Kafka producer/consumer** with a small,
provider-independent surface (`bootstrap.servers`, `sasl.mechanism`, `security.protocol`,
plus a per-provider token/credential source). All three major CSPs and multiple
multi-cloud vendors expose a Kafka-compatible endpoint, so the same client library and the
same code path serve every target.

| CSP / vendor | Managed Kafka endpoint | Auth mechanism | Notes |
|---|---|---|---|
| Azure | **Event Hubs** (Kafka 1.0+ endpoint, `<ns>.servicebus.windows.net:9093`) | SASL/OAUTHBEARER with Entra token | one namespace hosts topics; idle cost stays low on Standard 1 TU |
| AWS | **MSK Serverless** | SASL/OAUTHBEARER with AWS IAM SigV4 | truly serverless (partition-hour billed) |
| GCP | **Managed Service for Apache Kafka** (GA) | SASL/OAUTHBEARER with Google IAM token | broker fleet is always-on; use the smallest cluster |
| Multi-cloud | **Confluent Cloud** / **Redpanda Cloud** / **Aiven Kafka** | SASL/PLAIN or SASL/OAUTHBEARER | escape hatch when vendor-lock even to a hyperscaler is unacceptable |
| Self-hosted | **Strimzi Kafka** on AKS/EKS/GKE, or **Redpanda** | SASL or mTLS | last resort; adds ops burden |

**Rules (MUST):**

- The core produces/consumes with a **Kafka client only** (e.g. `librdkafka`, `kafka-python`,
  `KafkaJS`, `Sarama`); no `ServiceBusClient`, `SqsClient`, `PubSubClient`, or any other
  vendor SDK is imported.
- The event schema uses **CloudEvents envelope** on top of JSON Schema
  ([tech-stack.md](tech-stack.md)); this stays identical across providers.
- **DLQ** = a Kafka **dead-letter topic** with a naming convention (e.g. `<topic>.dlq`)
  plus a redrive worker; providers that offer native DLQ (Event Hubs does not) MUST be
  ignored in favor of the topic convention so behavior is uniform.
- **Ordering** is preserved by partition key (per-resource key ⇒ per-resource ordering).
  Any provider-specific ordering primitive (Service Bus sessions, FIFO groups) MUST NOT
  leak into core.
- **Idempotency** is enforced by the app-level idempotency key on the event, not by
  provider "exactly-once" flags.

**Anti-patterns (MUST NOT):**

- Using Event Hubs through the AMQP native SDK (or the Service Bus SDK). If Event Hubs is
  chosen, **only the Kafka endpoint on `:9093`** is permitted.
- Using Dapr's pub/sub building block — it adds a sidecar dependency and re-locks the
  runtime layer.

## 2. Runtime Contract — OCI Image + Knative-Compatible Manifest

The core ships as one or more **OCI container images** and a small **Knative-compatible
manifest subset** describing traffic, revisions, autoscaling triggers, health probes, and
env/secret bindings. Provider adapters render this into the CSP-specific resource shape.

| CSP / substrate | Runtime | Scale-to-zero | Deployment shape rendered from the contract |
|---|---|---|---|
| Azure | **Container Apps** (Consumption + KEDA) | ✓ | `containerapp` resource generated from the manifest via Bicep/Terraform |
| AWS | **App Runner** (request-based) or **ECS Fargate** + KEDA | App Runner ✓ / Fargate — | rendered from the same manifest |
| GCP | **Cloud Run** (services & jobs) | ✓ | Cloud Run is native Knative; the manifest applies directly |
| Any K8s (AKS/EKS/GKE) | **Knative Serving** + KEDA | ✓ | manifest applies directly |
| Fallback | bare `Deployment` + HPA + KEDA | — (idle ≥ 1 replica) | rendered when scale-to-zero is unavailable |

**Rules (MUST):**

- The image exposes standard **`/healthz` and `/readyz`** endpoints. Container Apps probes,
  K8s probes, App Runner probes, and Cloud Run probes all point at these two.
- **Scale triggers are contract-level signals** (e.g. `scale-on: kafka-lag`, or a CPU
  target). Provider adapters translate them to KEDA CRDs, App Runner concurrency,
  Cloud Run CPU utilization, etc.
- The core does **NOT** depend on Dapr sidecars, Envoy-specific ingress annotations, or any
  Container Apps-only feature (e.g. built-in KEDA scaler references that only exist in
  Container Apps YAML).
- Where Azure ships a scheduled worker as a Container Apps Job, other providers render the
  same contract as a K8s `CronJob`, an AWS EventBridge-triggered task, or a Cloud Run Job —
  all interchangeable.

**Anti-patterns (MUST NOT):**

- Baking Container Apps-only YAML (Dapr components, native KEDA scaler refs) into the
  application's own repo.
- Requiring an Envoy-flavored ingress rule; use a portable ingress abstraction or handle
  the routing in-app.

## 3. Secret Contract — Environment / K8s Secret

The application reads **only environment variables** (or, on Kubernetes, files mounted from a
`Secret`). It **never** calls a CSP secret SDK directly. The injection layer bridges the
CSP secret backend to the container's environment.

| CSP / substrate | Injection layer | Backend | Auth |
|---|---|---|---|
| Azure Container Apps | native `secret` field with **Key Vault reference** | Key Vault | user-assigned MI |
| Any K8s | **External Secrets Operator (ESO)** with a `SecretStore` CRD | Key Vault / AWS Secrets Manager / GCP Secret Manager / Vault | Workload Identity per CSP |
| AWS (ECS/App Runner) | native task-def secret reference | Secrets Manager / Parameter Store | IRSA |
| GCP (Cloud Run) | native environment-from-secret reference | Secret Manager | Workload Identity |
| Multi-cloud OSS | **ESO + HashiCorp Vault** | Vault | JWT/OIDC |
| Dev/local | file / `sops`-encrypted git | files | GPG/age |

**Rules (MUST):**

- The core reads secrets **only** through the injected `SecretProvider` interface in
  `shared/providers/` ([project-structure.md](project-structure.md#injectable-seams)); no
  `SecretClient` from any vendor SDK appears in `core/`.
- **Secret names follow a stable schema** (upper-snake env var names) across all providers so
  the app is provider-blind.
- **Fail-closed**: if the injection layer cannot resolve a required secret at startup, the
  process fails fast — it never falls back to a cached or embedded value
  ([security-and-identity.md](security-and-identity.md#secrets-and-config)).
- **Rotation** is the injection layer's job; the app tolerates a rolled secret by re-reading
  env on process restart. Long-lived caches of decrypted secret material are prohibited.

**Anti-patterns (MUST NOT):**

- Calling `SecretClient.GetSecret()` (or the equivalent) from application code.
- Committing plaintext or encrypted secrets to source (SOPS in git is allowed **only** for
  dev/local; never for staging or prod).

## 4. Workload Identity Contract — OIDC Token

The executor authenticates to the CSP with a **short-lived OIDC token** obtained from the
runtime substrate; the token is exchanged for CSP credentials at the adapter boundary. No
long-lived key or shared secret is held by the executor.

| CSP / substrate | Workload identity primitive | Token exchange |
|---|---|---|
| Azure | User-assigned Managed Identity | IMDS → Entra token (SASL/OAUTHBEARER, ARM, KV) |
| AWS | IAM Roles for Service Accounts (IRSA) | pod token → `AssumeRoleWithWebIdentity` |
| GCP | Workload Identity Federation | K8s SA token → GCP STS |
| Any K8s | **SPIFFE/SPIRE** | SVID (JWT/X.509) exchanged per adapter |
| CI/CD | GitHub Actions OIDC / Azure DevOps federated credential | issuer → CSP-side federation trust |

**Rules (MUST):**

- The core sees only a `WorkloadIdentity` interface exposing "get a token audience-scoped to
  X"; the concrete token issuer is a provider-adapter concern.
- **Approval identity ≠ execution identity** ([security-and-identity.md](security-and-identity.md#execution-identity)).
  This holds across every CSP mapping above.
- **No long-lived keys** in the executor's process, config, or secret store. Where a
  CSP-side credential is unavoidable (e.g. legacy service), it MUST be short-lived and
  auto-rotated, and its use MUST be recorded in the audit log.

**Anti-patterns (MUST NOT):**

- `DefaultAzureCredential()` or any similarly named SDK entry point in `core/` — that is a
  vendor SDK call, not the contract. It is allowed **only** in the Azure provider adapter,
  behind the interface.
- Sharing the executor's identity with the console, ChatOps, or any read-only surface.

## Azure-Phase Realization (Summary)

Today's implementation slots into the four contracts as follows. Every named service is a
**recommendation to confirm at adoption time** ([tech-stack.md](tech-stack.md)); the
contract is what does not change.

| Contract | Azure realization | Idle cost posture |
|---|---|---|
| Event bus | **Event Hubs Standard** (Kafka endpoint on `:9093`, 1 TU, auto-inflate off) | low idle; scales on TU |
| Runtime | **Container Apps** (Consumption, KEDA scale-to-zero) — one app + sidecars | `$0` when idle |
| Secret | Container Apps native secret + **Key Vault reference** | negligible |
| Workload identity | **User-assigned MI** + workload identity federation for CI/CD | free |

`Service Bus` and `Event Grid` are **not** in the minimum inventory going forward; the
event bus is Kafka wire only. Any provider-native pub/sub is used solely as a **source of
events into the Kafka bus** (e.g. an Event Grid subscription that forwards to an Event Hubs
Kafka topic) and never as a runtime dependency of `core/`.

## Non-Azure Path (Additive)

Adding another CSP is a **fork-level configuration exercise**, not a core change:

1. Register a new implementation of the four provider interfaces in `shared/providers/` at
   the composition root ([project-structure.md](project-structure.md#customization-via-dependency-injection)).
2. Point `bootstrap.servers`, the `SecretProvider`, the `RuntimeAdapter`, and the
   `WorkloadIdentity` bindings at the new CSP.
3. Render the same OCI image + Knative-compatible manifest into the target runtime.
4. Ship in **shadow mode** ([architecture.instructions.md](../../.github/instructions/architecture.instructions.md#safety-invariants))
   until parity with the Azure implementation is measured.

**Non-Azure targets remain TBD**
([Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must));
the contract exists so a future adapter is additive.

## Anti-Patterns (concise)

- Wrapping each CSP's native pub/sub (`Service Bus` + `SQS/SNS` + `Pub/Sub`) behind one
  interface. Ack semantics, ordering keys, DLQ shapes, and exactly-once behavior diverge
  enough that provider-specific bugs leak through — **use one wire protocol (Kafka) instead**.
- Introducing **Dapr** as a portability layer. It moves the lock-in from the CSP to Dapr,
  adds a sidecar dependency, and complicates local dev.
- Using **Event Hubs via the native AMQP SDK** to "save on Kafka client complexity." That
  re-Azurizes the code. Use the Kafka endpoint or don't use Event Hubs.
- Reading secrets by calling `SecretClient` from application code (see contract 3).
- `DefaultAzureCredential()` (or its equivalents) inside `core/` (see contract 4).

## Related Docs

- [tech-stack.md](tech-stack.md) — the concrete stack that realizes these contracts.
- [deploy-and-onboard.md](deploy-and-onboard.md#azure-resource-inventory-minimum-set) — the
  Azure resource inventory rendered from the contracts.
- [security-and-identity.md](security-and-identity.md) — identity model and secret
  handling in depth.
- [project-structure.md](project-structure.md#injectable-seams) — the DI seams that
  expose each contract to the composition root.
