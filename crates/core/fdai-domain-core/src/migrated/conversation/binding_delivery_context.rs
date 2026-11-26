pub trait ChannelScopeResolver {
    fn resolve_scope(&self, turn: String, principal: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VerifiedBindingDeliveryContextResolver {
    pub initialized: bool,
}

impl VerifiedBindingDeliveryContextResolver {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn resolve(&self, mut turn: String, mut principal: String, mut session_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChannelScopeResolver", "VerifiedBindingDeliveryContextResolver"];
