# `src/aiopspilot/delivery`

Delivery adapters. `gitops_pr` renders remediation PRs; `chatops` renders channel
messages (Teams / Slack / email / webhook / pager / SMS). Executor emits an
abstract action; the adapter renders it.
