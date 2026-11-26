pub const NOOP_REASON: &str = "no_op_provider";
pub trait WebSearchProvider {
    fn search(&self, query: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoOpWebSearchProvider {
    pub initialized: bool,
}

impl NoOpWebSearchProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn search(&self, mut query: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["NoOpWebSearchProvider", "WebSearchProvider"];
