#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LatencyClass {
    #[default]
    Fast,
    Standard,
    Slow,
}

impl LatencyClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Fast => "fast",
            Self::Standard => "standard",
            Self::Slow => "slow",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadToolSpec {
    pub tool_id: String,
    pub operation_class: String,
    pub timeout_seconds: f64,
    pub max_results: i64,
    pub max_output_bytes: i64,
    pub latency_class: LatencyClass,
    pub required_role: String,
    pub side_effect_class: String,
    pub query_template_owner: String,
}

impl ReadToolSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.tool_id.trim().is_empty() { return Err("tool_id must be non-empty"); }
        if self.operation_class.trim().is_empty() { return Err("operation_class must be non-empty"); }
        if self.required_role.trim().is_empty() { return Err("required_role must be non-empty"); }
        if self.side_effect_class.trim().is_empty() { return Err("side_effect_class must be non-empty"); }
        if self.query_template_owner.trim().is_empty() { return Err("query_template_owner must be non-empty"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn read_tool_spec(mut tool_id: String) -> ReadToolSpec {
    if tool_id.is_empty() {
        return Default::default();
    }
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["LatencyClass", "READ_TOOL_SPECS", "ReadToolSpec", "read_tool_spec"];
