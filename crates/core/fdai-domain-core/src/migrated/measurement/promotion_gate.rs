#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShadowVerdictRecord {
    pub action_type_name: String,
    pub observed_at: String,
    pub was_policy_escape: bool,
    pub operator_reviewed: bool,
    pub operator_agreed: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromotionGateProgress {
    pub action_type_name: String,
    pub shadow_days_elapsed: f64,
    pub sample_count: i64,
    pub reviewed_count: i64,
    pub agreed_count: i64,
    pub policy_escapes: i64,
    pub accuracy: f64,
    pub ready: bool,
    pub gaps: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromotionGateEvaluator {
    pub now_fn: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InMemoryShadowVerdictSource {
    pub verdicts: Vec<ShadowVerdictRecord>,
}

pub trait ShadowVerdictSource {
    fn list_recent(&self, action_type_name: Option<String>, since: Option<String>) -> Vec<ShadowVerdictRecord>;
}

impl PromotionGateProgress {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_json(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("action_type_name"), self.action_type_name.clone()), (String::from("shadow_days_elapsed"), String::new()), (String::from("sample_count"), String::new()), (String::from("reviewed_count"), String::new()), (String::from("agreed_count"), String::new()), (String::from("policy_escapes"), String::new()), (String::from("accuracy"), String::new()), (String::from("ready"), String::new()), (String::from("gaps"), String::new())])
    }
}

impl PromotionGateEvaluator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluate(&self, mut action_type: String, mut verdicts: Vec<ShadowVerdictRecord>) -> PromotionGateProgress {
        let now: String = self.now().unwrap_or_else(|_| String::new());
        let mut gaps: Vec<String> = Vec::<String>::new();
        PromotionGateProgress { ready: (gaps.clone()).is_empty(), gaps: gaps.clone(), ..Default::default() }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluate_many(&self, mut action_types: Vec<String>, mut source: String, mut window_days: Option<i64>) -> Vec<PromotionGateProgress> {
        let mut since: Option<String> = None;
        let mut results: Vec<PromotionGateProgress> = Vec::<PromotionGateProgress>::new();
        for at in action_types.clone() {
            results.push(self.evaluate(at.clone(), Vec::new()));
        }
        results.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn now(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

impl InMemoryShadowVerdictSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn list_recent(&self, mut action_type_name: Option<String>, mut since: Option<String>) -> Vec<ShadowVerdictRecord> {
        for v in self.verdicts.clone() {
            if (action_type_name.is_some()) && ((v.action_type_name.clone()) != ((action_type_name.clone()).unwrap_or_default())) {
                continue;
            }
            if (since.is_some()) && ((v.observed_at.clone()) < ((since.clone()).unwrap_or_default())) {
                continue;
            }
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryShadowVerdictSource", "PromotionGateEvaluator", "PromotionGateProgress", "ShadowVerdictRecord", "ShadowVerdictSource"];
