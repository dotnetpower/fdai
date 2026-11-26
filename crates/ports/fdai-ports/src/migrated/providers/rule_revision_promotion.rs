pub trait RuleRevisionPromotionAuthorizer {
    fn authorize(&self, approval: String, slot: String, target_revision: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleRevisionPromotionAuthorizer"];
