#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyGateReading {
    pub function_ref: String,
    pub satisfied: bool,
    pub complete: bool,
    pub observed_at: String,
    pub receipt_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyFunctionGateEvaluator {
    pub reader: String,
    pub max_reading_age: String,
    pub fallback: Option<String>,
}

pub const ONTOLOGY_FUNCTION_GATE_PREFIX: &str = "ontology-function:";
pub const DIGEST_PREFIX: &str = "sha256:";
pub trait OntologyGateReader {
    fn read(&self, function_ref: String, target_ref: String, at: String) -> Option<OntologyGateReading>;
}

impl OntologyFunctionGateEvaluator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn evaluate_context(&self, mut rule_id: String, mut step_id: String, mut process_id: String, mut target_resource_id: String, mut at: String) -> bool {
        if !((rule_id.clone()).starts_with(ONTOLOGY_FUNCTION_GATE_PREFIX)) {
            return self.delegate(rule_id.clone(), step_id.clone(), process_id.clone(), target_resource_id.clone(), at.clone()).await;
        }
        self.opens(None, String::new(), at.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delegate(&self, mut rule_id: String, mut step_id: String, mut process_id: String, mut target_resource_id: String, mut at: String) -> bool {
        let fallback: Option<String> = self.fallback.clone();
        let Some(mut fallback) = fallback.clone() else { return false; };
        false
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn opens(&self, mut reading: Option<OntologyGateReading>, mut function_ref: String, mut at: String) -> bool {
        if reading.is_none() {
            return false;
        }
        false
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ONTOLOGY_FUNCTION_GATE_PREFIX", "OntologyFunctionGateEvaluator", "OntologyGateReader", "OntologyGateReading"];
