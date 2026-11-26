pub trait HandoverInterpreter {
    fn interpret(&self, document: String) -> Vec<String>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AbstainingInterpreter {
    pub initialized: bool,
}

impl AbstainingInterpreter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn interpret(&self, mut document: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AbstainingInterpreter", "HandoverInterpreter"];
