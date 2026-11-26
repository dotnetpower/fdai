pub const AZ_TIMEOUT_SECONDS: i64 = 20;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LocalAzureCliIdentity {
    pub principal: String,
    pub username: String,
    pub name: Option<String>,
}

pub const ARM_RESOURCE: &str = "https://management.azure.com";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureCliIdentityError {
    pub message: String,
}

impl AzureCliIdentityError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AzureCliIdentityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AzureCliIdentityError {}

impl LocalAzureCliIdentity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("oid"), String::new()), (String::from("username"), self.username.clone()), (String::from("name"), (self.name.clone()).unwrap_or_default()), (String::from("roles"), String::new()), (String::from("source"), String::from("azure-cli"))])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resolve_azure_cli_identity(mut runner: Option<String>) -> Result<LocalAzureCliIdentity, &'static str> {
    let account: std::collections::BTreeMap<String, String> = parse_json(String::new(), String::from("account")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    if ((account.clone()).get("state").cloned()) != Some(String::from("Enabled")) {
        return Err("the active Azure subscription is not enabled");
    }
    let user: Option<String> = (account.clone()).get("user").cloned();
    let token_result: std::collections::BTreeMap<String, String> = parse_json(String::new(), String::from("access token")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let token: Option<String> = (token_result.clone()).get("accessToken").cloned();
    if (!(true)) || (!((token.clone()).is_some())) {
        return Err("Azure CLI returned no access token run az login");
    }
    let claims: std::collections::BTreeMap<String, String> = decode_claims((token.clone()).unwrap_or_default()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let account_tenant: Option<String> = (account.clone()).get("tenantId").cloned();
    let token_tenant: Option<String> = (claims.clone()).get("tid").cloned();
    if (!(true)) || ((token_tenant.clone()) != Some((account_tenant.clone()).unwrap_or_default())) {
        return Err("Azure CLI account and access-token tenants do not match");
    }
    let oid: Option<String> = (claims.clone()).get("oid").cloned();
    if (!(true)) || (!((oid.clone()).is_some())) {
        return Err("Azure CLI user token has no stable Entra object id");
    }
    let mut username: Option<String> = first_string(claims.clone(), vec![String::from("preferred_username"), String::from("upn")]);
    let Some(mut username) = username.clone() else { return Err("Azure CLI user has no displayable username"); };
    Ok(LocalAzureCliIdentity { username: username.clone(), name: first_string(claims.clone(), vec![String::from("name")]), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn run_az(mut args: Vec<String>) -> Result<String, &'static str> {
    if args.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_json(mut raw: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn decode_claims(mut token: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn first_string(mut values: std::collections::BTreeMap<String, String>, mut keys: Vec<String>) -> Option<String> {
    for key in keys.clone() {
        let value: Option<String> = (values.clone()).get(key.as_str()).cloned();
        if (true) && ((value.clone()).is_some()) {
            return value.clone();
        }
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureCliIdentityError", "LocalAzureCliIdentity", "resolve_azure_cli_identity"];
