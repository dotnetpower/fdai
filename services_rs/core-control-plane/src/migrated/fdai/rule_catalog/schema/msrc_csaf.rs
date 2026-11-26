pub const MAX_CSAF_BYTES: i64 = 2097152;
pub const MAX_VULNERABILITIES_PER_ADVISORY: i64 = 128;
pub const MAX_PRODUCTS_PER_ADVISORY: i64 = 256;
pub const MAX_REMEDIATIONS_PER_VULNERABILITY: i64 = 64;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CsafDisposition {
    #[default]
    ExistingRule,
    NewRuleCandidate,
    VersionObservation,
    ManualEvidence,
    ConditionalNotApplicable,
    AmbiguousOrBlocked,
}

impl CsafDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ExistingRule => "existing_rule",
            Self::NewRuleCandidate => "new_rule_candidate",
            Self::VersionObservation => "version_observation",
            Self::ManualEvidence => "manual_evidence",
            Self::ConditionalNotApplicable => "conditional_not_applicable",
            Self::AmbiguousOrBlocked => "ambiguous_or_blocked",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CsafThreatExploitStatus {
    #[default]
    Exploited,
    ExploitationMoreLikely,
    ExploitationLessLikely,
    ExploitationUnlikely,
    PubliclyDisclosed,
    Unproven,
}

impl CsafThreatExploitStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Exploited => "exploited",
            Self::ExploitationMoreLikely => "exploitation_more_likely",
            Self::ExploitationLessLikely => "exploitation_less_likely",
            Self::ExploitationUnlikely => "exploitation_unlikely",
            Self::PubliclyDisclosed => "publicly_disclosed",
            Self::Unproven => "unproven",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CsafRemediationCategory {
    #[default]
    VendorFix,
    Workaround,
    Mitigation,
    NoneAvailable,
}

impl CsafRemediationCategory {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::VendorFix => "vendor_fix",
            Self::Workaround => "workaround",
            Self::Mitigation => "mitigation",
            Self::NoneAvailable => "none_available",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CsafKevSlaTier {
    #[default]
    Immediate24h,
    Urgent72h,
    High14d,
    Standard30d,
    Monitor90d,
}

impl CsafKevSlaTier {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Immediate24h => "immediate_24h",
            Self::Urgent72h => "urgent_72h",
            Self::High14d => "high_14d",
            Self::Standard30d => "standard_30d",
            Self::Monitor90d => "monitor_90d",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafAttackVectorProfile {
    pub is_network_reachable: bool,
    pub is_unauthenticated: bool,
    pub is_zero_click: bool,
    pub is_scope_changed: bool,
    pub is_high_cia_impact: bool,
    pub is_wormable_candidate: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafProductBranch {
    pub product_id: String,
    pub name: String,
    pub cpe: Option<String>,
}

impl CsafProductBranch {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.product_id.trim().is_empty() { return Err("product_id must be non-empty"); }
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafRemediationRecord {
    pub category: CsafRemediationCategory,
    pub product_ids: Vec<String>,
    pub details: String,
    pub fixed_version: Option<String>,
    pub kb_article: Option<String>,
    pub workaround_property: Option<String>,
    pub workaround_expected_value: Option<String>,
    pub recommended_action_type: Option<String>,
    pub url: Option<String>,
}

impl CsafRemediationRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.details.trim().is_empty() { return Err("details must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafVulnerabilityRecord {
    pub cve_id: String,
    pub title: String,
    pub cvss_base_score: f64,
    pub cvss_temporal_score: Option<f64>,
    pub cvss_vector: String,
    pub severity: String,
    pub exploit_status: CsafThreatExploitStatus,
    pub publicly_disclosed: bool,
    pub known_affected_product_ids: Vec<String>,
    pub fixed_product_ids: Vec<String>,
    pub known_not_affected_product_ids: Vec<String>,
    pub remediations: Vec<CsafRemediationRecord>,
}

impl CsafVulnerabilityRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.cve_id.trim().is_empty() { return Err("cve_id must be non-empty"); }
        if self.title.trim().is_empty() { return Err("title must be non-empty"); }
        if self.cvss_vector.trim().is_empty() { return Err("cvss_vector must be non-empty"); }
        if self.severity.trim().is_empty() { return Err("severity must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafAdvisoryDocument {
    pub csaf_version: String,
    pub tracking_id: String,
    pub title: String,
    pub initial_release_date: String,
    pub current_release_date: String,
    pub revision_count: i64,
    pub source_url: String,
    pub document_digest: String,
    pub signature_verified: bool,
    pub products: Vec<CsafProductBranch>,
    pub vulnerabilities: Vec<CsafVulnerabilityRecord>,
}

impl CsafAdvisoryDocument {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.csaf_version.trim().is_empty() { return Err("csaf_version must be non-empty"); }
        if self.tracking_id.trim().is_empty() { return Err("tracking_id must be non-empty"); }
        if self.title.trim().is_empty() { return Err("title must be non-empty"); }
        if self.initial_release_date.trim().is_empty() { return Err("initial_release_date must be non-empty"); }
        if self.current_release_date.trim().is_empty() { return Err("current_release_date must be non-empty"); }
        if self.source_url.trim().is_empty() { return Err("source_url must be non-empty"); }
        if self.document_digest.trim().is_empty() { return Err("document_digest must be non-empty"); }
        if !(1_i64..=1000_i64).contains(&self.revision_count) { return Err("revision_count out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafProductCrosswalk {
    pub product_id: String,
    pub product_name: String,
    pub disposition: String,
    pub canonical_resource_type: Option<String>,
    pub canonical_resource_types: Vec<String>,
    pub provider_resource_types: Vec<String>,
    pub version_property: Option<String>,
    pub minimum_affected_version_inclusive: Option<String>,
    pub vulnerable_version_ceiling_exclusive: Option<String>,
    pub freshness_ceiling_seconds: i64,
    pub reviewer: String,
}

impl CsafProductCrosswalk {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.product_id.trim().is_empty() { return Err("product_id must be non-empty"); }
        if self.product_name.trim().is_empty() { return Err("product_name must be non-empty"); }
        if self.disposition.trim().is_empty() { return Err("disposition must be non-empty"); }
        if self.reviewer.trim().is_empty() { return Err("reviewer must be non-empty"); }
        if !(60_i64..=31536000_i64).contains(&self.freshness_ceiling_seconds) { return Err("freshness_ceiling_seconds out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CsafVulnerabilityCrosswalk {
    pub cve_id: String,
    pub advisory_tracking_id: String,
    pub disposition: CsafDisposition,
    pub mapping_state: String,
    pub product_ids: Vec<String>,
    pub existing_rule_id: Option<String>,
    pub candidate_action_type: Option<String>,
    pub workaround_property: Option<String>,
    pub workaround_expected_value: Option<String>,
    pub blocked_reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MsrcCsafCrosswalkCatalog {
    pub schema_version: String,
    pub source_id: String,
    pub source_revision: String,
    pub advisories_digest: String,
    pub crosswalk_digest: String,
    pub product_mappings: Vec<CsafProductCrosswalk>,
    pub vulnerability_mappings: Vec<CsafVulnerabilityCrosswalk>,
    pub advisories: Vec<CsafAdvisoryDocument>,
}

pub const SHA256: &str = "^sha256:[a-f0-9]{64}$";
pub const CVE_ID: &str = "^(?:CVE-[0-9]{4}-[0-9]{4,7}|ADV[0-9]{6})$";
pub const TRACKING_ID: &str = "^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$";
pub const PRODUCT_ID: &str = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$";
pub const IDENTIFIER: &str = "^[a-z0-9][a-z0-9._:-]{0,255}$";
pub const KB_ARTICLE: &str = "^KB[0-9]{6,9}$";
pub const CVSS_V3_VECTOR: &str = "^CVSS:3\\.[01](/[A-Z]+:[A-Za-z0-9.]+)+$";
pub const MSRC_HTTPS_PREFIX: &str = "https://msrc.microsoft.com/";
pub const DOTTED_VERSION_RE: &str = "^(?:0|[1-9][0-9]{0,8})(?:\\.(?:0|[1-9][0-9]{0,8})){1,7}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CsafSchemaError {
    pub message: String,
}

impl CsafSchemaError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CsafSchemaError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CsafSchemaError {}

impl CsafProductBranch {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_product_branch(&self) -> Result<CsafProductBranch, &'static str> {
        Err("runtime_binding_required")
    }
}

impl CsafRemediationRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_remediation(&self) -> Result<CsafRemediationRecord, &'static str> {
        if (((self.details.clone()).trim().to_string()).is_empty()) || (has_forbidden_text_chars(self.details.clone())) {
            return Err("CSAF remediation details MUST NOT be blank or contain controlbidi chars");
        }
        if self.fixed_version.is_some() {
            let _ = parse_dotted_version((self.fixed_version.clone()).unwrap_or_default()).unwrap_or_else(|_| Vec::new());
        }
        if self.url.is_some() {
            let _ = validate_https_url((self.url.clone()).unwrap_or_default(), std::collections::BTreeSet::new(), String::from("CSAF remediation url"), true).unwrap_or_else(|_| ());
        }
        Ok(self.clone())
    }
}

impl CsafVulnerabilityRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_vulnerability(&self) -> Result<CsafVulnerabilityRecord, &'static str> {
        if (self.known_affected_product_ids.clone()).is_empty() {
            return Err("CSAF vulnerability requires at least one known_affected product_id");
        }
        if (((self.title.clone()).trim().to_string()).is_empty()) || (has_forbidden_text_chars(self.title.clone())) {
            return Err("CSAF vulnerability title MUST NOT be blank or contain controlbidi chars");
        }
        if (((self.remediations.clone()).len() as i64)) > (MAX_REMEDIATIONS_PER_VULNERABILITY) {
            return Err("CSAF vulnerability remediations exceed maximum bound");
        }
        let score_severity: String = severity_for_cvss_score(self.cvss_base_score).unwrap_or_else(|_| String::new());
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn attack_profile(&self) -> CsafAttackVectorProfile {
        parse_cvss_v3_vector_profile(self.cvss_vector.clone()).unwrap_or_else(|_| Default::default())
    }
}

impl CsafAdvisoryDocument {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_tz(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_advisory(&self) -> Result<CsafAdvisoryDocument, &'static str> {
        if (((self.title.clone()).trim().to_string()).is_empty()) || (has_forbidden_text_chars(self.title.clone())) {
            return Err("CSAF advisory title MUST NOT be blank or contain controlbidi chars");
        }
        let _ = validate_https_url(self.source_url.clone(), std::collections::BTreeSet::from([String::from("msrc.microsoft.com")]), String::from("CSAF source_url"), false).unwrap_or_else(|_| ());
        if !(self.signature_verified) {
            return Err("CSAF advisory MUST have signature_verifiedTrue before admission");
        }
        if (self.current_release_date.clone()) < (self.initial_release_date.clone()) {
            return Err("current_release_date MUST NOT precede initial_release_date");
        }
        if ((self.products.clone()).is_empty()) || ((((self.products.clone()).len() as i64)) > (MAX_PRODUCTS_PER_ADVISORY)) {
            return Err("CSAF advisory products MUST be non-empty and bounded");
        }
        if ((self.vulnerabilities.clone()).is_empty()) || ((((self.vulnerabilities.clone()).len() as i64)) > (MAX_VULNERABILITIES_PER_ADVISORY)) {
            return Err("CSAF advisory vulnerabilities MUST be non-empty and bounded");
        }
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_multi_revision(&self) -> bool {
        (self.revision_count) > (1_i64)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn release_latency_days(&self) -> i64 {
        0_i64
    }
}

impl CsafProductCrosswalk {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_product_crosswalk(&self) -> Result<CsafProductCrosswalk, &'static str> {
        if (((self.product_name.clone()).trim().to_string()).is_empty()) || (has_forbidden_text_chars(self.product_name.clone())) {
            return Err("CSAF product_name MUST NOT be blank or contain controlbidi chars");
        }
        Ok(self.clone())
    }
}

impl CsafVulnerabilityCrosswalk {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_vulnerability_crosswalk(&self) -> Result<CsafVulnerabilityCrosswalk, &'static str> {
        if (self.workaround_property.is_none()) != (self.workaround_expected_value.is_none()) {
            return Err("workaround_property and workaround_expected_value MUST be supplied toget");
        }
        Ok(self.clone())
    }
}

impl MsrcCsafCrosswalkCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_catalog(&self) -> Result<MsrcCsafCrosswalkCatalog, &'static str> {
        let mut advisory_cves: std::collections::BTreeMap<String, (String, CsafVulnerabilityRecord)> = std::collections::BTreeMap::<String, (String, CsafVulnerabilityRecord)>::new();
        for advisory in self.advisories.clone() {
            for vuln in advisory.vulnerabilities.clone() {
                if (advisory_cves.clone()).contains_key((vuln.cve_id.clone()).as_str()) {
                    return Err("duplicate CVE vuln.cve_id across advisories");
                }
                advisory_cves.insert(vuln.cve_id.clone(), (advisory.tracking_id.clone(), vuln.clone()));
            }
        }
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn get_vulnerability_crosswalk(&self, mut cve_id: String) -> Option<CsafVulnerabilityCrosswalk> {
        if cve_id.is_empty() {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn summary_counts(&self) -> std::collections::BTreeMap<String, i64> {
        std::collections::BTreeMap::from([(String::from("advisories"), ((self.advisories.clone()).len() as i64)), (String::from("product_mappings"), ((self.product_mappings.clone()).len() as i64)), (String::from("vulnerability_mappings"), ((self.vulnerability_mappings.clone()).len() as i64)), (String::from("exploited"), 0_i64)])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_forbidden_text_chars(mut text: String) -> bool {
    if text.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_https_url(mut url: String, mut allowed_hosts: std::collections::BTreeSet<String>, mut field_name: String, mut allow_query: bool) -> Result<(), &'static str> {
    if url.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reject_duplicate_keys(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reject_nonfinite_constant(mut token: String) -> Result<String, &'static str> {
    Err("non-finite JSON constant tokenr is not permitted")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_dotted_version(mut raw: String) -> Result<Vec<i64>, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn pad_version(mut version: Vec<i64>, mut length: i64) -> Vec<i64> {
    if version.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn compare_dotted_versions(mut left: String, mut right: String) -> i64 {
    0_i64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn version_train_prefix(mut minimum_inclusive: String, mut ceiling_exclusive: String) -> Vec<i64> {
    let mut shared: Vec<i64> = Vec::<i64>::new();
    shared.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn is_version_in_affected_window(mut observed_version: String, mut minimum_inclusive: String, mut ceiling_exclusive: String) -> Result<bool, &'static str> {
    if (compare_dotted_versions(minimum_inclusive.clone(), ceiling_exclusive.clone())) >= (0_i64) {
        return Err("affected version window requires minimum_inclusive  ceiling_exclusive");
    }
    Ok(((compare_dotted_versions(observed_version.clone(), minimum_inclusive.clone())) >= (0_i64)) && ((compare_dotted_versions(observed_version.clone(), ceiling_exclusive.clone())) < (0_i64)))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn severity_for_cvss_score(mut score: f64) -> Result<String, &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn parse_cvss_v3_vector_profile(mut vector: String) -> Result<CsafAttackVectorProfile, &'static str> {
    Ok(CsafAttackVectorProfile::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn classify_kev_sla_tier(mut severity: String, mut exploit_status: CsafThreatExploitStatus, mut cvss_vector: String) -> (CsafKevSlaTier, i64) {
    let profile: CsafAttackVectorProfile = parse_cvss_v3_vector_profile(cvss_vector.clone()).unwrap_or_else(|_| Default::default());
    (Default::default(), 0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_msrc_csaf_raw_dict(mut path: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut seen_paths: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_msrc_csaf_crosswalk_catalog(mut path: String) -> MsrcCsafCrosswalkCatalog {
    if path.is_empty() {
        return Default::default();
    }
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CsafAdvisoryDocument", "CsafAttackVectorProfile", "CsafDisposition", "CsafKevSlaTier", "CsafProductBranch", "CsafProductCrosswalk", "CsafRemediationCategory", "CsafRemediationRecord", "CsafSchemaError", "CsafThreatExploitStatus", "CsafVulnerabilityCrosswalk", "CsafVulnerabilityRecord", "MsrcCsafCrosswalkCatalog", "StrictScalar", "classify_kev_sla_tier", "compare_dotted_versions", "is_version_in_affected_window", "load_msrc_csaf_crosswalk_catalog", "load_msrc_csaf_raw_dict", "parse_cvss_v3_vector_profile", "parse_dotted_version", "severity_for_cvss_score", "version_train_prefix"];
