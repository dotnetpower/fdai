#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeploymentDeadline {
    pub initialized: bool,
}

impl DeploymentDeadline {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn remaining(&self, mut maximum: Option<i64>) -> Result<i64, &'static str> {
        Ok(0_i64)
    }
}

