#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeterministicT2Proposer {
    pub initialized: bool,
}

impl DeterministicT2Proposer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn propose(&self, mut context: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AbstainingT2Proposer {
    pub initialized: bool,
}

impl AbstainingT2Proposer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn propose(&self, mut context: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AbstainingT2Proposer", "DeterministicT2Proposer"];
