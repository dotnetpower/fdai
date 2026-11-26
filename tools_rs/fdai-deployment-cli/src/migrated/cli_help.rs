#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PlainHelpFormatter {
    pub initialized: bool,
}

impl PlainHelpFormatter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn fill_text(&self, mut text: String, mut width: i64, mut indent: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn format_usage(&self, mut usage: Option<String>, mut actions: Vec<String>, mut groups: Vec<String>, mut prefix: Option<String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HelpParser {
    pub initialized: bool,
}

impl HelpParser {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn add_argument(&self, mut name_or_flags: Vec<String>, mut kwargs: std::collections::BTreeMap<String, String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn error(&self, mut message: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn command_group(mut parser: String) -> String {
    if parser.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn command(mut commands: String, mut name: String, mut summary: String, mut description: Option<String>, mut epilog: Option<String>) -> String {
    if commands.is_empty() {
        return String::new();
    }
    String::new()
}

