pub trait AutomationBlueprintEvidenceFeed {
    fn completed_turns(&self) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AutomationBlueprintSuggestionService {
    pub initialized: bool,
}

impl AutomationBlueprintSuggestionService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn suggest(&self, mut now: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AutomationBlueprintEvidenceFeed", "AutomationBlueprintSuggestionService"];
