# Detection latency measurements

Report root: `logs/detection-latency/20260713T020931Z`

`MAX_WAIT_SECONDS=240.0`, `POLL_FAST=1.0s`, `POLL_METRIC=15.0s`.

| Scenario | Probe class | Inject (s) | Time to first observed (s) | Polls | Observed |
|----------|-------------|-----------:|---------------------------:|------:|----------|
| `aks-pod-kill` | `kube_event` | 1.64 | 0.16 | 1 | True |
