use std::collections::BTreeMap;
pub const MAX_TEMPLATE_BYTES: i64 = 64000;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SeverityBand {
    #[default]
    Critical,
    High,
    Medium,
    Low,
}

impl SeverityBand {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Critical => "critical",
            Self::High => "high",
            Self::Medium => "medium",
            Self::Low => "low",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Impact {
    #[default]
    CodeExecution,
    PrivilegeEscalation,
    DataWrite,
    DataRead,
    DenialOfService,
    InfoDisclosure,
    Limited,
}

impl Impact {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::CodeExecution => "code_execution",
            Self::PrivilegeEscalation => "privilege_escalation",
            Self::DataWrite => "data_write",
            Self::DataRead => "data_read",
            Self::DenialOfService => "denial_of_service",
            Self::InfoDisclosure => "info_disclosure",
            Self::Limited => "limited",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AttackVector {
    #[default]
    Network,
    Adjacent,
    Local,
    Physical,
}

impl AttackVector {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Network => "network",
            Self::Adjacent => "adjacent",
            Self::Local => "local",
            Self::Physical => "physical",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AttackComplexity {
    #[default]
    Low,
    High,
}

impl AttackComplexity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Low => "low",
            Self::High => "high",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PrivilegesRequired {
    #[default]
    None,
    Low,
    High,
}

impl PrivilegesRequired {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Low => "low",
            Self::High => "high",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum UserInteraction {
    #[default]
    None,
    Required,
}

impl UserInteraction {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Required => "required",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FixClass {
    #[default]
    DependencyBump,
    LocalCodeFix,
    ConfigChange,
    SecretRemoval,
    DesignChange,
}

impl FixClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::DependencyBump => "dependency_bump",
            Self::LocalCodeFix => "local_code_fix",
            Self::ConfigChange => "config_change",
            Self::SecretRemoval => "secret_removal",
            Self::DesignChange => "design_change",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AutofixEligibility {
    #[default]
    Auto,
    Assisted,
    Manual,
}

impl AutofixEligibility {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Assisted => "assisted",
            Self::Manual => "manual",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RemediationDepth {
    #[default]
    D0,
    D1,
    D2,
    D3,
    PlanOnly,
}

impl RemediationDepth {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::D0 => "D0",
            Self::D1 => "D1",
            Self::D2 => "D2",
            Self::D3 => "D3",
            Self::PlanOnly => "plan_only",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Confidence {
    #[default]
    Hypothesis,
    Reported,
    Corroborated,
    Verified,
    Proven,
}

impl Confidence {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Hypothesis => "hypothesis",
            Self::Reported => "reported",
            Self::Corroborated => "corroborated",
            Self::Verified => "verified",
            Self::Proven => "proven",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Exposure {
    #[default]
    Exposed,
    Internal,
    NotDeployed,
    Unknown,
}

impl Exposure {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Exposed => "exposed",
            Self::Internal => "internal",
            Self::NotDeployed => "not_deployed",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Priority {
    #[default]
    P0,
    P1,
    P2,
    P3,
    P4,
}

impl Priority {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::P0 => "P0",
            Self::P1 => "P1",
            Self::P2 => "P2",
            Self::P3 => "P3",
            Self::P4 => "P4",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WeaknessClass {
    pub title: String,
    pub cwe: Vec<i64>,
    pub impact_range: Vec<Impact>,
    pub fix_class: FixClass,
    pub autofix_eligibility: AutofixEligibility,
    pub max_depth: RemediationDepth,
    pub guidance: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WeaknessClassCatalog {
    pub schema_version: i64,
    pub catalog_id: String,
    pub version: String,
    pub classes: BTreeMap<String, WeaknessClass>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BandThreshold {
    pub band: SeverityBand,
    pub min_points: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScoreThreshold {
    pub band: SeverityBand,
    pub min_score: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SeverityRubric {
    pub schema_version: i64,
    pub rubric_id: String,
    pub version: String,
    pub bands: Vec<BandThreshold>,
    pub advisory_score_bands: Vec<ScoreThreshold>,
    pub impact_points: BTreeMap<Impact, f64>,
    pub attack_vector_penalty: BTreeMap<AttackVector, f64>,
    pub attack_complexity_penalty: BTreeMap<AttackComplexity, f64>,
    pub privileges_required_penalty: BTreeMap<PrivilegesRequired, f64>,
    pub user_interaction_penalty: BTreeMap<UserInteraction, f64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PriorityCondition {
    pub kev: Option<bool>,
    #[allow(clippy::type_complexity)]
    pub exposure_in: Option<Vec<Exposure>>,
    pub floor_at_least: Option<SeverityBand>,
    pub ceiling_at_least: Option<SeverityBand>,
    pub confidence_at_least: Option<Confidence>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PriorityRule {
    pub id: String,
    pub when: Box<PriorityCondition>,
    pub priority: Priority,
    pub due_days: i64,
}

impl PriorityRule {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=365_i64).contains(&self.due_days) { return Err("due_days out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PriorityDefault {
    pub priority: Priority,
    pub due_days: i64,
}

impl PriorityDefault {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=365_i64).contains(&self.due_days) { return Err("due_days out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PriorityPolicy {
    pub schema_version: i64,
    pub policy_id: String,
    pub version: String,
    pub rules: Vec<PriorityRule>,
    pub default: Box<PriorityDefault>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PackLimits {
    pub max_issues: i64,
    pub max_groups: i64,
    pub expiry_days: i64,
    pub max_groups_per_session: i64,
    pub max_fix_attempts: i64,
    pub max_diff_bytes: i64,
}

impl PackLimits {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=500_i64).contains(&self.max_issues) { return Err("max_issues out of bounds"); }
        if !(1_i64..=200_i64).contains(&self.max_groups) { return Err("max_groups out of bounds"); }
        if !(1_i64..=90_i64).contains(&self.expiry_days) { return Err("expiry_days out of bounds"); }
        if !(1_i64..=50_i64).contains(&self.max_groups_per_session) { return Err("max_groups_per_session out of bounds"); }
        if !(0_i64..=5_i64).contains(&self.max_fix_attempts) { return Err("max_fix_attempts out of bounds"); }
        if !(1000_i64..=50000000_i64).contains(&self.max_diff_bytes) { return Err("max_diff_bytes out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForbiddenPath {
    pub id: String,
    pub globs: Vec<String>,
    pub description: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForbiddenPattern {
    pub id: String,
    pub pattern: String,
    pub description: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RemediationPolicy {
    pub schema_version: i64,
    pub policy_id: String,
    pub version: String,
    pub limits: Box<PackLimits>,
    pub test_path_globs: Vec<String>,
    pub forbidden_paths: Vec<ForbiddenPath>,
    pub forbidden_added_patterns: Vec<ForbiddenPattern>,
    pub test_assertion_patterns: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodeSecurityCatalog {
    pub weakness_classes: Box<WeaknessClassCatalog>,
    pub severity_rubric: Box<SeverityRubric>,
    pub priority_policy: Box<PriorityPolicy>,
    pub remediation_policy: Box<RemediationPolicy>,
    pub pack_templates: BTreeMap<String, String>,
}

pub const CLASS_ID: &str = "^[a-z][a-z0-9_]{2,63}$";
pub const RULE_ID: &str = "^[a-z][a-z0-9-]{2,63}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CodeSecurityCatalogError {
    pub message: String,
}

impl CodeSecurityCatalogError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CodeSecurityCatalogError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CodeSecurityCatalogError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Strict {
    pub initialized: bool,
}

impl WeaknessClass {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn manual_is_plan_only(&self) -> Result<WeaknessClass, &'static str> {
        Err("runtime_binding_required")
    }
}

impl WeaknessClassCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unique_cwe_owner(&self) -> Result<WeaknessClassCatalog, &'static str> {
        let mut owners: std::collections::BTreeMap<i64, String> = std::collections::BTreeMap::<i64, String>::new();
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn class_for_cwe(&self, mut cwe: i64) -> Option<String> {
        core::hint::black_box(None)
    }
}

impl SeverityRubric {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn complete_and_descending(&self) -> Result<SeverityRubric, &'static str> {
        Err("runtime_binding_required")
    }
}

impl PriorityPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unique_ids(&self) -> Result<PriorityPolicy, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ForbiddenPattern {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn compiles(&self) -> Result<ForbiddenPattern, &'static str> {
        Err("runtime_binding_required")
    }
}

impl RemediationPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn assertions_compile(&self) -> Result<RemediationPolicy, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn guard_document(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

impl CodeSecurityCatalog {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn version_stamp(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("weakness_classes"), String::new()), (String::from("severity_rubric"), String::new()), (String::from("priority_policy"), String::new()), (String::from("remediation_policy"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_yaml(mut path: String) -> Result<String, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_templates(mut root: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut templates: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(templates.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_code_security_catalog(mut root: String) -> Result<CodeSecurityCatalog, &'static str> {
    Ok(CodeSecurityCatalog::default())
}

