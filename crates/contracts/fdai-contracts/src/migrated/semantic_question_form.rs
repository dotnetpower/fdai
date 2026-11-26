pub const MAX_FORM_MENTIONS: i64 = 16;
pub const MAX_FORM_GOALS: i64 = 4;
pub const MAX_FORM_ALTERNATIVES: i64 = 3;
pub const MAX_ALTERNATIVE_ATOMS: i64 = 6;
pub const MAX_FORM_BYTES: i64 = 6144;
pub const MAX_CONTEXT_SPANS: i64 = 32;
pub const MAX_UNSUPPORTED_CONSTRAINTS: i64 = 8;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MentionForm {
    #[default]
    Identifier,
    Name,
    Concept,
    ValueContract,
    Anaphor,
    Ordinal,
}

impl MentionForm {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Identifier => "identifier",
            Self::Name => "name",
            Self::Concept => "concept",
            Self::ValueContract => "value",
            Self::Anaphor => "anaphor",
            Self::Ordinal => "ordinal",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MentionDomain {
    #[default]
    Instance,
    ObjectType,
    ResourceType,
    ResourceClass,
    State,
    Health,
    Metric,
    Region,
    DeclarationKind,
    Property,
}

impl MentionDomain {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Instance => "instance",
            Self::ObjectType => "object_type",
            Self::ResourceType => "resource_type",
            Self::ResourceClass => "resource_class",
            Self::State => "state",
            Self::Health => "health",
            Self::Metric => "metric",
            Self::Region => "region",
            Self::DeclarationKind => "declaration_kind",
            Self::Property => "property",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GoalLevel {
    #[default]
    Instance,
    Schema,
}

impl GoalLevel {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Instance => "instance",
            Self::Schema => "schema",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GoalOperation {
    #[default]
    Select,
    Count,
    Lookup,
    Traverse,
    PathContract,
    Aggregate,
    Rank,
    History,
    CompareWindows,
    CompareEntities,
    DiffVersions,
    Impact,
    ExplainCause,
    VerifyEvidence,
    DescribeSchema,
    Diagnose,
    DraftAction,
}

impl GoalOperation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Select => "select",
            Self::Count => "count",
            Self::Lookup => "lookup",
            Self::Traverse => "traverse",
            Self::PathContract => "path",
            Self::Aggregate => "aggregate",
            Self::Rank => "rank",
            Self::History => "history",
            Self::CompareWindows => "compare_windows",
            Self::CompareEntities => "compare_entities",
            Self::DiffVersions => "diff_versions",
            Self::Impact => "impact",
            Self::ExplainCause => "explain_cause",
            Self::VerifyEvidence => "verify_evidence",
            Self::DescribeSchema => "describe_schema",
            Self::Diagnose => "diagnose",
            Self::DraftAction => "draft_action",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SubjectScope {
    #[default]
    Anchor,
    Collection,
    PriorResult,
    GoalOutput,
}

impl SubjectScope {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Anchor => "anchor",
            Self::Collection => "collection",
            Self::PriorResult => "prior_result",
            Self::GoalOutput => "goal_output",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FilterRole {
    #[default]
    Type,
    State,
    Health,
    Region,
    NameFragment,
    Scope,
    Metric,
}

impl FilterRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Type => "type",
            Self::State => "state",
            Self::Health => "health",
            Self::Region => "region",
            Self::NameFragment => "name_fragment",
            Self::Scope => "scope",
            Self::Metric => "metric",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Comparator {
    #[default]
    Greater,
    AtLeast,
    Less,
    AtMost,
}

impl Comparator {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Greater => "gt",
            Self::AtLeast => "ge",
            Self::Less => "lt",
            Self::AtMost => "le",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MetricUnit {
    #[default]
    Percent,
    Milliseconds,
    Count,
    Nanocores,
    Unstated,
}

impl MetricUnit {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Percent => "percent",
            Self::Milliseconds => "ms",
            Self::Count => "count",
            Self::Nanocores => "nanocores",
            Self::Unstated => "unit_unstated",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RelationSense {
    #[default]
    Containment,
    Attachment,
    Dependency,
    Connectivity,
    Traffic,
    Classification,
    Composition,
    Ownership,
    Authorization,
    Evidence,
}

impl RelationSense {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Containment => "containment",
            Self::Attachment => "attachment",
            Self::Dependency => "dependency",
            Self::Connectivity => "connectivity",
            Self::Traffic => "traffic",
            Self::Classification => "classification",
            Self::Composition => "composition",
            Self::Ownership => "ownership",
            Self::Authorization => "authorization",
            Self::Evidence => "evidence",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RelationScope {
    #[default]
    OneSense,
    AllKinds,
}

impl RelationScope {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OneSense => "one_sense",
            Self::AllKinds => "all_kinds",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SubjectPosition {
    #[default]
    Source,
    Target,
    Either,
}

impl SubjectPosition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Source => "source",
            Self::Target => "target",
            Self::Either => "either",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SubjectRole {
    #[default]
    Container,
    Member,
    Dependent,
    Dependency,
    Sender,
    Receiver,
    Attached,
    Host,
    Instance,
    Category,
    Evidence,
    Evidenced,
    Owner,
    Owned,
    Whole,
    Part,
    Grantee,
    Granted,
    Either,
}

impl SubjectRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Container => "container",
            Self::Member => "member",
            Self::Dependent => "dependent",
            Self::Dependency => "dependency",
            Self::Sender => "sender",
            Self::Receiver => "receiver",
            Self::Attached => "attached",
            Self::Host => "host",
            Self::Instance => "instance",
            Self::Category => "category",
            Self::Evidence => "evidence",
            Self::Evidenced => "evidenced",
            Self::Owner => "owner",
            Self::Owned => "owned",
            Self::Whole => "whole",
            Self::Part => "part",
            Self::Grantee => "grantee",
            Self::Granted => "granted",
            Self::Either => "either",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RelationReach {
    #[default]
    OneHop,
    Transitive,
}

impl RelationReach {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OneHop => "one_hop",
            Self::Transitive => "transitive",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RelationAnchorScope {
    #[default]
    Instance,
    Collection,
}

impl RelationAnchorScope {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Instance => "instance",
            Self::Collection => "collection",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MeasureKind {
    #[default]
    Count,
    State,
    Health,
    Metric,
    Change,
    Event,
    Forecast,
    Cost,
    Property,
}

impl MeasureKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Count => "count",
            Self::State => "state",
            Self::Health => "health",
            Self::Metric => "metric",
            Self::Change => "change",
            Self::Event => "event",
            Self::Forecast => "forecast",
            Self::Cost => "cost",
            Self::Property => "property",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GroupBy {
    #[default]
    Endpoint,
    Type,
    Container,
    None,
}

impl GroupBy {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Endpoint => "endpoint",
            Self::Type => "type",
            Self::Container => "container",
            Self::None => "none",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OrderDirection {
    #[default]
    Ascending,
    Descending,
}

impl OrderDirection {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ascending => "ascending",
            Self::Descending => "descending",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TimeKind {
    #[default]
    Current,
    Window,
    AsOf,
    TwoWindows,
    Versions,
    Future,
    Unspecified,
}

impl TimeKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Current => "current",
            Self::Window => "window",
            Self::AsOf => "as_of",
            Self::TwoWindows => "two_windows",
            Self::Versions => "versions",
            Self::Future => "future",
            Self::Unspecified => "unspecified",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Want {
    #[default]
    Fact,
    Cause,
    Verification,
    Completeness,
}

impl Want {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Fact => "fact",
            Self::Cause => "cause",
            Self::Verification => "verification",
            Self::Completeness => "completeness",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MetricQualifier {
    #[default]
    High,
    Low,
}

impl MetricQualifier {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::High => "high",
            Self::Low => "low",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DurationUnit {
    #[default]
    Minute,
    Hour,
    Day,
    Week,
}

impl DurationUnit {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Minute => "minute",
            Self::Hour => "hour",
            Self::Day => "day",
            Self::Week => "week",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceSpan {
    pub start: i64,
    pub end: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FormQualifier {
    pub mention: String,
    pub sense: RelationSense,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FormMention {
    pub id: String,
    pub form: MentionForm,
    pub domain: MentionDomain,
    pub span: Box<SourceSpan>,
    #[allow(clippy::type_complexity)]
    pub qualifier: Option<Box<FormQualifier>>,
    pub position: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricComparison {
    pub comparator: Comparator,
    pub value: String,
    pub value_span: Box<SourceSpan>,
    pub unit: MetricUnit,
    #[allow(clippy::type_complexity)]
    pub unit_span: Option<Box<SourceSpan>>,
    pub comparator_span: Box<SourceSpan>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FormFilter {
    pub role: FilterRole,
    pub mention: String,
    #[allow(clippy::type_complexity)]
    pub cue: Option<Box<SourceSpan>>,
    #[allow(clippy::type_complexity)]
    pub comparison: Option<Box<MetricComparison>>,
    pub qualifier: Option<MetricQualifier>,
    #[allow(clippy::type_complexity)]
    pub qualifier_span: Option<Box<SourceSpan>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FormRelation {
    pub sense: RelationSense,
    pub scope: RelationScope,
    pub anchor: Option<String>,
    pub counterpart: Option<String>,
    pub anchor_role: SubjectRole,
    pub result_role: SubjectRole,
    pub reach: RelationReach,
    pub cue: Box<SourceSpan>,
    #[allow(clippy::type_complexity)]
    pub reach_cue: Option<Box<SourceSpan>>,
    pub anchor_scope: RelationAnchorScope,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FormOrder {
    pub direction: OrderDirection,
    pub limit: Option<i64>,
    #[allow(clippy::type_complexity)]
    pub limit_span: Option<Box<SourceSpan>>,
    #[allow(clippy::type_complexity)]
    pub cue: Option<Box<SourceSpan>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FormMeasure {
    pub kind: MeasureKind,
    pub group_by: GroupBy,
    pub mention: Option<String>,
    #[allow(clippy::type_complexity)]
    pub order: Option<Box<FormOrder>>,
    #[allow(clippy::type_complexity)]
    pub cue: Option<Box<SourceSpan>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DurationValue {
    pub amount: i64,
    pub unit: DurationUnit,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TemporalValue {
    #[allow(clippy::type_complexity)]
    pub duration: Option<Box<DurationValue>>,
    pub calendar_offset_days: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FormTime {
    pub kind: TimeKind,
    #[allow(clippy::type_complexity)]
    pub value: Option<Box<TemporalValue>>,
    pub windows: Vec<TemporalValue>,
    #[allow(clippy::type_complexity)]
    pub cue: Option<Box<SourceSpan>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FormGoal {
    pub id: String,
    pub level: GoalLevel,
    pub operation: GoalOperation,
    pub subject: Option<String>,
    pub subject_scope: SubjectScope,
    pub counterpart: Option<String>,
    pub filters: Vec<FormFilter>,
    #[allow(clippy::type_complexity)]
    pub relation: Option<Box<FormRelation>>,
    #[allow(clippy::type_complexity)]
    pub measure: Option<Box<FormMeasure>>,
    pub time: Box<FormTime>,
    pub want: Want,
    pub depends_on: Vec<String>,
    pub cue: Box<SourceSpan>,
    pub confidence: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AtomDiff {
    pub field: String,
    pub value: String,
}

impl AtomDiff {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.field.as_str(), "level" | "operation" | "subject" | "subject_scope" | "relation.sense" | "relation.anchor" | "relation.counterpart" | "relation.anchor_role" | "relation.result_role" | "relation.reach" | "measure.kind" | "time.kind" | "want") { return Err("invalid field literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FormAlternative {
    pub goal: String,
    pub atoms: Vec<AtomDiff>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticQuestionForm {
    pub schema_version: String,
    pub mentions: Vec<FormMention>,
    pub goals: Vec<FormGoal>,
    pub alternatives: Vec<FormAlternative>,
    pub context: Vec<SourceSpan>,
    pub unsupported_constraints: Vec<SourceSpan>,
    pub remaining_goals: bool,
    pub execution_authority: bool,
}

impl SemanticQuestionForm {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0" | "1.1.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const MENTION_ID: &str = "^m[0-9]{1,2}$";
pub const GOAL_ID: &str = "^g[0-9]{1,2}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FormModel {
    pub initialized: bool,
}

impl SourceSpan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn ordered(&self) -> Result<SourceSpan, &'static str> {
        if (self.end) <= (self.start) {
            return Err("source span end MUST follow its start");
        }
        Ok(self.clone())
    }
}

impl MetricComparison {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn unit_has_its_span(&self) -> Result<MetricComparison, &'static str> {
        Err("runtime_binding_required")
    }
}

impl FormFilter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn comparison_matches_role(&self) -> Result<FormFilter, &'static str> {
        if (self.qualifier.is_some()) && (self.comparison.is_some()) {
            return Err("a metric filter states a number or a qualifier never both");
        }
        if (self.qualifier.is_none()) != (self.qualifier_span.is_none()) {
            return Err("a metric qualifier needs its span and only a qualifier has one");
        }
        Ok(self.clone())
    }
}

impl FormRelation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn collection_anchor_is_one_hop_of_one_sense(&self) -> Result<FormRelation, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn roles_consistent(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn anchor_position(&self) -> Option<SubjectPosition> {
        core::hint::black_box(None)
    }
}

impl FormOrder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn limit_has_its_span(&self) -> Result<FormOrder, &'static str> {
        if (self.limit.is_none()) != (self.limit_span.is_none()) {
            return Err("a stated order limit needs its span and no limit has none");
        }
        Ok(self.clone())
    }
}

impl TemporalValue {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn one_value(&self) -> Result<TemporalValue, &'static str> {
        if (self.duration.is_none()) == (self.calendar_offset_days.is_none()) {
            return Err("temporal value MUST carry exactly one of duration or offset");
        }
        Ok(self.clone())
    }
}

impl FormTime {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn value_matches_kind(&self) -> Result<FormTime, &'static str> {
        Err("runtime_binding_required")
    }
}

impl FormGoal {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn effective_operation(&self) -> GoalOperation {
        self.operation.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn restated_subject(&self) -> bool {
        core::hint::black_box(false)
    }
}

impl SemanticQuestionForm {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn references_resolve(&self) -> Result<SemanticQuestionForm, &'static str> {
        let mut goal_ids: Vec<String> = Vec::<String>::new();
        for goal in self.goals.clone() {
            if (goal_ids.clone()).contains(&(goal.id.clone())) {
                return Err("form goal ids MUST be unique");
            }
            goal_ids.push(goal.id.clone());
        }
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn canonical_json(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn mention(&self, mut mention_id: String) -> FormMention {
        if mention_id.is_empty() {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn literal_mentions(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn declared_spans(&self, mut context: bool) -> Vec<SourceSpan> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn cited_mentions(&self) -> std::collections::BTreeSet<String> {
        let mut cited: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        for goal in self.goals.clone() {
            if (goal.subject.clone()).is_some() {
                cited.insert((goal.subject.clone()).unwrap_or_default());
            }
            if (goal.counterpart.clone()).is_some() {
                cited.insert((goal.counterpart.clone()).unwrap_or_default());
            }
        }
        std::collections::BTreeSet::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_CONTEXT_SPANS", "MAX_FORM_BYTES", "MAX_FORM_GOALS", "MAX_FORM_MENTIONS", "MAX_UNSUPPORTED_CONSTRAINTS", "AtomDiff", "Comparator", "DurationUnit", "DurationValue", "FilterRole", "FormAlternative", "FormFilter", "FormGoal", "FormMeasure", "FormMention", "FormQualifier", "FormRelation", "FormTime", "GoalLevel", "GoalOperation", "GroupBy", "MeasureKind", "MentionDomain", "MentionForm", "MetricComparison", "MetricQualifier", "MetricUnit", "RelationAnchorScope", "RelationReach", "RelationScope", "RelationSense", "SemanticQuestionForm", "SourceSpan", "SENSE_ROLES", "SubjectPosition", "SubjectRole", "SubjectScope", "TemporalValue", "TimeKind", "Want"];
