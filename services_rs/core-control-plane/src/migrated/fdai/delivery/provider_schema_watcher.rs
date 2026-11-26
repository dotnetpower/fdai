#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProviderSchemaSourceKind {
    #[default]
    Primary,
    Mirror,
    Offline,
}

impl ProviderSchemaSourceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Primary => "primary",
            Self::Mirror => "mirror",
            Self::Offline => "offline",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProviderSchemaRefreshDisposition {
    #[default]
    NotDue,
    Unchanged,
    Compatible,
    Breaking,
    PolicyBlocked,
    Unavailable,
}

impl ProviderSchemaRefreshDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NotDue => "not_due",
            Self::Unchanged => "unchanged",
            Self::Compatible => "compatible",
            Self::Breaking => "breaking",
            Self::PolicyBlocked => "policy_blocked",
            Self::Unavailable => "unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderSchemaSourceBinding {
    pub name: String,
    pub kind: ProviderSchemaSourceKind,
    pub source: String,
    pub allowed: bool,
}

impl ProviderSchemaSourceBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        if self.source.trim().is_empty() { return Err("source must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderSchemaWatchPolicy {
    pub cadence_seconds: i64,
    pub failure_retry_seconds: i64,
    pub stale_after_seconds: i64,
    pub review_compatible_drift: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderSchemaRefreshReceipt {
    pub provider: String,
    pub disposition: ProviderSchemaRefreshDisposition,
    pub reason: String,
    pub checked_at: String,
    pub source_name: Option<String>,
    pub source_kind: Option<ProviderSchemaSourceKind>,
    pub source_revision: Option<String>,
    pub fallback_used: bool,
    pub baseline_digest: Option<String>,
    pub observed_digest: Option<String>,
    pub drift_digest: Option<String>,
    pub type_count: Option<i64>,
    pub modeled_count: Option<i64>,
    pub stale: bool,
    pub review_required: bool,
    pub review_package_digest: Option<String>,
    pub review_dispatched: bool,
    pub review_handoff_reason: Option<String>,
    pub grants_authority: bool,
}

impl ProviderSchemaRefreshReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.grants_authority { return Err("grants_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub trait ProviderSchemaSnapshotSource {
    fn collect(&self) -> String;
}

pub trait ProviderSchemaReviewPublisher {
    fn publish_provider_schema_drift(&self, package: std::collections::BTreeMap<String, String>) -> String;
}

impl ProviderSchemaRefreshReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("provider"), self.provider.clone()), (String::from("disposition"), String::new()), (String::from("reason"), self.reason.clone()), (String::from("checked_at"), self.checked_at.clone()), (String::from("source_name"), (self.source_name.clone()).unwrap_or_default()), (String::from("source_kind"), String::new()), (String::from("source_revision"), (self.source_revision.clone()).unwrap_or_default()), (String::from("fallback_used"), String::new()), (String::from("baseline_digest"), (self.baseline_digest.clone()).unwrap_or_default()), (String::from("observed_digest"), (self.observed_digest.clone()).unwrap_or_default()), (String::from("drift_digest"), (self.drift_digest.clone()).unwrap_or_default()), (String::from("type_count"), String::new()), (String::from("modeled_count"), String::new()), (String::from("stale"), String::new()), (String::from("review_required"), String::new()), (String::from("review_package_digest"), (self.review_package_digest.clone()).unwrap_or_default()), (String::from("review_dispatched"), String::new()), (String::from("review_handoff_reason"), (self.review_handoff_reason.clone()).unwrap_or_default()), (String::from("grants_authority"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProviderSchemaWatcher {
    pub initialized: bool,
}

impl ProviderSchemaWatcher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut now: String, mut force: bool) -> ProviderSchemaRefreshReceipt {
        let checked_at: String = aware_utc(now.clone()).unwrap_or_else(|_| String::new());
        if (!(force)) && (!(is_due(None, checked_at.clone(), Default::default()).unwrap_or_else(|_| false))) {
            let mut receipt: ProviderSchemaRefreshReceipt = self.receipt(Default::default(), String::from("schedule_not_due"), checked_at.clone(), None, None, None, None, false, None, None, false);
            return receipt.clone();
        }
        let mut observed: Option<String> = None;
        let mut selected: Option<ProviderSchemaSourceBinding> = None;
        if (observed.is_none()) || (selected.is_none()) {
            let mut receipt: ProviderSchemaRefreshReceipt = self.receipt(Default::default(), String::from("all_allowed_sources_unavailable"), checked_at.clone(), None, None, None, None, false, None, None, false);
            return receipt.clone();
        }
        let mut receipt: ProviderSchemaRefreshReceipt = self.receipt(Default::default(), String::new(), checked_at.clone(), None, None, observed.clone(), selected.clone(), false, None, None, false);
        receipt.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::too_many_arguments)]
    pub fn receipt(&self, mut disposition: ProviderSchemaRefreshDisposition, mut reason: String, mut checked_at: String, mut baseline: Option<String>, mut baseline_time: Option<String>, mut observed: Option<String>, mut selected: Option<ProviderSchemaSourceBinding>, mut fallback_used: bool, mut drift: Option<String>, mut coverage: Option<String>, mut review_required: bool) -> ProviderSchemaRefreshReceipt {
        ProviderSchemaRefreshReceipt { disposition: disposition.clone(), reason: reason.clone(), fallback_used: fallback_used, stale: is_stale(baseline_time.clone(), checked_at.clone(), Default::default()), review_required: review_required, ..Default::default() }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn is_due(mut last_run: Option<std::collections::BTreeMap<String, String>>, mut now: String, mut policy: ProviderSchemaWatchPolicy) -> Result<bool, &'static str> {
    let Some(mut last_run) = last_run.clone() else { return Ok(true); };
    let raw_checked_at: Option<String> = (last_run.clone()).get("checked_at").cloned();
    let raw_disposition: Option<String> = (last_run.clone()).get("disposition").cloned();
    if (!(true)) || (!(true)) {
        return Err("provider schema last-run receipt is invalid");
    }
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_stale(mut baseline_time: Option<String>, mut now: String, mut policy: ProviderSchemaWatchPolicy) -> bool {
    if baseline_time.is_none() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn review_package(mut snapshot: String, mut drift: String, mut coverage: String) -> std::collections::BTreeMap<String, String> {
    let mut status_counts: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::<String, i64>::new();
    std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("kind"), String::from("provider-schema-drift-review")), (String::from("provider"), String::new()), (String::from("source_revision"), String::new()), (String::from("baseline_digest"), String::new()), (String::from("observed_digest"), String::new()), (String::from("drift_digest"), String::new()), (String::from("drift_kind"), String::new()), (String::from("added_types"), String::new()), (String::from("removed_types"), String::new()), (String::from("added_stable_versions"), String::new()), (String::from("removed_stable_versions"), String::new()), (String::from("added_preview_versions"), String::new()), (String::from("removed_preview_versions"), String::new()), (String::from("type_count"), String::new()), (String::from("modeled_count"), String::new()), (String::from("coverage_status_counts"), String::new()), (String::from("review_required"), String::new()), (String::from("grants_authority"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn aware_utc(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProviderSchemaRefreshDisposition", "ProviderSchemaRefreshReceipt", "ProviderSchemaReviewPublisher", "ProviderSchemaSnapshotSource", "ProviderSchemaSourceBinding", "ProviderSchemaSourceKind", "ProviderSchemaWatchPolicy", "ProviderSchemaWatcher"];
