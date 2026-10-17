# Customer lifecycle configuration template

Use this tracked, placeholder-only directory to understand the planned customer configuration
repository. The existing pure validators can check its annotations, layers and secret references
offline. This is not a signed package or a deployable installation.

> **Boundary:** Copy this directory to a private customer repository before adding real values.
> Never commit those values to upstream FDAI. Signing, predecessor verification, sealing and Hub
> package import remain unimplemented; do not upload this raw directory to a Hub.

## Files

| File | Purpose |
|------|---------|
| `release-schema.yaml` | Synthetic Release schema for the offline checks, not a trusted Release |
| `installations/example-installation/installation.yaml` | Example channel, version range, windows and Entity list |
| `installations/example-installation/environment.yaml` | Non-authority values and Key Vault references |
| `installations/example-installation/sealed.yaml` | Plaintext placeholder identifiers that a future packager must seal |
| `installations/example-installation/entities/core.yaml` | Broad and more-specific Release override ranges |

Identifiers, endpoints, vault names and the region are placeholders. `DEV`, version ranges,
replica counts and UTC windows are generic example settings, not a selected deployment.
`sealed.yaml` is a name for the future packager input: its contents are not encrypted today.

## Validate the example

From the FDAI checkout, run the existing locked development environment:

```bash
uv run --no-sync pytest -q --no-cov \
  tests/integration/test_lifecycle_configuration_template.py
```

The checks call the existing deployment CLI validators. They resolve Release `1.5.2` to three
replicas, reject an uncovered `2.0.0`, and reject authority keys or literal secrets. A passing
result proves only those offline contracts. It does not register a key, sign or import a package,
authorize a Plan, validate a real region, or observe a workload.

## Keep values in their owning boundary

- Put ordinary configuration in `environment.yaml` or an Entity override.
- Keep identifiers only in the private `sealed.yaml` input. Do not send it to a Hub before
  a reviewed sealing and import path exists.
- Store credentials in Key Vault and include only a reference, never the credential value.
- Keep approval policy, promotion, standing authority and executor identity out of configuration.

## Next steps

| To learn about | Read |
|----------------|------|
| Key custody and onboarding prerequisites | [Configuration key onboarding](../../docs/runbooks/lifecycle-configuration-key-onboarding.md) |
| Configuration contract and remaining implementation | [Lifecycle Configuration](../../docs/roadmap/deployment/lifecycle-configuration.md) |
