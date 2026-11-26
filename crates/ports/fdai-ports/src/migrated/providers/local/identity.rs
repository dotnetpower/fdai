#[derive(Clone, Debug, Default, PartialEq)]
pub struct LocalWorkloadIdentityConfig {
    pub principal_object_id: String,
    pub tenant_id: String,
    pub ttl_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LocalWorkloadIdentity {
    pub initialized: bool,
}

impl LocalWorkloadIdentity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_token(&self, mut audience: String) -> String {
        let token: String = synthetic_token(audience.clone(), String::new(), String::new(), String::new());
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn synthetic_token(mut audience: String, mut principal_object_id: String, mut tenant_id: String, mut expires_at: String) -> String {
    let claims: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("aud"), audience.clone()), (String::from("oid"), principal_object_id.clone()), (String::from("tid"), tenant_id.clone()), (String::from("exp"), String::new())]);
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["LocalWorkloadIdentity", "LocalWorkloadIdentityConfig"];
