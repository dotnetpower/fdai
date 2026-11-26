#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ConstraintSlotRole {
    #[default]
    TimeWindow,
    Location,
    PropertyPredicate,
    LifecycleStatus,
    GroupBy,
    RelationPath,
    PriorResult,
    Ordinal,
}

impl ConstraintSlotRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::TimeWindow => "time_window",
            Self::Location => "location",
            Self::PropertyPredicate => "property_predicate",
            Self::LifecycleStatus => "lifecycle_status",
            Self::GroupBy => "group_by",
            Self::RelationPath => "relation_path",
            Self::PriorResult => "prior_result",
            Self::Ordinal => "ordinal",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticConstraintSlot {
    pub role: ConstraintSlotRole,
    pub source_start: i64,
    pub source_end: i64,
    pub grounded: bool,
    pub value: Option<String>,
    pub object_type: Option<String>,
    pub unbound_reason: String,
}

impl SemanticConstraintSlot {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=32000_i64).contains(&self.source_start) { return Err("source_start out of bounds"); }
        if !(1_i64..=32000_i64).contains(&self.source_end) { return Err("source_end out of bounds"); }
        Ok(())
    }
}

impl SemanticConstraintSlot {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn consistent(&self) -> Result<SemanticConstraintSlot, &'static str> {
        if (self.source_end) <= (self.source_start) {
            return Err("constraint slot source span MUST be ordered");
        }
        if self.grounded {
            if (self.value.is_none()) || (true) {
                return Err("grounded constraint slots require value only");
            }
        } else if false {
            return Err("unbound constraint slots require a reason");
        }
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConstraintSlotRole", "SemanticConstraintSlot"];
