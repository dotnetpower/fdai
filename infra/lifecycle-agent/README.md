# Lifecycle Agent deployment

This root prepares one installation-bound Lifecycle Agent for an existing AKS cluster. It creates
the Agent's dedicated Managed Identity and workload federation, assigns only `Agent.Access` on the
selected Lifecycle Hub API, and installs a single-writer Agent with durable local state.

## Boundary

- The Agent receives no Azure managed-resource write role.
- Kubernetes permissions cover only Deployments, internal Services, Jobs, and CronJobs in the
  exact target namespace. The Role also grants namespace-scoped `list` on Deployments and
  CronJobs, which `fdai-lifecycle-agent enroll` uses to derive Entities read-only. No Secret,
  write verb or cluster-wide permission is added. Applying this to an existing installation is an
  in-place Role update that needs the usual reviewed saved plan.
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
- The Job Pod template carries a digest of every staged input. A policy, approval, native state,
  current state, public identity, or configuration artifact change replaces and reruns the Job.
  The first 12 digest characters are also part of the bounded Job name so provider patch behavior
  cannot turn a required rerun into a no-op.
- Private inputs are rewritten from the retained Secret through mode-`0600` temporary files and
  atomic replacement on every initializer run. Existing or empty files are never accepted by
  presence alone.
- If an interrupted kubelet `subPath` setup left an empty directory at a file target, the
  initializer removes only that empty directory. A non-empty directory still fails closed.
- After local native bootstrap, pass its private `lifecycle-native-scope.json` through
  `agent-tfvars --native-state`. The initializer stages it atomically at the Agent state path; the
  installation private key still never enters Terraform.
- All Agent journal, current-state, native-state, and artifact-cache files live beneath the
  UID-owned mode-`0700` `/state/agent` directory. The group-managed PVC mount root is never passed
  as the Agent state directory.
- The main container mounts only that PVC `agent` subdirectory at the image's UID-owned
  mode-`0700` `/agent-state` path. Strict readers therefore never traverse the group-writable PVC
  mount root.
- A bounded `64Mi` `emptyDir` provides writable `/tmp` for Kubernetes dynamic discovery while the
  image root filesystem remains read-only.
- The installation identity private key is never a Terraform input. Native bootstrap runs
  separately and supplies only the installation public key to the running Agent.
- `enable_agent=false` prepares identity, RBAC, state, and inputs without starting a poller.
  Switch it to `true` only after enrollment, application binding, native ownership acceptance,
  reported empty state, Entity management, signed input publication, and Plan issuance.
- The PVC uses a zone-redundant (`StandardSSD_ZRS` by default) StorageClass that this root creates
  with `WaitForFirstConsumer`, so a Pod rescheduled to another zone can attach the volume. A regional
  `Standard_LRS` disk cannot attach to a zonal node. Set `storage_class_name` to use an existing
  class instead. A StorageClass is immutable on a bound PVC: to move an installation that already
  has the previous `managed-csi` volume, scale the Agent to zero, delete its empty PVC outside
  Terraform so the next reviewed plan creates the replacement, then apply. Never delete a PVC that
  holds enrolled state.
- Terraform never waits for binding during the disabled stage. Verify `Bound` independently after the Agent Pod is scheduled.

## Apply

Use an explicit private local backend and a kubeconfig context for the exact cluster. Before
applying, verify the Hub API client and `Agent.Access` role IDs through an independently approved
Entra readback. Review the complete saved plan. A delete, replacement, other role, other namespace,
mutable image, or changed OIDC issuer stops the deployment.

After apply, verify the federated credential, app-role assignment, ServiceAccount annotation,
namespace Role, PVC binding, one ready Agent replica, and the Hub's attributed Plan reports.
Agent acceptance is complete only after independent workload readback and an up-to-date Hub
recompute.
