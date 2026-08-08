---
name: azure-selfprovision
description: |
  Self-provision the Azure resources FDAI needs into the operator's OWN
  logged-in subscription, instead of borrowing another project's account.
  Primary trigger: `resolved-models.json` / `resolved-models-local.json`
  points a `narrator` / capability endpoint at a foreign resource group's
  Azure OpenAI account (an endpoint FDAI does not own). Load this skill
  when the project is opened with `az login` already active and you want
  to propose + create the required resource group and resources, when an
  AOAI endpoint in `resolved-models*.json` belongs to a different project,
  when a local narrator / LLM path fails because no FDAI-owned AOAI exists,
  or when onboarding a fresh subscription for local dev. For the full
  private-tenant deploy pipeline (state SA + runner VM + app stack) use
  `azure-deploy-runner` instead; this skill covers the lighter
  "make the LLM path stand on its own resources" flow.
version: 1.0.0
scope: repository
---

# Self-Provision FDAI's Required Azure Resources

FDAI resolves its LLM capability registry
([rule-catalog/llm-registry.yaml](../../../rule-catalog/llm-registry.yaml))
into a runtime map, `resolved-models.json` (deploy) or
`resolved-models-local.json` (local dev). Each capability - and the
console `narrator` - carries an Azure OpenAI (AOAI) `endpoint`. When that
endpoint belongs to **another project's resource group**, FDAI is
borrowing a foreign account: the mapping breaks the moment that account
is rotated, its quota is spent elsewhere, or its owner revokes your role.

This skill makes the LLM path **stand on resources the operator owns** in
their own logged-in subscription. It is deliberately narrow: it
provisions the minimum (a resource group + an AOAI account + the
deployments the registry needs) and regenerates `resolved-models*.json`
to point at the new, owned endpoint. It never runs a destructive change
and never hardcodes a tenant, subscription, or resource identifier (those
live only in the maintainer's `/memories/`, per
[generic-scope.instructions.md](../../instructions/generic-scope.instructions.md)).

## When To Offer This (on project open)

When the project opens and `az` is already authenticated, it is
appropriate to proactively check the LLM wiring and offer to fix it.
Trigger the proposal when ALL of these hold:

1. `az account show` succeeds (a login is present).
2. A `resolved-models.json` or `resolved-models-local.json` exists and
   its `narrator` / capability `endpoint`(s) resolve to an AOAI account
   the current subscription does **not** contain (a foreign RG), OR no
   `resolved-models*.json` exists at all.
3. The operator has not opted out.

If any check fails, stay silent - do not nag, and never auto-create Azure
resources without an explicit go-ahead. Provisioning is a
propose-then-create flow, not an on-open side effect.

## Step 0 - Confirm the target subscription (MUST)

Two profiles are common on a dev machine (a default profile plus a
customer profile under `$HOME/.azure-customer`). Provisioning into the
wrong subscription is the failure this step prevents.

```bash
# Default profile:
az account show --query "{name:name, id:id, tenantId:tenantId}" -o jsonc
# Customer profile, when present:
AZURE_CONFIG_DIR=$HOME/.azure-customer az account show \
  --query "{name:name, id:id, tenantId:tenantId}" -o jsonc
```

State the resolved subscription name + id back to the operator and get an
explicit "yes, this one" before creating anything. Never assume the
default profile is the intended target.

## Step 1 - Detect the borrowed / missing endpoint

```bash
# What endpoint(s) is FDAI currently pointing at?
grep -o 'https://[a-z0-9-]*\.openai\.azure\.com' \
  resolved-models*.json 2>/dev/null | sort -u

# Does the current subscription actually own an AOAI account?
az cognitiveservices account list \
  --query "[?kind=='OpenAI'].{name:name, rg:resourceGroup, endpoint:properties.endpoint}" \
  -o table
```

If the endpoint from the first command does not appear in the second
list, FDAI is borrowing a foreign account. That is the condition to fix.

## Step 2 - Decide the shape (light vs full)

| Path | Use when | Provisions | Owner |
|------|----------|-----------|-------|
| **Light (local dev)** | you just need the narrator / a real LLM locally | one AOAI account + one mini deployment, public network + keyless (`az login`) | this skill |
| **Full (dev deploy)** | you are standing up the whole control plane | AOAI in the **app RG** with every capability deployment, private + keyless, via `terraform -var enable_llm=true` | `azure-deploy-runner` + `infra/` |

The AOAI account belongs in the **app** resource group
(`rg-fdai-dev-krc`), NOT the ops resource group (`rg-fdai-ops-krc`). The
ops RG holds state storage + the runner VM + the hub VNet by design; an
AOAI account there would be a layering mistake. For the light local path
you MAY create a dedicated dev RG so nothing else is disturbed.

## Step 3 (Light path) - create an owned AOAI + regenerate the map

Propose these commands, then run them only after the operator confirms
the subscription from Step 0. Names follow the CAF convention
(`oai-` prefix for the account); pick a region the operator wants.

```bash
REGION=koreacentral
RG=rg-fdai-dev-krc                 # app RG (see deploy-and-onboard.md)
AOAI=oai-fdai-dev-krc              # CAF: oai-<workload>-<env>-<region_short>

# 1. Resource group (idempotent).
az group create -n "$RG" -l "$REGION" -o none

# 2. AOAI account: public network ON + keyless (Azure AD) so a laptop can
#    reach it during local dev. (The infra module uses private + keyless
#    for deploy; local dev needs public reachability.)
az cognitiveservices account create -n "$AOAI" -g "$RG" -l "$REGION" \
  --kind OpenAI --sku S0 --custom-domain "$AOAI" \
  --assign-identity --yes -o none

# 3. Grant YOURSELF the data-plane role (keyless calls via `az login`).
ME=$(az ad signed-in-user show --query id -o tsv)
SCOPE=$(az cognitiveservices account show -n "$AOAI" -g "$RG" --query id -o tsv)
az role assignment create --assignee "$ME" \
  --role "Cognitive Services OpenAI User" --scope "$SCOPE" -o none

# 4. A mini deployment for the narrator / t1.judge (pick a family the
#    region catalog offers - check `az cognitiveservices account list-models`).
az cognitiveservices account deployment create -n "$AOAI" -g "$RG" \
  --deployment-name gpt-4o-mini --model-name gpt-4o-mini \
  --model-format OpenAI --sku-name Standard --sku-capacity 10 -o none

# 5. New owned endpoint.
ENDPOINT=$(az cognitiveservices account show -n "$AOAI" -g "$RG" \
  --query properties.endpoint -o tsv)
echo "owned endpoint: $ENDPOINT"
```

Then regenerate the runtime map so it points at the owned endpoint. Use
the resolver's live path (`--use-azure-cli` reads the real catalog / quota
/ role assignments; `az login` must already hold a valid token):

```bash
python -m fdai.rule_catalog.schema.llm_resolver_cli \
  --registry rule-catalog/llm-registry.yaml \
  --region "$REGION" \
  --subscription-id "$(az account show --query id -o tsv)" \
  --deployer-object-id "$ME" \
  --use-azure-cli \
  --narrator-endpoint "$ENDPOINT" \
  --out resolved-models-local.json
```

Confirm the borrowed endpoint is gone:

```bash
grep -o 'https://[a-z0-9-]*\.openai\.azure\.com' resolved-models-local.json | sort -u
```

`resolved-models.json` and `resolved-models-local.json` are gitignored
generated artifacts (see the repo hints in
[copilot-instructions.md](../../copilot-instructions.md)) - regenerate
them, never hand-edit and never commit them.

## Step 4 (Full path) - hand off to the deploy pipeline

For a real deployment, do not build AOAI by hand. Set `enable_llm=true`
and pass the resolver's capability output as `resolved_capabilities` so
the `infra/modules/llm/azure-openai` module creates the account +
one deployment per capability in the app RG. Follow
[azure-deploy-runner](../azure-deploy-runner/SKILL.md) for the runner /
private-network mechanics and
[deploy-and-onboard.md](../../../docs/roadmap/deployment/deploy-and-onboard.md)
row 11 for the LLM provisioning gate (Cognitive Services Contributor +
region family availability, else the capability degrades to `hil-only`).

## Guardrails (MUST)

- **Validate code before Azure mutation.** Before creating an account, role assignment, or model
  deployment, finish and commit the local code slice and require
  `python3 scripts/automation/validation_queue.py check-commit HEAD` to pass. A standalone
  environment repair with no code change still targets the currently receipted `HEAD`. Read-only
  account and inventory checks may run earlier.
- **Confirm the subscription first** (Step 0). Never create resources in a
  profile the operator did not confirm this session.
- **Propose, then create.** Print the exact commands and the target
  sub / RG / region; create only after an explicit go-ahead. Never
  auto-provision as an on-open side effect.
- **No destructive actions.** This skill only creates (idempotent) and
  regenerates the gitignored map. It never deletes an RG, account, or
  deployment - a wrong-account cleanup is a separate, operator-approved
  step.
- **Customer-agnostic.** Do not write any tenant / subscription / resource
  / customer identifier into this skill, the repo, or any doc. Generic CAF
  names (`rg-fdai-dev-krc`, `oai-fdai-dev-krc`) are fine; real values live
  only in the maintainer's `/memories/`.
- **Cost + policy.** Creating an AOAI account and a deployment consumes
  quota and may incur cost. Respect any active cost or "no deploy before a
  milestone" rule the maintainer set for this session.

## Related

- Borrowed-vs-owned deploy mechanics:
  [azure-deploy-runner](../azure-deploy-runner/SKILL.md).
- LLM resolver + capability registry:
  [docs/roadmap/architecture/llm-strategy.md](../../../docs/roadmap/architecture/llm-strategy.md).
- Deployer-scoped LLM provisioning gate:
  [docs/roadmap/deployment/dev-and-deploy-parity.md](../../../docs/roadmap/deployment/dev-and-deploy-parity.md).
- Azure resource inventory (row 11 = AOAI):
  [docs/roadmap/deployment/deploy-and-onboard.md](../../../docs/roadmap/deployment/deploy-and-onboard.md).
- Customer-agnostic scope:
  [.github/instructions/generic-scope.instructions.md](../../instructions/generic-scope.instructions.md).
