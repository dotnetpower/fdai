---
title: Exposure Reasoning
---

# Exposure Reasoning

This document defines how FDAI finds unsafe externally reachable resource compositions that have no
CVE, advisory, or product defect behind them. It reasons over the operating ontology instead of
matching known signatures, so a "by design" gap such as an API Management developer portal whose
sign-up is hidden but not disabled becomes a grounded, explainable finding.

> **Authority boundary:** Exposure reasoning reads and concludes. It never approves, executes,
> promotes, or changes a resource. Every conclusion is evidence with a stated grade, and every
> remediation goes through the existing ActionType, approval, and seven-safeguard path.

> **Status:** Proposed design. New capabilities start in shadow mode. Nothing here is implemented;
> see the [implementation ledger](../../roadmap-implementation/operations/exposure-reasoning.md).

## Design at a glance

A CVE answers "does this product version contain a known defect?" The harder question is "does
this combination of facts let an anonymous party reach something it should not?" FDAI answers it
in four steps:

```text
1. Model     Resource -> Endpoint, with reachability, identity, and data reach as typed facts
2. Contrast  intent (what is declared) vs enforcement (what actually answers)
3. Compose   reviewed ExposureMechanism rules join facts into an exposure path
4. Conclude  holds | refuted | unknown, with evidence grade and mandatory refutation checks
```

Example: an APIM instance declares `signup.enabled = false`. FDAI also observes a live Basic
identity provider, a Starter product with `approvalRequired = false`, and a public developer-portal
host. Two mechanisms fire, the refutation checks find no Entra-only or approval gate, and the result
is `holds` at grade `configuration-inferred`. A permitted probe can raise it to `probe-confirmed`.

## Why signatures are not enough

| Question | Signature (CVE, policy) | Exposure reasoning |
|----------|-------------------------|--------------------|
| Is a known defect present? | Yes | Not its job |
| Is a control shown as off but still enforced on? | No | Yes: intent vs enforcement |
| Do individually safe settings combine into a risky path? | No | Yes: composition |
| Is a new service family similar to a known gap? | No | Yes: structural fingerprint |
| What if the vendor says "by design"? | Nothing is published | The invariant is still checked |

FDAI does not claim to discover every unknown vulnerability. It detects violations of explicit
security invariants over observed facts. A flaw that breaks no modeled invariant stays invisible.

## Reasoning model

### Five planes

Each exposed resource is described on five planes. A contradiction between two planes is the main
signal, and the reachable data behind the surface sets the impact.

| Plane | Question | Example facts | State-fact lane |
|-------|----------|---------------|-----------------|
| Intent | What does the owner declare? | `signup.enabled = false`, "internal only" tag | `desired` |
| Enforcement | What actually answers or is configured? | Basic identity provider exists, listener answers | `observed` |
| Reachability | Who can reach the entry point? | Public host, custom domain, private endpoint, WAF in front | `observed` |
| Identity | How is a caller admitted or issued a credential? | Identity providers, self-registration, approval policy | `observed` |
| Data reach | What does the surface lead to? | Product -> API -> backend -> data class | `derived` |

Lane separation reuses the existing state-fact metadata, so a provider observation is never decoded
as a derived fact or the reverse.

### Security invariants

An `ExposureMechanism` encodes one reviewed invariant. These are the first set:

| Id | Invariant | Violation pattern |
|----|-----------|-------------------|
| `INV-INTENT` | A control shown as disabled is disabled where it is enforced. | Intent says off, enforcement still accepts the operation. |
| `INV-CRED` | An anonymous caller cannot self-issue a credential for protected data. | Reachable self-registration plus automatic approval plus data reach. |
| `INV-ORIGIN` | A shared multi-tenant entry point validates the origin of state-changing requests. | Host-routed endpoint accepts writes without tenant binding. |
| `INV-MGMT` | A management or admin plane is not internet-reachable without strong authentication. | Public admin or SCM endpoint with a weak or default identity. |
| `INV-DEFAULT` | A default identity, product, or key is not left at its permissive setting. | Built-in object with its shipped permissive value. |

### Three-valued conclusion

A conclusion is `holds`, `refuted`, or `unknown`. Missing evidence is `unknown`, never safe. Each
mechanism lists required refutation checks, as the
[Operational Hypothesis Loop](../rules-and-detection/operational-hypothesis-loop.md) requires for
causal claims. A mechanism with no refutation result stays `unknown`.

### Exposure class

The class comes from a reviewed decision table, not from a model or CVSS. Inputs are the reach of
the entry point, how a credential can be acquired, and the data reach.

| Reach | Credential acquisition | Data reach | Class |
|-------|------------------------|------------|-------|
| Internet, anonymous | Self-issuable without approval | Sensitive or unknown | `critical-potential` |
| Internet, anonymous | Self-issuable without approval | Public only | `medium-potential` |
| Internet, anonymous | Approval-gated | Any | `low-potential` |
| Internet, any tenant | None | Any | `informational` |
| Private or tenant-scoped | Any | Any | `not-exposed` |

Unknown data reach is treated as sensitive. The class describes potential exposure, not exploitation:
correlation of configuration facts never proves that anyone abused the path.

## Evidence tiers

Each fact carries the cheapest tier that supports it. A conclusion records its highest tier and
never claims more.

| Tier | Source | Authority | Notes |
|------|--------|-----------|-------|
| E0 | ARM and Resource Graph configuration | Read-only | Resource properties, SKU, hostnames, network settings. |
| E1 | ARM child-resource reads | Read-only | Identity providers, portal settings, products, subscriptions. These are not in Resource Graph. |
| E2 | Passive public metadata | Read-only | DNS, certificate, and hostname resolution for names the subscription owns. |
| E3 | Non-mutating probe | Separate opt-in scope | Mechanism-declared, side-effect-free request on an owned endpoint. |

E3 is the only tier that touches a live listener. A mechanism may use it only if its review proves
the request cannot create, change, or delete anything. It never submits real credentials or valid
form data, and it stores only a bounded classification of the response. Exploit steps such as
creating an account are out of scope for every tier. Probing endpoints that a subscription does
not own, including internet-wide enumeration, is a non-goal.

## Ontology additions

The [metamodel](../architecture/operating-ontology-metamodel.md) allows a new ObjectType only after
a frozen competency test fails against existing objects. This design reuses `Resource`, `Property`,
`Observation`, `Finding`, `Pattern`, `ConfigurationBaseline`, and `ConfigurationDriftFinding`, and
adds the minimum below, in shadow and `projection_owned`.

| Declaration | Kind | Purpose | Why existing objects fail |
|-------------|------|---------|---------------------------|
| `Endpoint` | ObjectType | An externally addressable entry point of a resource with reachability class, protocol, and plane. | `Resource` cannot hold several independently reachable entry points. |
| `ExposureMechanism` | ObjectType | A reviewed invariant with premises, refutation checks, validation axes, and probe contract. | `DiagnosticMechanism` models failure diagnosis, not safety invariants. |
| `resource_exposes_endpoint` | LinkType | `Resource -> Endpoint`. | New object. |
| `endpoint_reaches_resource` | LinkType | Derived, time-bounded reach from an entry point to a data-bearing resource. | `routes_to` states observed forwarding and proves nothing about reach. |
| `finding_instantiates_mechanism` | LinkType | `Finding -> ExposureMechanism`. | Needed to explain a conclusion. |

A finding reuses `Finding` and the existing `evidence_supports_hypothesis` and
`evidence_refutes_hypothesis` links. `mechanism_validated_by` already links mechanisms to
`BenchmarkValidation` receipts. Both ObjectTypes set `execution_authority: false`.

### Competency questions

These frozen questions decide whether each addition is justified.

| Id | Question |
|----|----------|
| E1 | Which entry points are reachable from the internet, and through which hostname or address? |
| E2 | Where does a declared setting contradict what the resource enforces? |
| E3 | Which anonymous-reachable entry point can lead to a credential, and to which data? |
| E4 | Which of these conclusions is `unknown`, and which fact is missing? |
| E5 | Which other resources share the structural fingerprint of a known gap? |
| E6 | Why was this concluded, and what refutation checks ran? |

## Collaboration

| Agent | Role | Bus boundary |
|-------|------|--------------|
| Huginn | Collects entry-point and child-resource evidence and normalizes it. | Publishes events, no conclusion. |
| Heimdall | Owns the security observation: evaluates mechanisms and publishes the finding. | Existing observation topics, shadow. |
| Forseti | Reviews high-class findings and any remediation proposal. | Verdict only. |
| Norns | Compiles recurring cohorts into candidate mechanisms and patterns. | Inert candidates, off path. |
| Mimir | Promotes or demotes a mechanism through the promotion registry. | Registry outcomes. |

No agent calls another directly. Collaboration uses schema-validated event-bus topics only.

## Inference tiers

1. **T0, deterministic.** Rego rules join ontology facts for reach closure, intent-vs-enforcement
   contradiction, and the decision table. This is the default and the only tier that may produce
   `holds`.
2. **T1, similarity.** A new service family is compared with known mechanisms by structural
   fingerprint: planes present, UI-gated or API-open operations, default identities, and admission
   path. It suggests a candidate, never a conclusion.
3. **T2, residual.** A mixed-model pool proposes candidate invariant violations for a capability graph
   that no mechanism covers. A candidate counts only if it compiles into a checkable predicate over
   observed facts and passes the deterministic verifier. Otherwise it is a recorded hypothesis with
   no finding. T2 is grounded, risk-gated, and approval-gated, and a coding session never invokes
   a live model for it without an explicit request.

## Worked example: API Management developer portal

Facts for one APIM instance, with the lane that carries each.

| Fact | Lane | Tier |
|------|------|------|
| Service SKU belongs to the classic tier family | `observed` | E0 |
| Developer portal host answers publicly (no private network, no IP restriction) | `observed` | E0 |
| `portalsettings/signup.enabled = false` | `desired` | E1 |
| Basic identity provider exists | `observed` | E1 |
| Starter product has `subscriptionRequired = true`, `approvalRequired = false` | `observed` | E1 |
| Product -> API -> backend resource, with data class | `derived` | E1 |

1. `INV-INTENT` fires: intent is off, enforcement still holds a live registration provider.
2. `INV-CRED` fires: reachable portal, self-registration, and no approval gate.
3. `INV-DEFAULT` fires: the built-in Starter product keeps its permissive shipped value.
4. Refutation checks run: Entra as the only provider, approval required on every product, restricted
   or private reach, and backends that require their own authentication. Any one refutes the path.
5. With no refutation and a data-bearing backend, the class is `critical-potential` at grade
   `configuration-inferred`. Unknown data class stays `critical-potential`.
6. If the instance opted into E3, an empty-body request to the sign-up route that returns a
   validation error rather than not-found raises the grade to `probe-confirmed`.

The tier is a modeled property, not an assumption. A classic tier is observed with the portal. For a
tier whose portal behavior has not been verified, the portal facts stay `unknown`, so the instance is
neither marked safe nor marked exposed.

## Learning without new CVEs

New mechanisms come from four reviewed sources: advisories and research on "by design" behavior,
fleet cohorts with the same fingerprint, incident post-mortems, and T2 hypotheses that survived
verification. Each becomes an inert `RuleCandidate` from Norns, runs in shadow against a labeled
corpus, and moves through Mimir's promotion registry on measured recall and false-clear evidence. A
recall or precision regression demotes it. The first corpus case is the APIM sign-up gap, with
negative controls such as an Entra-only portal and an approval-gated product.

## Safety and boundaries

- The repository stays customer-agnostic: mechanisms are catalog data, with no tenant value,
  endpoint, or identifier. A fork adds mechanisms through catalog data without editing core code.
- Probes are opt-in per subscription, scoped to owned endpoints, rate limited, budgeted, audited, and
  limited to a mechanism-declared safe request. Response bodies are never stored.
- A remediation is a proposal. Deleting an identity provider is destructive and needs human approval;
  setting approval required on a product is reversible. Both use the seven safeguards.
- A false-positive exemption reuses the existing exemption lifecycle.
- Incomplete or stale evidence yields `unknown` or a recorded gap, never a clear result.

## Delivery plan

| Phase | Outcome | Exit evidence |
|-------|---------|---------------|
| P0 | Competency questions and a labeled corpus with the APIM case and negative controls. | Frozen test fails on existing objects, which justifies the additions. |
| P1 | Entry-point inventory and E1 child-resource reads for APIM. | Facts appear with lane, tier, and freshness. |
| P2 | T0 mechanisms in shadow for the five invariants. | Corpus recall, zero false clear on negative controls. |
| P3 | Probe contract and E3 for owned endpoints. | Audit receipts showing no mutation. |
| P4 | T1 fingerprint generalization to other services. | Candidates reviewed, none promoted without evidence. |
| P5 | T2 hypothesis lane. | Every candidate verified or recorded as hypothesis. |

## Non-goals

- Exploiting a path, creating accounts, or submitting real credentials.
- Scanning endpoints the subscription does not own, or internet-wide enumeration.
- Guaranteeing discovery of every unknown vulnerability.
- Replacing CVE, Defender, or Azure Policy evaluation. Their results are inputs.
- Autonomous remediation outside the existing approval path.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/operations/exposure-reasoning.md) |
| Objects, links, lanes, identity, and time | [Operating Ontology](../architecture/operating-ontology.md) |
| Declaration kinds and the new-ObjectType gate | [Operating Ontology Metamodel](../architecture/operating-ontology-metamodel.md) |
| Hypothesis, refutation, and effect closure | [Operational Hypothesis Loop](../rules-and-detection/operational-hypothesis-loop.md) |
| Deep security assessment and the report feed | [Assurance Twin](assurance-twin.md) |
| Code-level security findings | [Code Security Findings](code-security-findings.md) |
