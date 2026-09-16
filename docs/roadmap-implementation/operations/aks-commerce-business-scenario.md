# AKS Commerce Business Scenario Implementation

This ledger records delivery state for the bounded AKS commerce scenario defined by the
[owner design](../../roadmap/operations/aks-commerce-business-scenario.md).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Business topology and package assets | implemented | `extensions/aks-commerce/resources`; shared contract and package tests | The package is inert, immutable, customer-agnostic, and adds no agent or authority. |
| Messaging, browser, Kubernetes, and SLO observations | implemented | Azure metric templates, browser policy, synthetic journey, observation source, and focused tests | Live source identity and availability remain deployment-bound. |
| Deterministic business-impact assessment | implemented | `fdai_aks_commerce.assessment`; complete, backlog, DLQ, regression, held, and recovered regressions | The reducer never converts missing evidence into health. |
| Operator and Console projection | implemented | Operator family tests; Console decoder tests, typecheck, build, and two-route browser scenarios | Authenticated live data remains a separate deployment claim. |
| Governed Kubernetes actions and verification | implemented | Kubernetes adapter and business-effect tests; ActionType catalog regressions | Enforce mode remains blocked without the ordinary promotion, approval, and live effect evidence. |
| Public HTTPS scenario-lab profile | implemented | Terraform validation, scenario-lab tests, and `prepare-commerce.sh` shell validation | No tenant, DNS, certificate, or Terraform plan is selected. |
| Live Azure scenario validation | not-started | #1207 | Requires a separately approved exact plan and live evidence campaign. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-17 | implemented | Added the immutable scenario package, workload SLOs, Azure messaging mappings, read-only browser policy, synthetic order journey, deterministic business-impact reducer, durable projection path, Operator and Console workspace, exact-target Kubernetes adapter, independent business-effect closure, and optional public-HTTPS scenario-lab profile. | `current change`; focused Python, ActionType, Operator, Console, browser, Terraform, shell, type, lint, and documentation checks listed in the scope table. | Retain the separately approved live Azure receipt before raising any area to validated or promoting an action. |
| 2026-09-17 | in-progress | Defined the generic AKS commerce business topology, evidence, browser, authority, action, and public-exposure boundaries without changing the agent pantheon. | `current change`; owner design, implementation ledger, and #1207. | Implement each scope row, run focused checks, and retain separately approved live evidence. |

### Remaining work

- [x] Record passing package and contract tests for the business topology and immutable assets.
- [x] Record passing adapter and reducer tests for complete, unavailable, stale, conflicting, and recovered observations.
- [x] Record passing Operator, Console, typecheck, build, and declared viewport evidence.
- [x] Record passing Kubernetes action shadow, rollback, idempotency, and independent-effect tests; approval remains the shared Var boundary.
- [x] Record passing Terraform format, validation, and scenario-profile tests without applying Azure changes.
- [ ] Retain one separately approved live Azure receipt for public HTTPS access, degraded business impact, governed recovery, and independently verified recovery.
