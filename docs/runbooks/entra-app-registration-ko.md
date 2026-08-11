---
title: Entra 앱 등록
translation_of: entra-app-registration.md
translation_source_sha: 89a8a3f44b11773173d88aeb5d79444625ec865a
translation_revised: 2026-08-11
---

# Entra 앱 등록

FDAI 콘솔에 필요한 두 개의 Entra ID 앱 등록 - `fdai-api` (Operator API 오디언스)
와 `fdai-console-spa` (SPA 사인인 클라이언트) - 을 만들고, 사인인이 동작하게
하는 App Roles, 서비스 principal, 롤 할당을 생성하는 방법입니다. 이 런북은
**로컬 사인인 테스트**
([console/README.md § 로컬 sign-in 테스트](../../console/README.md))와
[deploy-and-onboard.md](../roadmap/deployment/deploy-and-onboard.md) 및
[user-rbac-and-identity.md § 10](../roadmap/interfaces/user-rbac-and-identity.md#10-sign-in-flow-reference)
가 참조하는 **배포 시점** 설정을 모두 다룹니다.

> Customer-agnostic: 아래의 모든 id는 셸 변수 또는 `<placeholder>` 입니다. 실제
> 테넌트 / 앱 / 범위 GUID를 추적 파일에 붙여넣지 마세요 - gitignored 된
> `.env.local` 이나 시크릿 저장소에만 두세요.

## 무엇이 생성되나

| 등록 | 목적 | 핵심 설정 |
|------|------|-----------|
| `fdai-api` | 콘솔(및 이후 ChatOps 백엔드)의 Web API 오디언스. | 애플리케이션 ID URI `api://<api-app-id>`; delegated 범위 `access` 하나; App Roles 다섯 개; v2 접근 토큰. |
| `fdai-console-spa` | SPA 사인인 클라이언트 (MSAL, PKCE). | SPA redirect URI; `fdai-api` 의 `access` 범위 에 대한 delegated 권한. |

둘 다 실행기 아이덴티티를 갖지 않습니다 - 그것은 별도의 user-assigned Managed
신원 입니다 ([security-and-identity.md](../roadmap/architecture/security-and-identity.md)).

## 사전 요구

- `az` 가 **대상 테넌트** 에 로그인. 매 단계 전에 확인:

  ```sh
  az 계정 show --query "{sub:id, 테넌트:tenantId, user:user.이름}" -o json
  ```

- 앱 등록을 만들고 admin consent를 부여할 수 있는 디렉터리 롤 (애플리케이션
  Administrator 또는 Cloud 애플리케이션 Administrator, 또는 Global
  Administrator).

- 자동 배포를 사용하는 경우 자체 호스팅 실행기 Managed Identity를
  `fdai-console-spa`의 소유자로 지정하고, Microsoft Graph
  `Application.ReadWrite.OwnedBy` 애플리케이션 권한에 admin consent를
  부여합니다. 그러면 작업 흐름은 해당 신원이 소유한 앱만 업데이트할 수 있습니다.

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

`access` delegated 범위를 추가하고 **v2** 접근 토큰을 강제합니다 (그래야
`iss` 가 검증기 가 기본으로 쓰는 `.../v2.0` 발급자가 됩니다):

```sh
API_OBJID=$(az ad app show --id "$API_APPID" --query id -o tsv)
SCOPE_GUID=$(python3 -c "import uuid; print(uuid.uuid4())")
python3 - "$SCOPE_GUID" <<'PY' > /tmp/fdai_api_scope.json
import json, sys
print(json.dumps({"api": {
  "requestedAccessTokenVersion": 2,
  "oauth2PermissionScopes": [{
    "id": sys.argv[1],
    "adminConsentDescription": "Allow the console to call the fdai Operator API on behalf of the signed-in operator",
    "adminConsentDisplayName": "Access the fdai Operator API",
    "userConsentDescription": "Allow the console to call the fdai Operator API on your behalf",
    "userConsentDisplayName": "Access the fdai Operator API",
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

### 로컬 redirect URI 동기화 유지

`console: prepare full stack` 작업은 `console/.env.local`에서 로컬 테넌트와 SPA 클라이언트 값을
읽고 `scripts/deployment/azure/sync-entra-spa-redirect.py`를 통해 두 개의 고정 Vite 출처를
안전하게 재시도할 수 있는 방식으로 동기화합니다. 보조 로직은 기존 redirect를 모두 보존합니다.
`--allow-loopback-http` 옵션은 `localhost` 또는 `127.0.0.1`에만 HTTP를 허용하며 기본 명령은
계속 HTTPS-only입니다. 테넌트가 다르거나 Microsoft Graph 권한이 부족하면 로컬 서비스가
시작되기 전에 준비 단계가 중단됩니다.

### 배포된 redirect URI 동기화 유지

각 배포 대상에 다음 GitHub Actions 저장소 variable을 설정합니다.

| 변수 | 값 |
|------|----|
| `AZURE_TENANT_ID` | 대상 Entra 테넌트 id. |
| `ENTRA_CONSOLE_SPA_CLIENT_ID` | 해당 테넌트의 `fdai-console-spa` 애플리케이션 클라이언트 id. |

`deploy-dev.yml`을 `apply=true` 및 `deploy_console=true`로 실행하면 Terraform의
`console_default_hostname`을 읽고 `scripts/deployment/azure/sync-entra-spa-redirect.py`를
실행합니다. 이 보조 로직은 다음 작업을 수행합니다.

1. 활성 Azure CLI 테넌트가 `AZURE_TENANT_ID`와 같은지 확인합니다.
2. 기존 SPA redirect URI를 모두 보존하고, 배포된 HTTPS 출처가 없을 때만
   추가합니다.
3. 앱 등록을 다시 읽고 새 URI가 보이지 않으면 배포를 실패 처리합니다.

이 작업은 안전하게 재시도할 수 있습니다. 같은 테넌트의 다른 구독은 같은
tenant-local 앱 등록을 사용합니다. 다른 테넌트에 배포하려면 해당 테넌트의 SPA
클라이언트 id와 그 테넌트가 소유한 실행기 신원이 필요합니다. 변수가 없거나 테넌트가
일치하지 않거나 Graph 권한이 부족하면, 사인인이 부분 설정된 채 남지 않도록 배포가
중단됩니다.

## 3. 서비스 principal + 롤 할당

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

## 4. id를 구성에 매핑

위 단계의 값들은 런타임 구성으로 들어갑니다. 추적 파일 밖에 보관하세요.

| 값 | Operator API env | SPA env (Vite) |
|----|--------------|----------------|
| 테넌트 id | `FDAI_ENTRA_TENANT_ID` | `VITE_MSAL_TENANT_ID` |
| `api://$API_APPID` | `FDAI_API_AUDIENCE` | - |
| `api://$API_APPID/access` | - | `VITE_MSAL_API_SCOPE` |
| `$SPA_APPID` | - | `VITE_MSAL_CLIENT_ID` |

Operator API 검증기 env: [deploy-and-onboard.md](../roadmap/deployment/deploy-and-onboard.md)
(`FDAI_ENTRA_TENANT_ID`, `FDAI_API_AUDIENCE`, 선택 `FDAI_ENTRA_ISSUER` /
`FDAI_ENTRA_JWKS_URI`). SPA env: [console/README.md § 포크 구성](../../console/README.md).

## 5. 검증

```sh
az ad app show --id "$API_APPID" \
  --query "{uri:identifierUris, tokenVer:api.requestedAccessTokenVersion, \
            scopes:api.oauth2PermissionScopes[].value, roles:appRoles[].value}" -o json
az ad app show --id "$SPA_APPID" \
  --query "{spa:spa.redirectUris, perms:requiredResourceAccess[].resourceAppId}" -o json
```

그런 다음 [console/README.md](../../console/README.md) 의 로컬 사인인 테스트를
실행합니다: 토큰 없는 요청은 `401`; App 역할 없는 로그인 사용자는 `403`;
`Reader` 를 가진 사용자는 콘솔을 로드합니다.

## 정리 (정리)

```sh
az ad app delete --id "$SPA_APPID"
az ad app delete --id "$API_APPID"
```

앱 등록을 삭제하면 그 서비스 principal과 롤 할당도 함께 제거됩니다. 클라이언트
시크릿을 추가했다면 먼저 로테이션하세요 (위 플로우는 추가하지 않습니다 - SPA는
공개 클라이언트이고 API는 토큰을 검증하므로 둘 다 시크릿을 갖지 않습니다).
