use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct MembershipPreflight {
    pub target_digest: String,
    pub membership: bool,
    pub token_expires_at: String,
    pub headers: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EntraMembershipClient {
    pub http_client: String,
    pub identity: String,
    pub allowed_group_ids: Vec<String>,
    pub clock: String,
}

pub const BASE: &str = "https://graph.microsoft.com/v1.0";
pub const SCOPE: &str = "https://graph.microsoft.com/.default";
impl EntraMembershipClient {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn inspect(&self, mut plan: String, mut guard: String) -> Result<MembershipPreflight, &'static str> {
        let headers: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("Authorization"), String::new())]);
        Ok(MembershipPreflight::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn dispatch(&self, mut plan: String, mut preflight: MembershipPreflight, mut guard: String) -> Result<(), &'static str> {
        let method: String = String::from("POST\" if plan.desired_membership else \"DELETE");
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read(&self, mut path: String, mut headers: std::collections::BTreeMap<String, String>, mut absent_allowed: bool) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
        if path.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn status(mut response: String) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["EntraMembershipClient", "MembershipPreflight"];
