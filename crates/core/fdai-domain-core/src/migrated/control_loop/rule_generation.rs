#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RuleGenerationBarrier {
    pub initialized: bool,
}

impl RuleGenerationBarrier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read(&mut self) -> Vec<()> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn write(&mut self) -> Vec<()> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleGenerationBarrier"];
