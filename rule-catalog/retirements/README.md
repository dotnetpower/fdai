# Rule retirements

Reviewed records that move a rule out of the enforce set. A retirement is a
catalog-as-code diff, not an override: an override narrows autonomy for a
bounded scope, while a retirement changes the rule's standing everywhere.

One YAML document per rule, rendered by
[`governance_writers.py`](../../services/core-control-plane/src/fdai/delivery/gitops_pr/governance_writers.py)
for the `governance.retire-rule` ActionType, which declares
`execution_path: pr_native`.

| Field | Meaning |
|-------|---------|
| `rule_id` | The rule leaving the enforce set. |
| `mode` | `shadow_only` keeps the rule evaluating; `retired` removes it entirely. |
| `justification` | 20 to 500 characters, audit-safe. |
| `requested_by` / `approved_by` | Distinct Entra object ids; self-approval is rejected. |
| `decided_at` | RFC 3339 UTC. |

A rendered document carries no authority. It takes effect only when an approved,
distinct-approver pull request merges it. Upstream ships this store empty.
