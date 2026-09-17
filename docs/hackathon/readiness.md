---
title: Hackathon Demo Readiness
---

# Hackathon demo readiness

This document defines the FDAI hackathon demo using
[AKS Store Demo](https://github.com/Azure-Samples/aks-store-demo). Customers can browse products,
but cannot submit orders because the order service was scaled to zero replicas. FDAI should detect
the business impact, propose a bounded recovery, and verify the result after human approval.

> **Readiness:** This is the selected scenario and preparation checklist, not a completed live
> demonstration. Repository references below do not prove deployment or end-to-end recovery.
>
> **Scope:** Use an isolated Azure Kubernetes Service (AKS) lab and synthetic orders only. This
> document selects no tenant, subscription, cluster instance, or deployment plan and authorizes no
> deployment, fault injection, model call, or recovery action.

## Scenario at a glance

The story is a missed restart after maintenance: the order service remains scaled to zero even
though the reviewed operating requirement is at least one running instance during service hours.
Use that maintenance explanation only when the retained change records support it.

| Item | Demo target |
|------|-------------|
| Application | Public AKS Store Demo with synthetic products and orders |
| Healthy baseline | Product browsing and order submission succeed; `order-service` has 1 ready replica |
| Injected fault | Change only the `order-service` Deployment replica count from 1 to 0 |
| Customer impact | Products remain visible, but order submission fails |
| Detection | Repeated test-order failures plus a violation of the reviewed minimum replica count |
| Recovery proposal | `ops.scale-out`, restoring the same Deployment to `replica_count: 1` |
| Completion | Independent resource observations and successful test-order acceptance |
| Presentation length | Aim for 3-5 minutes; rehearse and measure before claiming timing |

This demonstrates order acceptance, not payment, order fulfillment, or delivery. A successful
submission does not prove that a downstream worker completed the order.

## Why this fault

Kubernetes reconciles workloads to their configured replica count. Zero replicas can therefore be
a valid Kubernetes state while violating the business operating requirement. Pod health alone is
not enough to detect this scenario.

- **Pod deletion:** Kubernetes normally replaces a deleted controller-owned Pod itself. That is
	not evidence of FDAI recovery.
- **Invalid image:** A failed rolling update can leave old healthy Pods serving traffic. An image
	pull failure does not necessarily produce a customer-visible outage.
- **Load spike:** Resource pressure and autoscaling make timing less predictable. Keep this as a
	later scenario, after the single-service recovery works reliably.

## Preparation boundaries

Use the upstream quickstart's `store-front`, `product-service`, `order-service`, and RabbitMQ as the
minimal application candidate. Pin the reviewed manifest revision and image digests for rehearsal.
The optional AI service and full order-fulfillment stack are outside this first demonstration.

- **Isolation:** Follow the dedicated scenario-lab cluster boundary and use a demo-only namespace.
	Do not inject faults into FDAI services, shared workloads, nodes, or system namespaces.
- **Exposure:** Expose only the storefront over HTTPS. Keep APIs, administration, and RabbitMQ
	private; do not reuse published sample credentials for an exposed service.
- **Operating intent:** Record the service-to-Deployment mapping, minimum replica count of 1,
	applicable service hours, and maintenance-end evidence before the run. Active authorized
	maintenance is not an invitation to scale the service up.
- **Single writer:** Review the Horizontal Pod Autoscaler (HPA) and GitOps reconciliation, which
	synchronizes desired configuration from Git. They should not compete with the approved action
	over the same replica count. Do not disable safety controls to make the demo work.
- **Synthetic traffic:** Test orders change application state. Use a separately authorized,
	bounded synthetic worker with a fixed cadence, request limit, timeout, and cleanup plan. It has
	no cloud management identity. Read-only browser capture does not authorize order submission.
- **Detection contract:** Fix the observation window, failure threshold, recovery threshold, and
	evidence freshness before rehearsal. Record failed order steps, not only page availability or
	HTTP status. Missing observations remain unknown rather than successful.
- **Time limits:** Set total and per-stage deadlines before the run. Stop on a deadline, missing
	authority, conflicting state, or unexpected target change; retain evidence and hand off for review.

## 1. Show the healthy store

Browse a product, add it to the cart, and submit a synthetic order. Retain the bounded baseline
observations: successful order acceptance, one ready order-service replica, a ready service
endpoint, and the exact target identity. Do not retain customer or order payloads in the repository.

## 2. Inject one configuration fault

An authorized operator changes the demo order Deployment from 1 replica to 0. Record the actor,
time, exact target, previous value, and new value as change evidence. The fault injection is
separate from FDAI's diagnosis and does not grant recovery authority.

Keep the storefront and product service running. Show that browsing still works while a test
order fails. Do not damage RabbitMQ data or delete the Deployment.

## 3. Let FDAI discover the impact

The synthetic worker continues without an operator question triggering diagnosis. FDAI should
combine failed order observations with the current Deployment and service endpoint state, then
compare them with the reviewed operating requirement.

| Dashboard field | Expected evidence-backed content |
|-----------------|----------------------------------|
| Title | Products are available, but orders cannot be submitted |
| Affected service | Order acceptance |
| Resource state | `order-service`: configured replicas 0, ready replicas 0 |
| Operating requirement | At least 1 running instance during the applicable service window |
| Impact | Test-order submission fails; product browsing still succeeds |
| Recent change | Exact replica-count change, if collected |
| Freshness | Actual observation times and source references |
| Next step | Open the matching incident or ask why |

Use deterministic rules for this repeatable condition. A missing maintenance record should remain
a visible evidence gap, not an invented explanation. Keep Dashboard, Incident, approval, execution,
and audit records on the actual run's correlation identifier.

## 4. Ask why orders fail

The operator asks:

> Products are visible. Why can't customers place an order?

When the required observations exist, the answer should explain:

> Product browsing is succeeding, but test orders are failing. The order service is configured
> for zero replicas and has no ready endpoint. Its reviewed operating requirement is at least one
> running instance. The recorded change reduced the replica count from one to zero. Restoring one
> replica is the proposed recovery, subject to current approval and safety checks.

Show the target, timestamps, dependency path, and evidence sources. Describe maintenance as a
related recorded change only when supported; temporal proximity alone does not prove root cause.

## 5. Review the bounded recovery

The approval should identify `ops.scale-out`, the exact Deployment identity and observed version,
the current count of 0, and the requested count of 1. A different human from the requester approves;
the executor identity remains separate. New capabilities start in observation mode and require
the authoritative promotion process before execution is enabled.

Confirm all seven existing safeguards before a live action:

| Safeguard | Demo requirement |
|-----------|------------------|
| Stop condition | Stop on stale evidence, changed target or configuration, lost authority, or deadline |
| Tested rollback | Retain and test the pre-action replica-count restoration under current recovery authority |
| Impact scope | Change one exact Deployment in the demo namespace |
| Successful dry run | Verify the proposed scale operation with the server before execution |
| Logical-target lock | Exclude concurrent changes to the same target |
| Stable idempotency key | Duplicate delivery does not cause repeated changes |
| Two-phase audit | Record intent before the effect and retain the terminal outcome |

Restoring the pre-action value of 0 undoes the recovery attempt but leaves order acceptance
unavailable. Do not label that rollback as business recovery. Keep the incident open and use the
reviewed recovery or manual-restoration procedure with its own current authority; a reset for the
next rehearsal is a separate operation.

## 6. Verify the customer-visible result

Keep these stages distinct in the activity view:

1. FDAI detected the order-acceptance failure and proposed a one-Deployment recovery.
2. A different human approved the current proposal.
3. The Kubernetes API accepted the scale request.
4. An independent observer confirmed the intended replica count, one ready replica, and a ready
	 endpoint for the same target after the action.
5. Independent synthetic observations confirmed order acceptance and continued product browsing
	 across the predefined recovery window.
6. FDAI marked the expected effect verified and retained the linked audit evidence.

An API success, a running Pod, or the injector's own success message is not business recovery.
Check the expected order-confirmation result, not only HTTP 200. Failed, stale, or incomplete
verification keeps the incident unresolved.

## 7. Show a held-for-review case

Use a separate rehearsal or clearly labeled Sample case with stale Kubernetes observations,
conflicting operating requirements, or an unavailable test-order worker. FDAI should explain what
evidence is missing and hold the action for review without changing the target.

Never combine this case with a completed run or present Sample data as live observations.

## Current readiness and remaining work

The repository review on 2026-09-17 establishes the following starting points. It does not certify
the current environment or a completed live run.

| Area | Available basis | Required before recording |
|------|-----------------|---------------------------|
| Application | Upstream AKS Store Demo quickstart | Approved isolated deployment, pinned inputs, and a successful baseline order |
| Commerce evidence | Existing commerce extension and broader business-scenario design | Confirm the quickstart's RabbitMQ and order-acceptance mapping; the broader design expects Azure Service Bus and fulfillment evidence |
| Automatic detection | Deterministic assessment design | Validate the zero-replica operating-intent violation and failed-order path without a manual question |
| Kubernetes scale | Runtime inventory registers a conditional Core binding with focused-test evidence | Verify the selected runtime binding, authorization, promotion, safeguards, and independent observations in the lab |
| Console journey | Existing incident, approval, and activity surfaces | Confirm real AKS records, one run identity, evidence links, and localized explanations across the flow |
| Business recovery | Resource and business-effect verification design | Confirm the bounded worker validates order acceptance independently of the executor |
| Existing VM Sample | Earlier VM-start walkthrough on `/live?data=sample` | Keep it explicitly labeled as a separate fallback; it is not AKS evidence |

The quickstart is a narrower candidate than the existing fulfillment design. Resolve that scope
and its required evidence in the owning design before runtime changes. Do not mark missing queue
or completion evidence as healthy to fit this demo, or imply an unverified detector already works.

## Work order

1. Confirm the order-acceptance scope and reconcile it with the owning commerce design.
2. Review the deployment target, identity boundaries, exact plan, and synthetic-traffic authority
	 through the existing deployment workflow. This document is not deployment approval.
3. Establish the healthy baseline and reviewed operating requirement.
4. Connect current Kubernetes, synthetic-order, and change observations to deterministic detection.
5. Verify the proposal and all safeguards in observation mode before authorizing live recovery.
6. Connect the same incident to Dashboard, conversation, approval, activity, and audit views.
7. Rehearse the complete live route and separate held-for-review case; record actual timings and gaps.
8. Verify English, Korean, keyboard use, and 1440x900, 993x641, and 390x844 layouts before recording.

## Recording checklist

- [ ] The store browses products and accepts a baseline synthetic order.
- [ ] The authorized fault changes only the demo order-service replica count from 1 to 0.
- [ ] Products remain visible while test-order submission fails.
- [ ] FDAI detects the issue before the operator asks a question.
- [ ] The explanation distinguishes Kubernetes desired state from the reviewed operating requirement.
- [ ] All claimed changes and causes have matching current evidence; missing records remain explicit.
- [ ] A different human approves the exact recovery, with all seven safeguards satisfied.
- [ ] API acceptance and independent resource and order-acceptance verification are separate steps.
- [ ] An uncertain case holds for review, and a failed recovery has a tested recovery procedure.
- [ ] Live observations, synthetic traffic, and Sample fallback data are clearly distinguished.
- [ ] No private identity, resource ID, credential, payload, or infrastructure endpoint is exposed.
- [ ] No payment, fulfillment, revenue, or formal performance improvement is inferred from this run.

## Related docs

| To learn about | Read |
|----------------|------|
| Public application | [AKS Store Demo](https://github.com/Azure-Samples/aks-store-demo) |
| Owning business scenario | [AKS Commerce Business Scenario](../roadmap/operations/aks-commerce-business-scenario.md) |
| Registered action support | [config/action-type-runtime-support.json](../../config/action-type-runtime-support.json) |
| Existing commerce package | [extensions/aks-commerce/README.md](../../extensions/aks-commerce/README.md) |
| Evidence presentation | [Console Evidence and Resilience](../roadmap/interfaces/console-evidence-and-resilience.md) |
| Operational authority | [Console Operations](../roadmap/interfaces/console-operations.md) |
| UI and UX review | [UI/UX quality rubric](../reference/ui-ux-quality-rubric.md) |
