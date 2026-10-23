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

## Testing

```bash
uv run --project lifecycle/manager pytest -q lifecycle/manager/tests
uv run --project lifecycle/manager ruff check lifecycle/manager
```
