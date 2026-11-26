pub trait RuleIdentityUpgradeAuthorizer {
    fn authorize_identity_upgrade(&self, approval: String, proposal: String, baseline: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleIdentityUpgradeAuthorizer"];
