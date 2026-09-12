---
title: Onboard the System Knowledge Teams Bot
---
# Onboard the System Knowledge Teams Bot

Use this runbook to prepare and deploy the independent FDAI System Knowledge Service in one
approved standard Teams channel. You can use a Bot Framework application or a team-scoped Teams
Outgoing Webhook named `FDAI-bot`. The Outgoing Webhook path needs no Entra application
registration, app package, or Microsoft Graph installation permission.

> **Scope:** This runbook covers the development environment. It does not change the operational
> A3 bot, request resource-specific consent (RSC) for all channel messages, or grant managed-resource
> execution authority.
>
> **Private tenant:** Run Key Vault, Blob, Terraform state, and Container Apps work through the
> VNet-connected self-hosted runner. Do not copy a secret or private state file to a laptop.

## Prerequisites

You need:

- an approved standard Team and channel;
- an enabled Teams service plan for the maintainer when a dedicated Team must be created;
- one or more Entra users mapped to stable FDAI knowledge principal names;
- a clean, pushed protected-main revision with required CI and an attested
  `fdai-system-knowledge-service` image;
- tenant administration permission to bootstrap the deployment-only installer identity when you
  select Bot Framework;
- Team owner permission to create an Outgoing Webhook when you select that transport;
- the existing private FDAI platform with document Blob storage enabled.

Private and shared channels are not supported by the initial release.

## Configure the Teams profile

Create these repository secrets without writing their values to source control:

| Secret | Content |
|--------|---------|
| `SYSTEM_KNOWLEDGE_TEAMS_PROFILE_JSON` | Selected transport, service name, tenant, approved team and channel lists, and transport-specific trust roots |
| `SYSTEM_KNOWLEDGE_PRINCIPAL_MAP_JSON` | Teams sender `aadObjectId` to deployment-local knowledge principal mapping |
| `SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET` | Teams-issued Base64 HMAC key; set only after Outgoing Webhook bootstrap |

For an Outgoing Webhook, use this profile:

```json
{
  "transport": "outgoing_webhook",
  "service_name": "<container-app-name>",
  "tenant_id": "<tenant-guid>",
  "team_ids": ["<team-guid>"],
  "channel_ids": ["<channel-id>"]
}
```

For Bot Framework, use the existing profile:

```json
{
  "transport": "bot_framework",
  "service_name": "<container-app-name>",
  "bot_name": "<azure-bot-name>",
  "tenant_id": "<tenant-guid>",
  "team_ids": ["<team-guid>"],
  "channel_ids": ["<channel-id>"],
  "allowed_service_urls": ["https://<bot-service-origin>"],
  "jwks_url": "https://<bot-service-jwks-url>"
}
```

Use this shape for the principal map:

```json
{
  "<entra-user-object-id>": "<knowledge-principal>"
}
```

The protected workflow writes only the principal map to one fixed Key Vault secret. The other
values remain protected deployment inputs and appear in the restricted Terraform state. For an
Outgoing Webhook enable transition, the workflow also writes and reads back the HMAC key under a
second fixed Key Vault secret. The HMAC value never enters Terraform state.

## Bootstrap the deployment-only installer for Bot Framework

The installer uses exactly two Microsoft Graph application permissions:

- `AppCatalog.ReadWrite.All`;
- `TeamsAppInstallation.ReadWriteForTeam.All`.

The runtime UAMI does not receive either permission. Bootstrap the installer once while signed in
as a tenant administrator:

```bash
result="$(
  uv run --frozen --package fdai-system-knowledge-service python \
    scripts/deployment/system_knowledge/bootstrap_installer_identity.py \
    --repository dotnetpower/fdai \
    --environment dev
)"
client_id="$(jq -er '.client_id' <<<"$result")"
gh variable set SYSTEM_KNOWLEDGE_INSTALLER_CLIENT_ID --body "$client_id"
result=""
client_id=""
```

The helper creates or verifies one Entra application, service principal, GitHub
`repo:dotnetpower/fdai:environment:dev` federated credential, and the exact two Graph roles. The
apply job exchanges GitHub OIDC for a short-lived Graph token. No client secret is created.

## Bootstrap an Outgoing Webhook

First run the protected workflow with `transition=bootstrap`. Use the same plan-only and exact
apply evidence flow described below. Bootstrap creates the Container App, private claim container,
and dedicated UAMI without an Azure Bot, Teams channel resource, app package, or HMAC binding.

After apply, copy the callback URL from the workflow summary. In Teams, open **Manage team** >
**Apps** > **Upload an app** > **Create an outgoing webhook**, then:

1. set the name to `FDAI-bot`;
2. paste the exact callback URL;
3. add a bounded description and optional image;
4. create the webhook;
5. store the displayed HMAC key directly in the protected repository secret by running
   `gh secret set SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET` and entering the value only at the
   terminal prompt.

Do not paste the key into chat, a command argument, a file, or workflow input. After the secret is
set, create a fresh `transition=enable` plan and apply its exact evidence. Enable writes the HMAC
key inside the VNet, adds the versionless Key Vault reference, and creates a new Container App
revision. The bootstrap endpoint returns `503 outgoing_webhook_unconfigured` until this step
completes.

## Plan the deployment

Resolve the attested image digest for the exact required-CI revision, then dispatch plan-only:

```bash
gh workflow run system-knowledge-deploy.yml \
  -f commit_sha=<exact-sha> \
  -f image_ref=ghcr.io/dotnetpower/fdai/fdai-system-knowledge-service@sha256:<digest> \
  -f previous_image_ref=ghcr.io/dotnetpower/fdai/fdai-system-knowledge-service@sha256:<digest> \
  -f transition=<bootstrap-or-enable>
```

Every plan is accepted only when it contains the dedicated UAMI, private claim container, three
minimum role assignments, one-replica Container App, and `execution_authority=false` contract. A
Bot Framework plan also contains the F0 Azure Bot and Teams channel. An Outgoing Webhook plan must
contain neither.

Record the plan run id, attempt, plan digest, and context digest from the workflow summary.

## Apply and install

Dispatch apply with the exact plan evidence:

```bash
gh workflow run system-knowledge-deploy.yml \
  -f commit_sha=<exact-sha> \
  -f image_ref=ghcr.io/dotnetpower/fdai/fdai-system-knowledge-service@sha256:<digest> \
  -f previous_image_ref=ghcr.io/dotnetpower/fdai/fdai-system-knowledge-service@sha256:<digest> \
  -f transition=<bootstrap-or-enable> \
  -f apply=true \
  -f plan_run_id=<plan-run-id> \
  -f plan_run_attempt=<attempt> \
  -f plan_digest=<plan-sha256> \
  -f context_digest=sha256:<context-sha256>
```

The workflow:

1. replays and guards the exact binary plan;
2. materializes and reads back the principal map inside the private VNet;
3. applies the plan;
4. verifies the active healthy revision and private Blob claim container;
5. for Bot Framework, builds the deterministic Teams package and uses the deployment-only OIDC
   identity to upload and install it;
6. for Outgoing Webhook, proves that no Azure Bot exists and exposes the callback URL in the
   workflow summary.

## Validate the channel

In the approved standard channel:

1. Mention `FDAI Knowledge` for Bot Framework or `FDAI-bot` for Outgoing Webhook and ask how FDAI
   keeps actions safe.
2. Verify that one same-conversation reply contains designed behavior, implementation evidence,
   limitations, source paths, and `execution_authority=false`.
3. Restart the exact Container App revision.
4. Confirm that no prior message is replied to again.
5. Send another mention and confirm one new reply.
6. Retain only content-free claim, revision, delivery, and timing evidence.

Do not copy conversation text, user identifiers, Team ids, or channel ids into the repository.

## Rehearse disable and rollback

Create a new plan with `transition=disable`, then apply its exact evidence using the same workflow.
The apply must finish within 15 minutes and leave the dedicated service Terraform state empty. Core,
Operator Service, document services, the Isolated Executor, and the operational A3 edge must remain
unchanged.

After recording rollback evidence, create and apply a fresh `enable` plan if the approved target
state is to keep the bot running.

## Related docs

| To learn about | Read |
|----------------|------|
| Service design and failure behavior | [System Knowledge Service](../roadmap/interfaces/system-knowledge-service.md) |
| Private deployment runner | [Deploy and onboard](../roadmap/deployment/deploy-and-onboard.md) |
| Service graduation gates | [Service graduation and data ownership](../roadmap/architecture/service-graduation-and-ownership.md) |
| Operational Teams conversations | [Production A3 channel runtime](../roadmap/interfaces/production-a3-channel-runtime.md) |
