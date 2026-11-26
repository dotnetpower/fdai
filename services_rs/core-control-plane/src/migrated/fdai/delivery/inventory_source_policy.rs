pub const MAX_POLICY_BYTES: i64 = 1048576;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CollectionSourceKind {
    #[default]
    Event,
    Delta,
    Snapshot,
    LiveRead,
}

impl CollectionSourceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Event => "event",
            Self::Delta => "delta",
            Self::Snapshot => "snapshot",
            Self::LiveRead => "live_read",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CollectionPriorityPolicy {
    pub base: i64,
    pub changed_boost: i64,
    pub stale_boost: i64,
    pub critical_boost: i64,
    pub operator_requested_boost: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceCollectionPolicy {
    pub source_id: String,
    pub source_kind: CollectionSourceKind,
    pub target_freshness_seconds: i64,
    pub max_staleness_seconds: i64,
    pub min_poll_interval_seconds: i64,
    pub max_poll_interval_seconds: i64,
    pub budget_window_seconds: i64,
    pub max_requests_per_window: i64,
    pub max_bytes_per_window: i64,
    pub global_concurrency_limit: i64,
    pub scope_concurrency_limit: i64,
    pub resource_type_concurrency_limit: i64,
    pub endpoint_concurrency_limit: i64,
    pub max_cursor_pages: i64,
    pub max_objects: i64,
    pub max_relationships: i64,
    pub max_run_seconds: i64,
    pub no_progress_timeout_seconds: i64,
    pub jitter_ratio: f64,
    pub backoff_base_seconds: i64,
    pub backoff_max_seconds: i64,
    pub circuit_failure_threshold: i64,
    pub circuit_probe_interval_seconds: i64,
    pub priority: Box<CollectionPriorityPolicy>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryCollectionPolicy {
    pub sources: Vec<SourceCollectionPolicy>,
}

pub const SOURCE_ID_PATTERN: &str = "[a-z][a-z0-9_.-]{0,127}";
impl CollectionPriorityPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>) -> CollectionPriorityPolicy {
        if value.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

impl SourceCollectionPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>) -> Result<SourceCollectionPolicy, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

impl InventoryCollectionPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>) -> Result<InventoryCollectionPolicy, &'static str> {
        let _ = require_exact_keys(value.clone(), std::collections::BTreeSet::from([String::from("schema_version"), String::from("sources")]), String::from("inventory collection policy")).unwrap_or_else(|_| ());
        let mut policies: Vec<SourceCollectionPolicy> = Vec::<SourceCollectionPolicy>::new();
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn source(&self, mut source_id: String) -> Result<SourceCollectionPolicy, &'static str> {
        for policy in self.sources.clone() {
            if (policy.source_id.clone()) == (source_id.clone()) {
                return Ok(policy.clone());
            }
        }
        Err("source_id")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_exact_keys(mut value: std::collections::BTreeMap<String, String>, mut expected: std::collections::BTreeSet<String>, mut subject: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_inventory_collection_policy(mut path: String) -> Result<InventoryCollectionPolicy, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["CollectionPriorityPolicy", "CollectionSourceKind", "InventoryCollectionPolicy", "SourceCollectionPolicy", "load_inventory_collection_policy"];
