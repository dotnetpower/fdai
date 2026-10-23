# Lifecycle Agent deployment

This root prepares one installation-bound Lifecycle Agent for an existing AKS cluster. It creates
the Agent's dedicated Managed Identity and workload federation, assigns only `Agent.Access` on the
selected Lifecycle Hub API, and installs a single-writer Agent with durable local state.

## Boundary

- The Agent receives no Azure managed-resource write role.
- Kubernetes permissions cover only Deployments, internal Services, Jobs, and CronJobs in the
  exact target namespace.
- Public signing keys and initial reported state use a ConfigMap. Local policy, runtime topology,
  and optional native approval use a private Kubernetes Secret in the private Terraform state.
- A pre-staged configuration signature stays canonical Base64 in Terraform and is written through
  the provider's binary Secret field, so arbitrary Ed25519 bytes never pass through UTF-8 decoding.
- The state initializer mounts both public and private inputs read-only before copying a verified
  pre-staged configuration into the persistent cache.
- The initializer also copies the local policy and optional native identity inputs to the PVC with
  mode `0600` beneath an exact current-UID mode-`0700` `/state/private` boundary. The main Agent
  does not mount the Kubernetes Secret and reads only those owner-only state files.
- Pod volume ownership uses `fsGroupChangePolicy=OnRootMismatch`. Once the PVC root has the Agent
  group, kubelet does not recursively broaden the initializer's private file modes.
- The main Agent bind-mounts only the required PVC files by `subPath` beneath the image's
  UID-owned mode-`0700` `/config/private` directory. It never treats the group-managed PVC root as
  a private-input parent.
- Initializer variables keep the private input directory and artifact-cache directory distinct;
  native approval and installation identity files always remain beneath `/state/private`.
- Activation runs that initializer as a bounded one-shot Job and waits for completion before
  creating or updating the Agent Deployment. This guarantees every `subPath` source exists before
  kubelet prepares the Agent Pod.
- The installation identity private key is never a Terraform input. Native bootstrap runs
  separately and supplies only the installation public key to the running Agent.
- `enable_agent=false` prepares identity, RBAC, state, and inputs without starting a poller.
  Switch it to `true` only after enrollment, application binding, native ownership acceptance,
  reported empty state, Entity management, signed input publication, and Plan issuance.
- The PVC uses `WaitForFirstConsumer` storage and Terraform never waits for binding during the
  disabled stage. Verify `Bound` independently after the Agent Pod is scheduled.

## Apply

Use an explicit private local backend and a kubeconfig context for the exact cluster. Before
applying, verify the Hub API client and `Agent.Access` role IDs through an independently approved
Entra readback. Review the complete saved plan. A delete, replacement, other role, other namespace,
mutable image, or changed OIDC issuer stops the deployment.

After apply, verify the federated credential, app-role assignment, ServiceAccount annotation,
namespace Role, PVC binding, one ready Agent replica, and the Hub's attributed Plan reports.
Agent acceptance is complete only after independent workload readback and an up-to-date Hub
recompute.
