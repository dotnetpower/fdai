# Lifecycle Hub apply demo

This demo shows a Lifecycle Hub keeping one workload on its Release channel. The lifecycle agent
upgrades the workload from 1.0.0 to 1.1.0 by the Hub's Plans. It then rolls back a deliberately
broken 1.2.0 when the health check fails, and the Hub stops planning 1.2.0 for that Entity.

Everything runs on your machine: the Hub command line, the Hub API on loopback, and the agent. Only
the agent touches the cluster, and only in the one namespace you name. The repository holds no
cluster name, subscription, tenant, or key. You pass the kubeconfig context and namespace as
arguments or environment variables, and the demo generates its keys in a work directory.

## Scenario

| Step | Channel | Hub | Agent | Result |
|------|---------|-----|-------|--------|
| Enroll | (empty) | Enrolls `demo`, approves it, records ownership, and manages `core` | | `core` reports 0.0.0 |
| 1.0.0 | 1.0.0 | Issues a Plan to 1.0.0 | Applies `nginx-unprivileged` 1.27.5 and reports `applied` | `recompute` is `up-to-date` |
| 1.1.0 | 1.0.0, 1.1.0 | Issues a Plan to 1.1.0 | Applies `nginx-unprivileged` 1.28.0 and reports `applied` | `recompute` is `up-to-date` |
| 1.2.0 | all three | Issues a Plan to 1.2.0 | The image digest doesn't exist, the health check fails, the agent restores 1.1.0 and reports `rolled-back` | The Hub holds `entity:core` for 24 hours, serves no Plan, and `recompute` is `waiting` with `suppression_window_active` |

The installation has two Entities. `core` is the managed workload, and it reports only the image
it runs. `artifact-mirror` is unmanaged, and it reports the three demo images as available, because
the Hub plans a Release only when every image it needs is available inside the installation.

Releases 1.0.0 and 1.1.0 pin the public `docker.io/nginxinc/nginx-unprivileged` image indexes for
`1.27.5-alpine` and `1.28.0-alpine` by digest. Release 1.2.0 names a digest that no registry holds.

## Prerequisites

- The repository's development environment: `uv sync --extra dev --frozen` from the repository
  root.
- For apply mode, a kubeconfig context for the cluster and an existing, dedicated namespace. The
  agent changes only Deployments and Services in that namespace, so it doesn't create the namespace.
  The demo refuses `default` and the `kube-*` namespaces.

## Run it

`demo.sh` sets `PYTHONPATH` for the Hub, the agent, and the shared checks, and runs
`python -m lifecycle.demo` from the repository root. Every run starts from a fresh work directory,
`/tmp/fdai-lifecycle-demo` unless you pass `--work`. The demo removes only a directory it created.

### Dry run, no cluster

The agent admits each Plan and computes the change without applying it. The scenario stops after
1.1.0, because the rollback needs a real apply:

```bash
lifecycle/demo/demo.sh run
```

### Apply on a local kind cluster

Create the cluster and the namespace once, then run the scenario:

```bash
kind create cluster --name fdai-lifecycle-demo
kubectl --context kind-fdai-lifecycle-demo create namespace fdai-lifecycle-demo

lifecycle/demo/demo.sh run --apply \
  --kube-context kind-fdai-lifecycle-demo --namespace fdai-lifecycle-demo \
  --health-timeout-seconds 60
```

Add `--pause` to wait for Enter before each step when you present it. Watch the workload in another
terminal with `kubectl --context kind-fdai-lifecycle-demo -n fdai-lifecycle-demo get deploy,pods -w`.

### Apply on AKS

Only the context and the namespace change. Get the credentials for the cluster you choose, create
the namespace, and pass both through environment variables so they stay out of the command history
you share:

```bash
export FDAI_DEMO_KUBE_CONTEXT=<your-aks-context>
export FDAI_DEMO_NAMESPACE=fdai-lifecycle-demo
kubectl --context "$FDAI_DEMO_KUBE_CONTEXT" create namespace "$FDAI_DEMO_NAMESPACE"

lifecycle/demo/demo.sh run --apply --health-timeout-seconds 120
```

The cluster pulls the two public images from Docker Hub. On a cluster without outbound access to
Docker Hub, the 1.0.0 step fails its health check too.

### Step by step

`run` drives the whole scenario. To drive it yourself, prepare the files and add one Release at a
time, then use the Hub and agent commands that `run` prints:

```bash
lifecycle/demo/demo.sh prepare
lifecycle/demo/demo.sh publish 1.0.0
```

## What each step checks

Each step reads the result back from the Hub with `fdai-lifecycle-hub show`, not from the agent's
output: the reports for the step's Plan, the next `recompute` outcome, and after 1.2.0 the active
`failure` suppression that names the failed Plan. A mismatch stops the run with exit code `1`.
The Hub API log is in `hub.log` in the work directory.

`demo.sh hub` runs any `fdai-lifecycle-hub` command on the demo's database. For example, show the
Hub's view after the run, or lift the hold so that the next `recompute` plans 1.2.0 again:

```bash
lifecycle/demo/demo.sh hub show demo
lifecycle/demo/demo.sh hub unsuppress demo --scope entity:core
```

## Files

| Path | Purpose |
|------|---------|
| `catalog.py` | Demo Releases, the signed agent inputs, the enrollment request, and channel publishing |
| `scenario.py` | The scenario: Hub setup, then publish, recompute, one agent poll, and checks per Release |
| `__main__.py` | `prepare`, `publish`, `hub`, and `run` commands |
| `demo.sh` | Runs the demo from the repository's development environment |
| `tests/` | The generated files plan as expected, and the dry-run scenario runs end to end |

## Testing

```bash
uv run --no-sync pytest -c pyproject.toml lifecycle/demo -q
```

The tests run the dry-run scenario with real processes and stand in for the applying agent against
the Hub, so they need no cluster.

## Related docs

| To learn about | Read |
|----------------|------|
| Hub commands, API, and failure holds | [Lifecycle Hub](../hub/README.md) |
| The agent's poll order and inputs | [Lifecycle agent](../agent/README.md) |
| The lifecycle design | [Hub-Managed Lifecycle](../../docs/roadmap/deployment/hub-managed-lifecycle.md) |
