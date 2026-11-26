use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DeliveryMode {
    #[default]
    Failover,
    Fanout,
}

impl DeliveryMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Failover => "failover",
            Self::Fanout => "fanout",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OnAllFailAction {
    #[default]
    HilEscalate,
    QueueAndPageOps,
}

impl OnAllFailAction {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::HilEscalate => "hil_escalate",
            Self::QueueAndPageOps => "queue_and_page_ops",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RouteSpec {
    pub category: String,
    pub trust_tier: String,
    pub delivery_mode: DeliveryMode,
    pub primary: String,
    pub fallback: Vec<String>,
    pub channels: Vec<String>,
    pub on_all_fail: OnAllFailAction,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NotificationMatrix {
    pub version: i64,
    pub routes: BTreeMap<String, RouteSpec>,
    pub default_route: String,
    pub channel_locales: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MatrixValidationError {
    pub message: String,
}

impl MatrixValidationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for MatrixValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for MatrixValidationError {}

impl RouteSpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn channel_ids(&self) -> Vec<String> {
        core::hint::black_box(Vec::new())
    }
}

impl NotificationMatrix {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolve(&self, mut category: String) -> RouteSpec {
        if category.is_empty() {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn locale_for(&self, mut channel_id: String) -> String {
        if channel_id.is_empty() {
            return String::new();
        }
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_matrix_from_yaml(mut path: String) -> Result<NotificationMatrix, &'static str> {
    Ok(load_matrix_from_mapping(std::collections::BTreeMap::new()).unwrap_or_else(|_| Default::default()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_matrix_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<NotificationMatrix, &'static str> {
    let matrix_raw: Option<String> = (raw.clone()).get("matrix").cloned();
    if !(true) {
        return Err("top-level matrix key is required and MUST be a mapping");
    }
    let mut routes: std::collections::BTreeMap<String, RouteSpec> = std::collections::BTreeMap::<String, RouteSpec>::new();
    let channel_locales: std::collections::BTreeMap<String, String> = parse_channel_locales(String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(NotificationMatrix::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_channel_locales(mut raw: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (raw.clone()).is_empty() {
        return Ok(std::collections::BTreeMap::<String, String>::new());
    }
    if !(false) {
        return Err("matrix.channels MUST be a mapping when present");
    }
    let mut locales: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(locales.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn parse_route(mut name: String, mut raw: std::collections::BTreeMap<String, String>) -> Result<RouteSpec, &'static str> {
    let allowed_keys: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("trust_tier"), String::from("delivery_mode"), String::from("primary"), String::from("fallback"), String::from("channels"), String::from("on_all_fail")]);
    let trust_tier_raw: Option<String> = (raw.clone()).get("trust_tier").cloned();
    if !(true) {
        return Err("route namer: trust_tier MUST be a string");
    }
    let mut primary: String = String::from("");
    Ok(RouteSpec { category: name.clone(), primary: primary.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn channel_id_list(mut route_name: String, mut field_name: String, mut raw: String, mut required: bool) -> Result<Vec<String>, &'static str> {
    if (!(false)) || ((required) && ((raw.clone()).is_empty())) {
        let qualifier: String = if required { String::from("non-empty ") } else { String::from("") };
        return Err("route route_namer: field_name MUST be a qualifierlist");
    }
    let mut values: Vec<String> = Vec::<String>::new();
    Ok(values.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["DeliveryMode", "MatrixValidationError", "NotificationMatrix", "OnAllFailAction", "RouteSpec", "load_matrix_from_mapping", "load_matrix_from_yaml"];
