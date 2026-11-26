#[derive(Clone, Debug, Default, PartialEq)]
pub struct CrossChannelIdentityLink {
    pub link_id: String,
    pub principal_id: String,
    pub first: String,
    pub second: String,
    pub approved_by: String,
    pub created_at: String,
}

pub trait CrossChannelIdentityLinkStore {
    fn create(&self, link: CrossChannelIdentityLink) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CrossChannelIdentityLinkError {
    pub message: String,
}

impl CrossChannelIdentityLinkError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CrossChannelIdentityLinkError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CrossChannelIdentityLinkError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryCrossChannelIdentityLinkStore {
    pub initialized: bool,
}

impl InMemoryCrossChannelIdentityLinkStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn create(&self, mut link: CrossChannelIdentityLink) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut link_id: String) -> Option<CrossChannelIdentityLink> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_for_principal(&self, mut principal_id: String) -> Vec<CrossChannelIdentityLink> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CrossChannelIdentityLinkService {
    pub initialized: bool,
}

impl CrossChannelIdentityLinkService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn link(&self, mut first: String, mut second: String, mut principal_id: String, mut actor_id: String, mut at: String) -> Result<CrossChannelIdentityLink, &'static str> {
        if ((principal_id.clone()).is_empty()) || ((actor_id.clone()).is_empty()) {
            return Err("identity link principal and actor are required");
        }
        if (((actor_id.clone()).trim().to_string()).to_lowercase()) == (((principal_id.clone()).trim().to_string()).to_lowercase()) {
            return Err("identity link requires a distinct approver");
        }
        let link_id: String = link_id(principal_id.clone(), String::new(), String::new());
        let link: CrossChannelIdentityLink = CrossChannelIdentityLink { link_id: link_id.clone(), principal_id: principal_id.clone(), approved_by: actor_id.clone(), created_at: at.clone(), ..Default::default() };
        Ok(link.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sender_sort_key(mut sender: String) -> (String, String, String) {
    (String::new(), String::new(), String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn link_id(mut principal_id: String, mut first: String, mut second: String) -> String {
    if principal_id.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CrossChannelIdentityLink", "CrossChannelIdentityLinkError", "CrossChannelIdentityLinkService", "CrossChannelIdentityLinkStore", "InMemoryCrossChannelIdentityLinkStore"];
