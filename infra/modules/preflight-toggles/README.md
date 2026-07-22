# Preflight capability-mode toggles

Data-only Terraform modules that encode the five **capability-mode
toggles** from `docs/roadmap/deployment/deployment-preflight.md`
(Blocker-to-Terraform Toggle Mapping). Each toggle turns a policy-
deny-shaped deploy blocker into a supported alternate rendering, so
the plan never emits the denied operation in the first place.

| Toggle | Values | Effect |
|--------|--------|--------|
| `disk_provisioning` | `inline` \| `attach_existing` | create the VM disk inline vs attach a pre-provisioned disk |
| `nsg_provisioning` | `create` \| `byo` | create an NSG vs reference an existing one |
| `registry_source` | `docker_io` \| `acr_mirror` | pull base images from an internal registry mirror instead of `docker.io` |
| `python_index_url` | (string) | point package installs at an internal PyPI mirror / artifact feed |
| `dependency_ordering` | `strict` \| `best_effort` | split prerequisite resources into an ordered apply stage |

## Design

Each sub-module is **data-only** (no `resource` blocks, no provider
dependency) - it accepts the mode flag plus auxiliary variables and
emits a normalized configuration map. Downstream modules read those
outputs and pick the concrete resource shape.

Keeping the toggles data-only means:

- `terraform validate` passes with no provider setup, so CI can
  exercise every toggle without an Azure subscription.
- A fork can wire the outputs into whichever compute / network
  module they already have, without editing this repo.
- The Deployment Preflight analyzer (see
  `docs/roadmap/deployment/deployment-preflight.md`) can quote the module name +
  the `mode` value verbatim in a `terraform_toggle` detected issue, and a
  reviewer can apply the fix by changing exactly one variable.

## Layout

```text
infra/modules/preflight-toggles/
├── disk_provisioning/       # inline | attach_existing
├── nsg_provisioning/        # create | byo
├── registry_source/         # docker_io | acr_mirror
├── python_index_url/        # single string; internal mirror support
└── dependency_ordering/     # strict | best_effort
```

Each sub-module ships with:

- `main.tf` (locals-only)
- `variables.tf` (validated mode + auxiliary vars)
- `outputs.tf` (normalized effective-config outputs)
- `README.md` (usage sketch)

## Usage sketch

A consumer module wires a toggle like this:

```hcl
module "disk" {
  source              = "../preflight-toggles/disk_provisioning"
  mode                = var.disk_provisioning_mode  # 'inline' or 'attach_existing'
  existing_disk_ids   = var.existing_disk_ids
  disk_size_gb        = 128
}

resource "azurerm_linux_virtual_machine" "vm" {
  # ...
  os_disk {
    # module.disk.effective_mode == 'attach_existing' -> reference
    # module.disk.effective_mode == 'inline'          -> create
    # ...
  }
}
```

The consumer never branches on the toggle NAME - it reads the
output block and picks the resource shape.

## Not shipped here

- Live `azurerm` resource creation. The Preflight analyzer's job is to
  say "set `disk_provisioning=attach_existing`"; the consumer module
  is where the actual disk resource lives, and that stays under the
  fork's control. See
  [`reference-disk-consumer/`](reference-disk-consumer/README.md) for the
  copy-paste consumer pattern (validate-only reference).
- Cross-toggle policy composition. A fork MAY combine multiple
  toggles behind a single "environment profile" variable; upstream
  keeps each toggle isolated so a Preflight detected issue maps 1:1 to a
  variable override.
