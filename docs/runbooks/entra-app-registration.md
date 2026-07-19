---
title: Entra App Registration
---

# Entra App Registration

How to create the two Entra ID app registrations the FDAI console needs -
`fdai-api` (the read-API audience) and `fdai-console-spa` (the SPA sign-in
client) - plus the App Roles, service principals, and role assignment that make
sign-in work. This runbook covers both the **local sign-in test**
([console/README.md § Local sign-in test](../../console/README.md)) and the
**deploy-time** setup referenced by
[deploy-and-onboard.md](../roadmap/deployment/deploy-and-onboard.md) and
[user-rbac-and-identity.md § 10](../roadmap/interfaces/user-rbac-and-identity.md#10-sign-in-flow-reference).

> Customer-agnostic: every id below is a shell variable or a `<placeholder>`.
> Never paste a real tenant, app, or scope GUID into a tracked file - keep them
> in a gitignored `.env.local` or a secret store.

## What gets created

| Registration | Purpose | Key settings |
|--------------|---------|--------------|
| `fdai-api` | Web API audience for the console (and later ChatOps backend). | Application ID URI `api://<api-app-id>`; one delegated scope `access`; five App Roles; v2 access tokens. |
| `fdai-console-spa` | SPA sign-in client (MSAL, PKCE). | SPA redirect URIs; delegated permission to `fdai-api`'s `access` scope. |

Neither holds the executor identity - that is a separate user-assigned Managed
Identity ([security-and-identity.md](../roadmap/architecture/security-and-identity.md)).

## Prerequisites

- `az` logged in to the **target tenant**. Confirm before every step:

  ```sh
  az account show --query "{sub:id, tenant:tenantId, user:user.name}" -o json
  ```

- A directory role that may create app registrations and grant admin consent
  (Application Administrator or Cloud Application Administrator, or Global
  Administrator).

- For automated deployment, the self-hosted runner Managed Identity is an owner
  of `fdai-console-spa` and has the Microsoft Graph
  `Application.ReadWrite.OwnedBy` application permission with admin consent.
  This lets the workflow update only applications owned by that identity.

## 1. Create `fdai-api`

```sh
# Single-tenant API app.
API_APPID=$(az ad app create \
  --display-name "fdai-api" \
  --sign-in-audience AzureADMyOrg \
  --query appId -o tsv)

# Five App Roles (values MUST equal the Role enum in core/rbac/roles.py:
# Reader / Contributor / Approver / Owner / BreakGlass).
python3 - <<'PY' > /tmp/fdai_approles.json
import json, uuid
roles = [
    ("Reader", "View the operator console"),
    ("Contributor", "Reader plus author draft governance PRs"),
    ("Approver", "Contributor plus review and approve governance PRs and HIL"),
    ("Owner", "Full administration of the fork's control plane"),
    ("BreakGlass", "Segregated emergency access (never auto-activated)"),
]
print(json.dumps([{
    "allowedMemberTypes": ["User"], "description": d, "displayName": n,
    "id": str(uuid.uuid4()), "isEnabled": True, "value": n,
} for n, d in roles]))
PY
az ad app update --id "$API_APPID" --app-roles @/tmp/fdai_approles.json
az ad app update --id "$API_APPID" --identifier-uris "api://$API_APPID"
```

Add the `access` delegated scope and force **v2** access tokens (so `iss` is the
`.../v2.0` issuer the verifier defaults to):

```sh
API_OBJID=$(az ad app show --id "$API_APPID" --query id -o tsv)
SCOPE_GUID=$(python3 -c "import uuid; print(uuid.uuid4())")
python3 - "$SCOPE_GUID" <<'PY' > /tmp/fdai_api_scope.json
import json, sys
print(json.dumps({"api": {
  "requestedAccessTokenVersion": 2,
  "oauth2PermissionScopes": [{
    "id": sys.argv[1],
    "adminConsentDescription": "Allow the console to call the fdai read API on behalf of the signed-in operator",
    "adminConsentDisplayName": "Access the fdai read API",
    "userConsentDescription": "Allow the console to call the fdai read API on your behalf",
    "userConsentDisplayName": "Access the fdai read API",
    "isEnabled": True, "type": "User", "value": "access",
  }],
}}))
PY
az rest --method PATCH \
  --uri "https://graph.microsoft.com/v1.0/applications/$API_OBJID" \
  --headers "Content-Type=application/json" \
  --body @/tmp/fdai_api_scope.json
```

## 2. Create `fdai-console-spa`

```sh
SPA_APPID=$(az ad app create \
  --display-name "fdai-console-spa" \
  --sign-in-audience AzureADMyOrg \
  --query appId -o tsv)
SPA_OBJID=$(az ad app show --id "$SPA_APPID" --query id -o tsv)

# Seed local Vite origins here. The deploy workflow adds the deployed console
# HTTPS origin after Terraform creates the Static Web App.
SCOPE_GUID=$(az ad app show --id "$API_APPID" \
  --query "api.oauth2PermissionScopes[?value=='access'].id | [0]" -o tsv)
python3 - "$API_APPID" "$SCOPE_GUID" <<'PY' > /tmp/fdai_spa.json
import json, sys
print(json.dumps({
  "spa": {"redirectUris": ["http://localhost:5273", "http://127.0.0.1:5273"]},
  "requiredResourceAccess": [{
    "resourceAppId": sys.argv[1],
    "resourceAccess": [{"id": sys.argv[2], "type": "Scope"}],
  }],
}))
PY
az rest --method PATCH \
  --uri "https://graph.microsoft.com/v1.0/applications/$SPA_OBJID" \
  --headers "Content-Type=application/json" \
  --body @/tmp/fdai_spa.json
```

### Keep the deployed redirect URI synchronized

Set these GitHub Actions repository variables for each deployment target:

| Variable | Value |
|----------|-------|
| `AZURE_TENANT_ID` | Target Entra tenant id. |
| `ENTRA_CONSOLE_SPA_CLIENT_ID` | Application client id of that tenant's `fdai-console-spa`. |

When `deploy-dev.yml` runs with both `apply=true` and `deploy_console=true`, it
reads `console_default_hostname` from Terraform and runs
`scripts/deployment/azure/sync-entra-spa-redirect.py`. The helper:

1. Verifies that the active Azure CLI tenant equals `AZURE_TENANT_ID`.
2. Preserves every existing SPA redirect URI and adds the deployed HTTPS origin
  only when it is missing.
3. Reads the app registration again and fails the deployment if the new URI is
  not visible.

The operation is safe to retry (idempotent). A different subscription in the
same tenant uses the same tenant-local app registration. A deployment to a
different tenant needs that tenant's SPA client id and a runner identity owned
by that tenant. Missing variables, a tenant mismatch, or insufficient Graph
permission stops the deployment instead of leaving sign-in partially configured.

## 3. Service principals + role assignment

```sh
# Enterprise apps (needed for App Role assignment + admin consent).
az ad sp create --id "$API_APPID"
az ad sp create --id "$SPA_APPID"

# Assign a user the Reader App Role on fdai-api (repeat per user/role).
USER_OBJID=$(az ad signed-in-user show --query id -o tsv)   # or another user's id
API_SP_OBJID=$(az ad sp show --id "$API_APPID" --query id -o tsv)
READER_ROLE_ID=$(az ad app show --id "$API_APPID" \
  --query "appRoles[?value=='Reader'].id | [0]" -o tsv)
python3 - "$USER_OBJID" "$API_SP_OBJID" "$READER_ROLE_ID" <<'PY' > /tmp/fdai_assign.json
import json, sys
print(json.dumps({"principalId": sys.argv[1], "resourceId": sys.argv[2], "appRoleId": sys.argv[3]}))
PY
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$API_SP_OBJID/appRoleAssignedTo" \
  --headers "Content-Type=application/json" \
  --body @/tmp/fdai_assign.json

# One-time admin consent so a signed-in user gets no consent prompt.
az ad app permission admin-consent --id "$SPA_APPID"
```

For a real deployment, assign the App Roles to the five `aw-*` Entra security
groups instead of to individual users
([user-rbac-and-identity.md § 4.4](../roadmap/interfaces/user-rbac-and-identity.md#44-app-roles-token-surface)).

## 4. Map ids to configuration

The values from the steps above feed the runtime config. Keep them out of
tracked files.

| Value | Read API env | SPA env (Vite) |
|-------|--------------|----------------|
| Tenant id | `FDAI_ENTRA_TENANT_ID` | `VITE_MSAL_TENANT_ID` |
| `api://$API_APPID` | `FDAI_API_AUDIENCE` | - |
| `api://$API_APPID/access` | - | `VITE_MSAL_API_SCOPE` |
| `$SPA_APPID` | - | `VITE_MSAL_CLIENT_ID` |

Read-API verifier env: [deploy-and-onboard.md](../roadmap/deployment/deploy-and-onboard.md)
(`FDAI_ENTRA_TENANT_ID`, `FDAI_API_AUDIENCE`, optional `FDAI_ENTRA_ISSUER` /
`FDAI_ENTRA_JWKS_URI`). SPA env: [console/README.md § Fork configuration](../../console/README.md).

## 5. Verify

```sh
az ad app show --id "$API_APPID" \
  --query "{uri:identifierUris, tokenVer:api.requestedAccessTokenVersion, \
            scopes:api.oauth2PermissionScopes[].value, roles:appRoles[].value}" -o json
az ad app show --id "$SPA_APPID" \
  --query "{spa:spa.redirectUris, perms:requiredResourceAccess[].resourceAppId}" -o json
```

Then run the local sign-in test in
[console/README.md](../../console/README.md): a request with no token returns
`401`; a signed-in user with no App Role returns `403`; a user with `Reader`
loads the console.

## Teardown

```sh
az ad app delete --id "$SPA_APPID"
az ad app delete --id "$API_APPID"
```

Deleting the app registrations also removes their service principals and role
assignments. Rotate any client secret first if one was added (the flows above
add none - the SPA is a public client and the API validates tokens, neither
holds a secret).
