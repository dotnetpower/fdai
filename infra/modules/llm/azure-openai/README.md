# Azure OpenAI infra module

Optional (`var.enable_llm=true`) provisioning of the AOAI account +
per-capability deployments consumed by the T1/T2 tiers. Read
[`docs/roadmap/dev-and-deploy-parity.md`](../../../../docs/roadmap/dev-and-deploy-parity.md)
before making changes here.

## Inputs

- `name` - CAF-named AOAI account (recommend `oai-<workload>-<env>-<region>`).
- `resolved_capabilities` - array from
  `resolved-models.json`; entries with `status == "hil-only"` are excluded by
  the caller.
- `executor_principal_id` - object id of the executor MI; the module
  role-assigns `Cognitive Services OpenAI User` for runtime data-plane calls.

## Outputs

- `endpoint` - custom-subdomain URL to bind on `T2_MODEL_ENDPOINT`.
- `deployments` - capability → deployment-name map (consumed by the runtime
  container's env vars).
- `capacity_units` - capability → provisioned units (thousand TPM). The
  resolver's raw `capacity_tpm` is divided by 1000 (rounded down) with a
  floor of 1 unit.

## Guards enforced here

- Duplicate capability names are rejected in `variables.tf` validation.
- The AOAI account disables `local_auth`; only the executor MI (or another
  RBAC assignee) can call the data plane.
- Public network access is off by default; a fork opens it explicitly if the
  region's Private Link posture requires that alternative.
