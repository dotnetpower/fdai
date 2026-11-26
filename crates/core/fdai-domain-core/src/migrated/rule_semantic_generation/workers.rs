pub trait RuleGenerationBuildHandler {
    fn handle(&self, request: String) -> String;
}

pub trait RuleGenerationValidationHandler {
    fn handle(&self, build_result: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleGenerationBuildHandler", "RuleGenerationValidationHandler"];
