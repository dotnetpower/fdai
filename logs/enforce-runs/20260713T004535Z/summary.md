# Enforce run summary

Report root: logs/enforce-runs/20260713T004535Z (vm-mem-stress replaced by retry 20260713T013725Z after tuning stressor size for the 894 MB VM)

| Scenario | Outcome | Detected | Reverted | Elapsed (s) |
|----------|---------|----------|----------|-------------|
| `aks-bad-deploy` | validated | True | True | 180.51 |
| `aks-http-abort` | validated | True | True | 180.83 |
| `aks-pod-cpu-spike` | validated | True | True | 180.66 |
| `aks-pod-kill` | validated | True | True | 181.62 |
| `aoai-tpm-throttle` | validated | True | True | 209.17 |
| `appgw-backend-failure` | validated | True | True | 180.41 |
| `mysql-cpu-pressure` | validated | True | True | 190.67 |
| `network-rtt-delay` | validated | True | True | 180.64 |
| `vm-cpu-stress` | validated | True | True | 244.75 |
| `vm-mem-stress` | validated | True | True | 275.06 |
