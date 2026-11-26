pub const MAX_RESPONSE_BYTES: i64 = 32768;

pub const ACTION_TYPE: &str = "remediate.subscription-tag-add";
pub const AUDIENCE: &str = "https://management.azure.com/.default";
pub const API_VERSION: &str = "2021-04-01";
pub trait TagEffectVerifier {
    fn expected(&self, action: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureSubscriptionTagEffectVerifier {
    pub initialized: bool,
}

impl AzureSubscriptionTagEffectVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn expected(&self, mut action: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn observe(&self, mut action: String, mut expected: String) -> Result<Option<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn arguments(mut action: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TagEffectVerifierRouter {
    pub initialized: bool,
}

impl TagEffectVerifierRouter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn expected(&self, mut action: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut action: String, mut expected: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureSubscriptionTagEffectVerifier", "TagEffectVerifierRouter"];
