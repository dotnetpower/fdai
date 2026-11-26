#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NornsDeploymentLearning {
    pub initialized: bool,
}

impl NornsDeploymentLearning {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn observe_incident_symptom(&self, mut incident_id: String, mut signal: String, mut target_type: String, mut severity: String) -> Vec<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn observe_preflight_manual_blocker(&self, mut finding_id: String, mut category: String, mut evidence_source: String, mut scope: String) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
        let values: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("finding_id"), finding_id.clone()), (String::from("category"), category.clone()), (String::from("evidence_source"), evidence_source.clone()), (String::from("scope"), scope.clone())]);
        for (name, value) in values.clone() {
            if ((value.clone()).is_empty()) || (((((value.clone()).len() as i64)) > (512_i64)) || (((value.clone()).contains("\n")) || ((value.clone()).contains("\r")))) {
                return Err("preflight manual blocker name is invalid");
            }
        }
        Ok(Some(std::collections::BTreeMap::from([(String::from("source_signal"), String::from("recurring_preflight_manual_blocker")), (String::from("evidence"), String::new()), (String::from("provenance"), String::new()), (String::from("proposed_by"), String::from("Norns")), (String::from("proposal_kind"), String::from("new")), (String::from("candidate_type"), String::from("preflight-toggle-gap")), (String::from("target_rule_id"), String::new()), (String::from("suggested_pattern"), String::from("add_reviewed_preflight_alternate_rendering"))])))
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["NornsDeploymentLearning"];
