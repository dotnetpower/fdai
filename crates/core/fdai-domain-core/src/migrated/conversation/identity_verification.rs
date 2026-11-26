#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizedChannelPrincipal {
    pub principal_id: String,
    pub authorization_ref: String,
}

impl AuthorizedChannelPrincipal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.principal_id.trim().is_empty() { return Err("principal_id must be non-empty"); }
        if self.authorization_ref.trim().is_empty() { return Err("authorization_ref must be non-empty"); }
        Ok(())
    }
}

pub trait ChannelPrincipalAuthorizationMapping {
    fn resolve(&self, channel_kind: String, channel_id: String, sender_id: String) -> String;
}

pub trait PrincipalScopeAuthorization {
    fn can_access_scope(&self, principal_id: String, scope_ref: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChannelIdentityVerificationError {
    pub message: String,
}

impl ChannelIdentityVerificationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ChannelIdentityVerificationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ChannelIdentityVerificationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChannelIdentityVerificationHooks {
    pub initialized: bool,
}

impl ChannelIdentityVerificationHooks {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify_external(&self, mut turn: String, mut scope_ref: String, mut verified_at: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub fn verify_web(&self, mut authenticated_principal_id: String, mut scope_ref: String, mut channel_id: String, mut browser_session_ref: String, mut verification_ref: String, mut verified_at: String, mut thread_id: Option<String>) -> Result<String, &'static str> {
        if (authenticated_principal_id.clone()) == (browser_session_ref.clone()) {
            return Err("browser session ref MUST remain distinct from principal id");
        }
        let _ = self.authorize_scope(authenticated_principal_id.clone(), scope_ref.clone()).unwrap_or_else(|_| ());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn authorize_scope(&self, mut principal_id: String, mut scope_ref: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AuthorizedChannelPrincipal", "ChannelIdentityVerificationError", "ChannelIdentityVerificationHooks", "ChannelPrincipalAuthorizationMapping", "PrincipalScopeAuthorization"];
