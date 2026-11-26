#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum InvocationMode {
    #[default]
    Shadow,
    Enforce,
}

impl InvocationMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shadow => "shadow",
            Self::Enforce => "enforce",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum InvocationScope {
    #[default]
    ControlPlane,
    OperatorChat,
}

impl InvocationScope {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ControlPlane => "control_plane",
            Self::OperatorChat => "operator_chat",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum InvocationDisposition {
    #[default]
    Answered,
    Held,
    Clarification,
    Unavailable,
    Regenerated,
    Unknown,
}

impl InvocationDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Answered => "answered",
            Self::Held => "held",
            Self::Clarification => "clarification",
            Self::Unavailable => "unavailable",
            Self::Regenerated => "regenerated",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LlmInvocation {
    pub occurred_at: String,
    pub correlation_id: String,
    pub capability_id: String,
    pub model_key: String,
    pub tier: String,
    pub mode: InvocationMode,
    pub usage: String,
    pub usage_scope: InvocationScope,
    pub cost: Option<i64>,
    pub currency: Option<String>,
    pub cached_prompt_tokens: i64,
    pub duration_ms: i64,
    pub profile_digest: Option<String>,
    pub locale: String,
    pub turn_family: String,
    pub disposition: InvocationDisposition,
}

impl LlmInvocation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn day_bucket(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn month_bucket(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn utc(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InvocationDisposition", "InvocationMode", "InvocationScope", "LlmInvocation"];
