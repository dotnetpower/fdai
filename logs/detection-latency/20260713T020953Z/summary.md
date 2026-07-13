# Detection latency measurements

Report root: `logs/detection-latency/20260713T020953Z`

`MAX_WAIT_SECONDS=240.0`, `POLL_FAST=1.0s`, `POLL_METRIC=15.0s`.

| Scenario | Probe class | Inject (s) | Time to first observed (s) | Polls | Observed |
|----------|-------------|-----------:|---------------------------:|------:|----------|
| `aks-pod-kill` | `kube_event` | 0.86 | 0.13 | 1 | True |
| `aks-pod-cpu-spike` | `chaos_mesh_status` | 0.33 | 1.22 | 2 | True |
| `network-rtt-delay` | `chaos_mesh_status` | 0.27 | 1.24 | 2 | True |
| `aks-http-abort` | `chaos_mesh_status` | 0.29 | 1.25 | 2 | True |
| `vm-cpu-stress` | `azure_monitor_metric` | 30.99 | 0.51 | 1 | True |
| `vm-mem-stress` | `run_command_free_m` | 31.51 | 31.45 | 1 | True |
| `mysql-cpu-pressure` | `azure_monitor_metric` | 0.01 | 0.61 | 1 | True |
| `aoai-tpm-throttle` | `http_429_sample` | 0.01 | 3.21 | 1 | True |
| `appgw-backend-failure` | `kube_endpoints` | 0.15 | 0.1 | 1 | True |
| `aks-bad-deploy` | `kube_pod_status` | 0.12 | 2.34 | 3 | True |
