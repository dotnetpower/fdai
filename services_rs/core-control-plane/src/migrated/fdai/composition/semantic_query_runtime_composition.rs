#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticQueryRuntimeComposition {
    pub runtime: Option<String>,
    pub unavailable_reason: Option<String>,
    pub model_auth_audiences: Vec<String>,
    pub current_evidence_probe: Option<String>,
}

