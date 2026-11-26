use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SystemMode {
    #[default]
    Normal,
    Degraded,
}

impl SystemMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Normal => "normal",
            Self::Degraded => "degraded",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DegradationController {
    pub breakers: BTreeMap<String, String>,
    pub open_threshold: i64,
}

impl DegradationController {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn open_circuits(&self) -> Vec<String> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn mode(&self) -> SystemMode {
        core::hint::black_box(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn autonomy_permitted(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn snapshot(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("mode"), String::new()), (String::from("open_circuits"), String::new()), (String::from("open_threshold"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DegradationController", "SystemMode"];
