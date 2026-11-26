use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResourceRef {
    pub resource_type: String,
    pub r#ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InventoryDiff {
    pub kind: String,
    pub target: Box<ResourceRef>,
    pub properties: BTreeMap<String, String>,
}

impl InventoryDiff {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "create" | "update" | "delete") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Finding {
    pub rule_id: String,
    pub resource: Box<ResourceRef>,
    pub severity: String,
    pub reason: String,
    pub evidence_refs: Vec<String>,
}

impl Finding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.severity.as_str(), "low" | "medium" | "high" | "critical") { return Err("invalid severity literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleSet {
    pub rule_ids: Vec<String>,
}

pub trait ScratchProjection {
    fn apply_diff(&self, diff: InventoryDiff) -> String;
    fn evaluate(&self, rules: RuleSet) -> Vec<Finding>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["Finding", "InventoryDiff", "ResourceRef", "RuleSet", "ScratchProjection", "Severity"];
