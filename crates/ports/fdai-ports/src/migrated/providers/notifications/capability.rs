#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChannelMode {
    #[default]
    Shadow,
    Enforce,
}

impl ChannelMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shadow => "shadow",
            Self::Enforce => "enforce",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelCapabilityState {
    pub channel_id: String,
    pub available: bool,
    pub enabled: bool,
    pub configured: bool,
    pub mode: ChannelMode,
}

impl ChannelCapabilityState {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn ready(&self) -> bool {
        (self.available) && ((self.enabled) && (self.configured))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_readiness_row(&self, mut source: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("key"), self.channel_id.clone()), (String::from("source"), source.clone()), (String::from("observed"), String::new()), (String::from("configured"), String::new()), (String::from("ready"), String::new()), (String::from("mode"), String::new()), (String::from("reason"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn unready_reason(mut state: ChannelCapabilityState) -> String {
    if !(state.available) {
        return String::from("prerequisites are incomplete");
    }
    if !(state.enabled) {
        return String::from("disabled by operator");
    }
    if !(state.configured) {
        return String::from("configuration is invalid");
    }
    String::from("not ready")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChannelCapabilityState", "ChannelMode"];
