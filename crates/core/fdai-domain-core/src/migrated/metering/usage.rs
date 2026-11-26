#[derive(Clone, Debug, Default, PartialEq)]
pub struct TokenUsage {
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
}

impl TokenUsage {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn total_tokens(&self) -> i64 {
        (self.prompt_tokens).saturating_add(self.completion_tokens)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn dunder_add(&self, mut other: TokenUsage) -> TokenUsage {
        TokenUsage { prompt_tokens: (self.prompt_tokens).saturating_add(other.prompt_tokens), completion_tokens: (self.completion_tokens).saturating_add(other.completion_tokens), ..Default::default() }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn zero() -> TokenUsage {
        core::hint::black_box(Default::default())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["TokenUsage"];
