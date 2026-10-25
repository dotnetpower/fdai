# Lifecycle Manager

Lifecycle Manager prepares one private, installation-bound input set for a Hub-managed FDAI
deployment. It generates customer and installation keys locally, signs enrollment and
configuration bytes, and binds an application Release to an independently reviewed runtime bundle.
It never contacts Azure, either Hub, a registry, or a cluster.

## Prepare

Keep the runtime bundle, component-image map, Hub public key, and Release public key in
current-user mode-`0700` directories with mode-`0600` files. Select a clean committed checkout and
a new private destination:

```bash
fdai-lifecycle-manager prepare \
  --source <clean-checkout> \
  --destination <new-private-directory> \
  --runtime-bundle <private-runtime-bundle.json> \
  --component-images <private-component-images.json> \
  --hub-public-key <hub-public.pem> \
  --release-public-key <release-public.pem> \
  --installation-id <installation-id> \
  --entity-id <entity-id> \
  --product fdai \
  --release-id <semantic-version> \
  --channel DEV \
  --region <azure-region> \
  --actor <approved-operator>
```

The destination contains the immutable Release publication request, signed enrollment,
customer-signed configuration artifact and Agent cache, application-binding request, Entity
settings, explicit empty reported state, private runtime policy, native creation approval, and
installation/configuration key pairs. The command prints only digests and paths. A failure removes
the partial destination.

The preparation receipt grants no publication, enrollment, ownership, Plan, Azure, Kubernetes, or
licensing authority. Use the Release and Lifecycle Hub trusted-operation stages and the independent
Lifecycle Agent root to apply those decisions. The installation private key stays local and never
enters Terraform, a Hub, a command argument, or a log.

If the short enrollment proof window expires while infrastructure and catalog stages run, refresh
only that proof into a new file:

```bash
fdai-lifecycle-manager refresh-enrollment \
  --prepared <private-directory> \
  --destination <private-directory>/signed-enrollment-refreshed.json
```

The command verifies the retained proof against the installation public/private key pair, preserves
the installation payload and identity, updates only `requested_at`, and writes a new mode-`0600`
artifact without replacing the original.

## Continue the exact workflow

After the Release operations Job returns its private receipt, derive the exact catalog import and
recompute requests:

```bash
fdai-lifecycle-manager catalog-requests \
  --prepared <private-directory> \
  --publication-receipt <private-release-receipt.json>
```

After native bootstrap produces its signed proof and the application binding has been accepted,
derive the separate native ownership request:

```bash
fdai-lifecycle-manager native-acceptance \
  --prepared <private-directory> --proof <private-native-proof.json>
```

`agent-tfvars` writes the independent Lifecycle Agent root's private input file from exact Azure,
AKS, Hub and image coordinates. It never copies the installation private key. Omit
`--enable-agent` for the preparation plan; add it only after the Lifecycle Hub has accepted native
ownership, recorded empty state, managed the Entity, imported the catalog and issued the Plan.
For that enabled plan, pass the local bootstrap state with
`--native-state <private-state-dir>/lifecycle-native-scope.json`.

## Testing

```bash
uv run --project lifecycle/manager pytest -q lifecycle/manager/tests
uv run --project lifecycle/manager ruff check lifecycle/manager
```
