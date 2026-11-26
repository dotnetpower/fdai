#[derive(Clone, Debug, Default, PartialEq)]
pub struct IdentityToken {
    pub token: String,
    pub expires_at: String,
    pub audience: String,
}

pub trait WorkloadIdentity {
    fn get_token(&self, audience: String) -> IdentityToken;
}

pub const PUBLIC_EXPORTS: &[&str] = &["IdentityToken", "WorkloadIdentity"];
