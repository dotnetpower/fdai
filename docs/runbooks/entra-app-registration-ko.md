---
title: Entra 앱 등록
translation_of: entra-app-registration.md
translation_source_sha: 99ad731a1e59e21405ae293539bcddcad7569372
translation_revised: 2026-07-18
---

# Entra 앱 등록

FDAI 콘솔에 필요한 두 개의 Entra ID 앱 등록 - `fdai-api` (read-API 오디언스)
와 `fdai-console-spa` (SPA 사인인 클라이언트) - 을 만들고, 사인인이 동작하게
하는 App Roles, service principal, 롤 할당을 생성하는 방법입니다. 이 runbook은
**로컬 사인인 테스트**
([console/README.md § Local sign-in test](../../console/README.md))와
[deploy-and-onboard.md](../roadmap/deployment/deploy-and-onboard.md) 및
[user-rbac-and-identity.md § 10](../roadmap/interfaces/user-rbac-and-identity.md#10-sign-in-flow-reference)
가 참조하는 **배포 시점** 설정을 모두 다룹니다.

> Customer-agnostic: 아래의 모든 id는 셸 변수 또는 `<placeholder>` 입니다. 실제
> tenant / app / scope GUID를 추적 파일에 붙여넣지 마세요 - gitignored 된
> `.env.local` 이나 secret store에만 두세요.

## 무엇이 생성되나

| 등록 | 목적 | 핵심 설정 |
|------|------|-----------|
| `fdai-api` | 콘솔(및 이후 ChatOps 백엔드)의 Web API 오디언스. | Application ID URI `api://<api-app-id>`; delegated scope `access` 하나; App Roles 다섯 개; v2 access token. |
| `fdai-console-spa` | SPA 사인인 클라이언트 (MSAL, PKCE). | SPA redirect URI; `fdai-api` 의 `access` scope 에 대한 delegated 권한. |

둘 다 executor 아이덴티티를 갖지 않습니다 - 그것은 별도의 user-assigned Managed
Identity 입니다 ([security-and-identity.md](../roadmap/architecture/security-and-identity.md)).

## 사전 요구

- `az` 가 **대상 tenant** 에 로그인. 매 단계 전에 확인:

  ```sh
  az account show --query "{sub:id, tenant:tenantId, user:user.name}" -o json
  ```

- 앱 등록을 만들고 admin consent를 부여할 수 있는 디렉터리 롤 (Application
  Administrator 또는 Cloud Application Administrator, 또는 Global
  Administrator).

- 자동 배포를 사용하는 경우 self-hosted runner Managed Identity를
  `fdai-console-spa`의 소유자로 지정하고, Microsoft Graph
  `Application.ReadWrite.OwnedBy` application permission에 admin consent를
  부여합니다. 그러면 workflow는 해당 identity가 소유한 앱만 업데이트할 수 있습니다.

## 1. `fdai-api` 생성

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

`access` delegated scope를 추가하고 **v2** access token을 강제합니다 (그래야
`iss` 가 verifier 가 기본으로 쓰는 `.../v2.0` 발급자가 됩니다):

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

## 2. `fdai-console-spa` 생성

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
  "spa": {"redirectUris": ["http://localhost:5173", "http://127.0.0.1:5173"]},
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

### 배포된 redirect URI 동기화 유지

각 배포 대상에 다음 GitHub Actions repository variable을 설정합니다.

| 변수 | 값 |
|------|----|
| `AZURE_TENANT_ID` | 대상 Entra tenant id. |
| `ENTRA_CONSOLE_SPA_CLIENT_ID` | 해당 tenant의 `fdai-console-spa` application client id. |

`deploy-dev.yml`을 `apply=true` 및 `deploy_console=true`로 실행하면 Terraform의
`console_default_hostname`을 읽고 `scripts/deployment/azure/sync-entra-spa-redirect.py`를
실행합니다. 이 helper는 다음 작업을 수행합니다.

1. 활성 Azure CLI tenant가 `AZURE_TENANT_ID`와 같은지 확인합니다.
2. 기존 SPA redirect URI를 모두 보존하고, 배포된 HTTPS origin이 없을 때만
   추가합니다.
3. 앱 등록을 다시 읽고 새 URI가 보이지 않으면 배포를 실패 처리합니다.

이 작업은 안전하게 재시도할 수 있습니다. 같은 tenant의 다른 subscription은 같은
tenant-local 앱 등록을 사용합니다. 다른 tenant에 배포하려면 해당 tenant의 SPA
client id와 그 tenant가 소유한 runner identity가 필요합니다. 변수가 없거나 tenant가
일치하지 않거나 Graph 권한이 부족하면, 사인인이 부분 설정된 채 남지 않도록 배포가
중단됩니다.

## 3. Service principal + 롤 할당

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

실제 배포에서는 App Roles를 개별 사용자가 아니라 다섯 개의 `aw-*` Entra 보안
그룹에 할당하세요
([user-rbac-and-identity.md § 4.4](../roadmap/interfaces/user-rbac-and-identity.md#44-app-roles-token-surface)).

## 4. id를 config에 매핑

위 단계의 값들은 런타임 config로 들어갑니다. 추적 파일 밖에 보관하세요.

| 값 | Read API env | SPA env (Vite) |
|----|--------------|----------------|
| Tenant id | `FDAI_ENTRA_TENANT_ID` | `VITE_MSAL_TENANT_ID` |
| `api://$API_APPID` | `FDAI_API_AUDIENCE` | - |
| `api://$API_APPID/access` | - | `VITE_MSAL_API_SCOPE` |
| `$SPA_APPID` | - | `VITE_MSAL_CLIENT_ID` |

Read-API verifier env: [deploy-and-onboard.md](../roadmap/deployment/deploy-and-onboard.md)
(`FDAI_ENTRA_TENANT_ID`, `FDAI_API_AUDIENCE`, 선택 `FDAI_ENTRA_ISSUER` /
`FDAI_ENTRA_JWKS_URI`). SPA env: [console/README.md § Fork configuration](../../console/README.md).

## 5. 검증

```sh
az ad app show --id "$API_APPID" \
  --query "{uri:identifierUris, tokenVer:api.requestedAccessTokenVersion, \
            scopes:api.oauth2PermissionScopes[].value, roles:appRoles[].value}" -o json
az ad app show --id "$SPA_APPID" \
  --query "{spa:spa.redirectUris, perms:requiredResourceAccess[].resourceAppId}" -o json
```

그런 다음 [console/README.md](../../console/README.md) 의 로컬 사인인 테스트를
실행합니다: 토큰 없는 요청은 `401`; App Role 없는 로그인 사용자는 `403`;
`Reader` 를 가진 사용자는 콘솔을 로드합니다.

## 정리 (teardown)

```sh
az ad app delete --id "$SPA_APPID"
az ad app delete --id "$API_APPID"
```

앱 등록을 삭제하면 그 service principal과 롤 할당도 함께 제거됩니다. client
secret을 추가했다면 먼저 로테이션하세요 (위 플로우는 추가하지 않습니다 - SPA는
public client이고 API는 토큰을 검증하므로 둘 다 secret을 갖지 않습니다).
