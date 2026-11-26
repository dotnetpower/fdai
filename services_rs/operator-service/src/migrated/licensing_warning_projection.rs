#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LicensingWarningState {
    #[default]
    Normal,
    ExpiringSoon,
    Expired,
    ClockRegression,
    ReadOnlyTrial,
}

impl LicensingWarningState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Normal => "normal",
            Self::ExpiringSoon => "expiring_soon",
            Self::Expired => "expired",
            Self::ClockRegression => "clock_regression",
            Self::ReadOnlyTrial => "read_only_trial",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LicensingWarningProjection {
    pub r#type: String,
    pub schema_version: String,
    pub read_only: bool,
    pub authority: String,
    pub secret_free: bool,
    pub principal_id: String,
    pub state: LicensingWarningState,
    pub license_status: String,
    pub watermark_notice: String,
    pub acting_available: bool,
    pub proactive_warning: bool,
    pub license_id: Option<String>,
    pub expires_at: Option<String>,
    pub remaining_seconds: Option<i64>,
    pub remaining_days: Option<i64>,
    pub observed_at: String,
    pub reason_code: String,
    pub projection_digest: String,
}

impl LicensingWarningProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.r#type.as_str(), "licensing.warning-projection") { return Err("invalid type literal"); }
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !self.read_only { return Err("read_only violated literal bool invariant"); }
        if !matches!(self.authority.as_str(), "none") { return Err("invalid authority literal"); }
        if !self.secret_free { return Err("secret_free violated literal bool invariant"); }
        if !matches!(self.watermark_notice.as_str(), "none" | "evaluation-ended" | "not-activated") { return Err("invalid watermark_notice literal"); }
        Ok(())
    }
}

pub const SAFE_IDENTIFIER: &str = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$";
impl LicensingWarningProjection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn validate_timezone(mut value: Option<String>) -> Result<Option<String>, &'static str> {
        let Some(mut value) = value.clone() else { return Ok(None); };
        Ok(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn reject_secret_like_strings(mut value: Option<String>) -> Result<Option<String>, &'static str> {
        let Some(mut value) = value.clone() else { return Ok(None); };
        Ok(Some(value.clone()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_invariants(&self) -> Result<LicensingWarningProjection, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_json(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_licensing_warning_projection(mut principal_id: Option<String>, mut license_status: String, mut acting_available: bool, mut observed_at: Option<String>, mut now: Option<String>, mut license_id: Option<String>, mut expires_at: Option<String>, mut clock_blocked: bool, mut reason_code: Option<String>, mut warning_window: String, mut raw_metadata: Option<std::collections::BTreeMap<String, String>>) -> Result<LicensingWarningProjection, &'static str> {
    if (principal_id.is_none()) || ((((principal_id.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("licensing warning projection requires an authenticated principal");
    }
    if let Some(mut raw_metadata) = raw_metadata.clone() {
        let _ = validate_raw_metadata(String::new()).unwrap_or_else(|_| ());
    }
    let safe_license_id: Option<String> = sanitize_identifier(license_id.clone()).unwrap_or_else(|_| None);
    if (clock_blocked) || (((license_status.clone()) == (String::from("clock_regression"))) || ((reason_code.clone()) == Some(String::from("clock_regression")))) {
        return Ok(LicensingWarningProjection { principal_id: ((principal_id.clone()).unwrap_or_default()).trim().to_string(), license_status: String::from("clock_regression"), watermark_notice: String::from("not-activated"), acting_available: false, proactive_warning: true, license_id: safe_license_id.clone(), reason_code: String::from("clock_regression_detected"), ..Default::default() });
    }
    if (!(acting_available)) || (!(matches!(license_status.as_str(), "active" | "issuer-workstation"))) {
        return Ok(LicensingWarningProjection { principal_id: ((principal_id.clone()).unwrap_or_default()).trim().to_string(), license_status: (sanitize_identifier(Some(license_status.clone())).unwrap_or_else(|_| None)).unwrap_or_else(|| String::from("absent")), watermark_notice: String::from("not-activated"), acting_available: false, proactive_warning: true, license_id: safe_license_id.clone(), remaining_seconds: None, remaining_days: None, reason_code: (sanitize_identifier(reason_code.clone()).unwrap_or_else(|_| None)).unwrap_or_else(|| String::from("read_only_unactivated")), ..Default::default() });
    }
    let mut rem_seconds: Option<i64> = None;
    let mut rem_days: Option<i64> = None;
    Ok(LicensingWarningProjection { principal_id: ((principal_id.clone()).unwrap_or_default()).trim().to_string(), license_status: (sanitize_identifier(Some(license_status.clone())).unwrap_or_else(|_| None)).unwrap_or_else(|| String::from("active")), watermark_notice: String::from("none"), acting_available: true, proactive_warning: false, license_id: safe_license_id.clone(), remaining_seconds: rem_seconds.clone(), remaining_days: rem_days.clone(), reason_code: (sanitize_identifier(reason_code.clone()).unwrap_or_else(|_| None)).unwrap_or_else(|| String::from("entitlement_active")), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_raw_metadata(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn sanitize_identifier(mut value: Option<String>) -> Result<Option<String>, &'static str> {
    if (value.is_none()) || ((((value.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Ok(None);
    }
    let cleaned: String = ((value.clone()).unwrap_or_default()).trim().to_string();
    Ok(Some(cleaned.clone()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["DEFAULT_RENEWAL_WARNING_WINDOW", "LicensingWarningProjection", "LicensingWarningState", "MAX_OBSERVATION_STALENESS", "build_licensing_warning_projection"];
