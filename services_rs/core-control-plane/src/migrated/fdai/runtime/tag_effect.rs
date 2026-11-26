pub trait TagEffectVerifier {
    fn expected(&self, action: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn build_default_tag_effect_bindings(mut environment: std::collections::BTreeMap<String, String>, mut governed_execution_enabled: bool, mut expected_effect_provider: Option<String>, mut effect_observer: Option<String>, mut execution_identities: Option<std::collections::BTreeMap<String, String>>, mut identity: Option<String>, mut http_client: Option<String>) -> (Option<String>, Option<String>) {
    if (!(governed_execution_enabled)) || ((expected_effect_provider.is_some()) || ((effect_observer.is_some()) || (http_client.is_none()))) {
        return (expected_effect_provider.clone(), effect_observer.clone());
    }
    let mut verifier: Option<String> = None;
    let gateway_url: String = ((environment.clone()).get("FDAI_DEV_OPERATIONS_GATEWAY_URL").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let gateway_audience: String = ((environment.clone()).get("FDAI_DEV_OPERATIONS_GATEWAY_AUDIENCE").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let subscription_id: String = ((environment.clone()).get("AZURE_SUBSCRIPTION_ID").cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let Some(mut verifier) = verifier.clone() else { return (None, None); };
    (None, None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["build_default_tag_effect_bindings"];
