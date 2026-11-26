pub const MAX_PREDICATE_OPERAND_BYTES: i64 = 65536;
pub const MAX_PREDICATES: i64 = 32;
pub const MAX_IN_VALUES: i64 = 1000;
pub const MAX_ROOT_IDS: i64 = 1000;
pub const MAX_LINK_TYPES: i64 = 64;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ObjectSelectorKind {
    #[default]
    ObjectType,
    Interface,
}

impl ObjectSelectorKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ObjectType => "object_type",
            Self::Interface => "interface",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ObjectPredicateOperator {
    #[default]
    Equals,
    NotEquals,
    In,
    Exists,
    Absent,
    AtLeast,
    AtMost,
    Contains,
    EqualsIgnoreCase,
}

impl ObjectPredicateOperator {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Equals => "equals",
            Self::NotEquals => "not_equals",
            Self::In => "in",
            Self::Exists => "exists",
            Self::Absent => "absent",
            Self::AtLeast => "at_least",
            Self::AtMost => "at_most",
            Self::Contains => "contains",
            Self::EqualsIgnoreCase => "equals_ignore_case",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ObjectSetTruncationReason {
    #[default]
    ResultLimit,
    CandidateLimit,
    TraversalLimit,
}

impl ObjectSetTruncationReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResultLimit => "result_limit",
            Self::CandidateLimit => "candidate_limit",
            Self::TraversalLimit => "traversal_limit",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ObjectSetPopulationStatus {
    #[default]
    Complete,
    Unknown,
    VisibilityIndeterminate,
}

impl ObjectSetPopulationStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Complete => "population_complete",
            Self::Unknown => "population_unknown",
            Self::VisibilityIndeterminate => "population_visibility_indeterminate",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObjectSelector {
    pub kind: ObjectSelectorKind,
    pub name: String,
}

impl ObjectSelector {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.name.trim().is_empty() { return Err("name must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObjectPredicate {
    pub property: String,
    pub operator: ObjectPredicateOperator,
    pub equals: String,
    pub values: Vec<String>,
}

impl ObjectPredicate {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.property.trim().is_empty() { return Err("property must be non-empty"); }
        if self.equals.trim().is_empty() { return Err("equals must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObjectTraversal {
    pub link_types: Vec<String>,
    pub direction: String,
    pub max_depth: i64,
}

impl ObjectTraversal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.direction.trim().is_empty() { return Err("direction must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RelationshipTraversalDefinition {
    pub selector: Box<ObjectSelector>,
    pub link_types: Vec<String>,
    pub direction: String,
    pub max_depth: i64,
    pub as_of: String,
    pub purpose: String,
    pub limit: i64,
    pub freshness_seconds: Option<i64>,
    pub endpoint_predicates: Vec<ObjectPredicate>,
    pub emit_lineage: bool,
    pub emit_coverage: bool,
    pub read_population: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TypedPathStep {
    pub link_type: String,
    pub direction: String,
    pub selector: Box<ObjectSelector>,
    pub max_hops: i64,
}

impl TypedPathStep {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.direction.as_str(), "outgoing" | "incoming") { return Err("invalid direction literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TypedPathDefinition {
    pub steps: Vec<TypedPathStep>,
    pub as_of: String,
    pub purpose: String,
    pub limit: i64,
    pub freshness_seconds: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyInstancePathDefinition {
    pub root_selector: Box<ObjectSelector>,
    pub steps: Vec<TypedPathStep>,
    pub as_of: String,
    pub purpose: String,
    pub limit: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObjectSetDefinition {
    pub selector: Box<ObjectSelector>,
    pub predicates: Vec<ObjectPredicate>,
    #[allow(clippy::type_complexity)]
    pub object_ids: Option<Vec<String>>,
    #[allow(clippy::type_complexity)]
    pub traversal: Option<Box<ObjectTraversal>>,
    pub root_ids: Vec<String>,
    pub as_of: String,
    pub purpose: String,
    pub limit: i64,
    pub freshness_seconds: Option<i64>,
    pub include_relationships: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObjectSetMaterialization {
    pub definition: Box<ObjectSetDefinition>,
    pub graph: String,
    pub concrete_types: Vec<String>,
    pub truncated: bool,
    pub truncation_reason: Option<ObjectSetTruncationReason>,
}

impl ObjectSelector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn non_blank_name(&self) -> Result<ObjectSelector, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ObjectPredicate {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn normalize_equals(mut value: String) -> String {
        bounded_json_operand(value.clone(), String::from("object_predicate.equals")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn normalize_values(mut value: String) -> String {
        bounded_json_operand(value.clone(), String::from("object_predicate.values")).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn operands_match_operator(&self) -> Result<ObjectPredicate, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn serialize_operands(&self, mut handler: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

impl ObjectTraversal {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unique_link_types(&self) -> Result<ObjectTraversal, &'static str> {
        Err("runtime_binding_required")
    }
}

impl RelationshipTraversalDefinition {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn population_read_allowed(&self, mut link_is_transitive: bool) -> bool {
        (!(self.read_population)) || (((self.max_depth) == (1_i64)) || (link_is_transitive))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bounded_traversal(&self) -> Result<RelationshipTraversalDefinition, &'static str> {
        if (((self.link_types.clone()).len() as i64)) != ((((self.link_types.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("relationship traversal link types MUST be unique");
        }
        if (self.emit_coverage) && (!(self.emit_lineage)) {
            return Err("relationship traversal coverage rows require lineage rows");
        }
        if (self.read_population) && (self.emit_lineage) {
            return Err("relationship traversal population reads endpoints not lineage");
        }
        Ok(self.clone())
    }
}

impl TypedPathDefinition {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bounded_path(&self) -> Result<TypedPathDefinition, &'static str> {
        Err("runtime_binding_required")
    }
}

impl OntologyInstancePathDefinition {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bounded_path(&self) -> Result<OntologyInstancePathDefinition, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ObjectSetDefinition {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn traversal_requires_roots(&self) -> Result<ObjectSetDefinition, &'static str> {
        if self.object_ids.is_some() {
            if (self.traversal.is_some()) || (!(self.root_ids.clone()).is_empty()) {
                return Err("explicit object ids MUST NOT be combined with traversal roots");
            }
        }
        if (self.traversal.is_some()) && ((self.root_ids.clone()).is_empty()) {
            return Err("object-set traversal requires root_ids");
        }
        if (self.traversal.is_none()) && (!(self.root_ids.clone()).is_empty()) {
            return Err("object-set root_ids require traversal");
        }
        if (self.traversal.is_some()) && (!(self.include_relationships)) {
            return Err("object-set traversal requires relationship inclusion");
        }
        Ok(self.clone())
    }
}

impl ObjectSetMaterialization {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn truncation_reason_matches_state(&self) -> Result<ObjectSetMaterialization, &'static str> {
        if (self.truncated) != (self.truncation_reason.is_some()) {
            return Err("object-set truncation reason MUST match truncated state");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_json_operand(mut value: String, mut path: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ObjectSetPopulationStatus", "InterfaceImplementation", "ObjectPredicate", "ObjectPredicateOperator", "ObjectSelector", "ObjectSelectorKind", "ObjectSetDefinition", "ObjectSetMaterialization", "ObjectSetTruncationReason", "ObjectTraversal", "OntologyInterfaceType", "RelationshipTraversalDefinition"];
