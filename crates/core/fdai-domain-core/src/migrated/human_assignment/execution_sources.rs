use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessCaseSource {
    pub cases: String,
    pub role_group_ids: BTreeMap<String, String>,
    pub promotions: String,
    pub clock: String,
    pub check_inverse: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessCurrentPublisher {
    pub source: Box<HumanAccessCaseSource>,
    pub approvals: String,
    pub clock: String,
}

pub const CURRENT_PREFIX: &str = "human_assignment:execution-current:";
pub trait CurrentHumanAccessPromotion {
    fn refresh(&self, action_type: String);
    fn mode_of(&self, action_type: String) -> String;
}

impl HumanAccessCaseSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn check(&self, mut material: String) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

impl HumanAccessCurrentPublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut material: String) -> Result<String, &'static str> {
        let value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("revision"), String::new()), (String::from("evidence"), String::new())]);
        let audit: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("actor"), String::from("Var")), (String::from("action_kind"), String::from("human_access.current_sources.observed")), (String::from("material_digest"), String::new()), (String::from("revision"), String::new()), (String::from("mode"), String::from("shadow"))]);
        Ok(String::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CURRENT_PREFIX", "CurrentHumanAccessPromotion", "HumanAccessCaseSource", "HumanAccessCurrentPublisher"];
