use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostParityOwner {
    #[default]
    Legacy,
    Package,
}

impl CostParityOwner {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Legacy => "legacy",
            Self::Package => "package",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostParityRecord {
    pub case_id: String,
    pub implementation: CostParityOwner,
    pub decision: String,
    pub reasons: Vec<String>,
    pub topic: String,
    pub payload: BTreeMap<String, String>,
    pub audit_fields: BTreeMap<String, String>,
    pub ontology_lineage: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ApprovedParityDifference {
    pub mechanism_version: String,
    pub approval_id: String,
    pub case_id: String,
    pub field: String,
    pub legacy_value_digest: String,
    pub package_value_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostParityReport {
    pub case_count: i64,
    pub approved_difference_count: i64,
    pub selected_owner: CostParityOwner,
    pub publication_records: Vec<CostParityRecord>,
}

pub const SHA256: &str = "^sha256:[0-9a-f]{64}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CostParityError {
    pub message: String,
}

impl CostParityError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CostParityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CostParityError {}

impl CostParityRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn comparable(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("decision"), self.decision.clone()), (String::from("reasons"), String::new()), (String::from("topic"), self.topic.clone()), (String::from("payload"), String::new()), (String::from("audit_fields"), String::new()), (String::from("ontology_lineage"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CostGovernanceParityHarness {
    pub initialized: bool,
}

impl CostGovernanceParityHarness {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn compare(&self, mut legacy: Vec<CostParityRecord>, mut package: Vec<CostParityRecord>, mut selected_owner: CostParityOwner, mut publisher_claims: Vec<CostParityOwner>, mut approved_differences: Vec<ApprovedParityDifference>) -> Result<CostParityReport, &'static str> {
        let legacy_by_case: std::collections::BTreeMap<String, CostParityRecord> = records_by_case(legacy.clone(), Default::default()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let package_by_case: std::collections::BTreeMap<String, CostParityRecord> = records_by_case(package.clone(), Default::default()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        if (((publisher_claims.clone()).len() as i64)) > (1_i64) {
            return Err("dual-writer publication is prohibited");
        }
        let mut used: std::collections::BTreeSet<(String, String)> = std::collections::BTreeSet::<(String, String)>::new();
        Ok(CostParityReport { case_count: ((legacy_by_case.clone()).len() as i64), approved_difference_count: ((used.clone()).len() as i64), selected_owner: selected_owner.clone(), ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn value_digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn records_by_case(mut records: Vec<CostParityRecord>, mut expected_owner: CostParityOwner) -> Result<std::collections::BTreeMap<String, CostParityRecord>, &'static str> {
    let mut result: std::collections::BTreeMap<String, CostParityRecord> = std::collections::BTreeMap::<String, CostParityRecord>::new();
    for record in records.clone() {
        if (result.clone()).contains_key((record.case_id.clone()).as_str()) {
            return Err("duplicate parity case id: record.case_id");
        }
        result.insert(record.case_id.clone(), record.clone());
    }
    if (result.clone()).is_empty() {
        return Err("parity corpus MUST be non-empty");
    }
    Ok(result.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ApprovedParityDifference", "CostGovernanceParityHarness", "CostParityError", "CostParityOwner", "CostParityRecord", "CostParityReport", "value_digest"];
