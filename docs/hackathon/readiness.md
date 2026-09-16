---
title: Hackathon Demo Readiness
---

# Hackathon demo readiness

This document defines one simple story for the FDAI hackathon demo. The story starts when an
operator notices that one of three checkout service virtual machines did not restart after
maintenance.

> **Scope:** All values and resources in this document are synthetic Sample data. They do not
> represent a customer environment or a live Azure action.

## Demo story in one sentence

FDAI finds that only two of three checkout servers are running, explains that the third server
remained deallocated after maintenance, asks a different human to approve one VM start, and closes
the case only after an independent observer confirms that the VM is running.

## 1. Discover the problem on the Dashboard

The demo should start on the Dashboard. The operator should understand the problem without opening
another page.

### What the operator sees

| Field | Sample value |
|-------|--------------|
| Title | One checkout server is not running |
| Service state | 2 of 3 servers running |
| Affected service | Online store checkout |
| Resource state | One VM is deallocated |
| Recent change | Maintenance completed, but no later VM start was recorded |
| Impact | Processing capacity is reduced; an outage is not confirmed |
| Observed | One minute ago |
| Next step | Open the incident or ask why |

The card should link to `sample-correlation-001`.

### What is missing today

The focused VM journey exists on the Sample Live page, but this problem card is not shown on the
Dashboard. A reviewer therefore sees the solution before understanding the problem. The Dashboard
card is the first implementation task.

## 2. Ask why one server is not running

The operator opens the incident or the conversation panel and asks:

> Why is one checkout server not running?

The answer should be short:

> Three checkout VMs are expected, but only two are running. `sample-checkout-vm-01` is
> deallocated. The latest related record is a completed maintenance change, and no later start
> record was found. This change may explain the reduced capacity, but the records alone do not
> prove causation.

The answer should show:

- the affected VM
- the current VM state
- when the state was observed
- the related maintenance record
- the evidence sources
- the difference between a related change and a proven cause

## 3. Show that FDAI can wait

Use a separate Sample case when the VM state is old, two sources disagree, or the VM is still
starting. FDAI should say what must be checked again and keep the case waiting for review.

Do not show a successful diagnosis or an executable action for this case.

## 4. Review the VM start approval

Open `/approvals?data=sample`.

The approval card should show:

- action: `ops.start-vm`
- target: one Sample VM
- reason: restore the expected three-server capacity
- impact scope: one VM
- stop condition
- rollback action: `ops.deallocate-vm`
- approval state: waiting for a different human

This pending example uses `sample-correlation-002`. It is separate from the completed story so the
two screens do not contradict each other.

## 5. Follow the completed journey

Open `/live?data=sample`.

The focused panel should show these steps in order:

1. The operator reported reduced checkout capacity.
2. FDAI found one deallocated VM and a related maintenance record.
3. A different human approved one VM start.
4. Azure accepted the start request.
5. A separate observer read the VM as running.
6. FDAI marked the expected effect as verified.

Azure request acceptance is not the final success condition. The case closes only after the
independent running-state observation.

## 6. Open the complete correlation

Select **Inspect complete correlation** and confirm:

| Check | Expected value |
|-------|----------------|
| Decision | Human approval |
| Authority | `A3-H` |
| Execution | Completed |
| Azure request | Accepted |
| Independent observation | VM running |
| Final result | Effect independently verified |
| Recovery | Ready, not required |
| Correlation | `sample-correlation-001` |

The Sample warning must remain visible. The detail is a walkthrough, not evidence of a live Azure
effect.

## Current screen status

| Screen | Status | Next work |
|--------|--------|-----------|
| Dashboard problem card | Missing | Add the 2-of-3 checkout server problem and link it to the Incident. |
| Incident detail | Partly ready | Confirm the same target, maintenance record, and completed correlation. |
| Conversation answer | Missing | Add the exact question and evidence-backed answer. |
| Waiting-for-review case | Missing | Add one stale, conflicting, or starting-state example. |
| Pending approval | Ready | Keep it on `sample-correlation-002`. |
| Sample Live journey | Ready | Recheck it after the Dashboard data is connected. |
| Complete correlation detail | Ready | Recheck English, Korean, and small screens. |
| Trace and Audit | Not confirmed | Include them only if matching Sample records are available. |

## Work order

Complete and review one item at a time:

1. Add the missing Dashboard problem card.
2. Connect the card to the matching Incident.
3. Add the operator question and short evidence-backed answer.
4. Add one clear waiting-for-review example.
5. Confirm the pending Approval and completed Live journey do not share the same correlation.
6. Confirm Trace and Audit data, or remove those screens from the recording plan.
7. Verify English, Korean, keyboard use, and 1440x900, 993x641, and 390x844 layouts.
8. Rehearse the complete route before recording.

## Recording checklist

- [ ] The problem is visible on the Dashboard before the solution.
- [ ] A reviewer can understand that one of three checkout servers is not running.
- [ ] The answer names the VM state and related maintenance record.
- [ ] One uncertain case visibly waits for more evidence.
- [ ] The approval changes only one VM and shows a rollback.
- [ ] Azure acceptance and independent effect verification are shown as different steps.
- [ ] The Sample boundary remains visible.
- [ ] No tenant, subscription, full resource ID, email, token, or endpoint appears.
- [ ] No live Azure effect or formal performance improvement is claimed.

## Related docs

| To learn about | Read |
|----------------|------|
| Console Sample behavior | [FDAI Console Conversations](../roadmap/interfaces/operator-console.md) |
| Evidence presentation | [Console Evidence and Resilience](../roadmap/interfaces/console-evidence-and-resilience.md) |
| Operational authority | [Console Operations](../roadmap/interfaces/console-operations.md) |
| UI and UX review | [UI/UX quality rubric](../reference/ui-ux-quality-rubric.md) |
