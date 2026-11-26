pub const MAX_ANSWER_CHARS: i64 = 16000;
pub const MAX_CLAIMS: i64 = 64;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AnswerClaimKind {
    #[default]
    Restatement,
    Fact,
    Count,
    Relation,
    State,
    Change,
    CauseHypothesis,
    Limitation,
    NextCheck,
}

impl AnswerClaimKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Restatement => "restatement",
            Self::Fact => "fact",
            Self::Count => "count",
            Self::Relation => "relation",
            Self::State => "state",
            Self::Change => "change",
            Self::CauseHypothesis => "cause_hypothesis",
            Self::Limitation => "limitation",
            Self::NextCheck => "next_check",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ClaimPolarity {
    #[default]
    Affirm,
    Deny,
}

impl ClaimPolarity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Affirm => "affirm",
            Self::Deny => "deny",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ClaimQuantifier {
    #[default]
    Exact,
    AtLeast,
    AtMost,
    Any,
    All,
    None,
}

impl ClaimQuantifier {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Exact => "exact",
            Self::AtLeast => "at_least",
            Self::AtMost => "at_most",
            Self::Any => "any",
            Self::All => "all",
            Self::None => "none",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ClaimModality {
    #[default]
    Observed,
    Possible,
    Hypothesis,
}

impl ClaimModality {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Observed => "observed",
            Self::Possible => "possible",
            Self::Hypothesis => "hypothesis",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ClaimCausalClass {
    #[default]
    None,
    Association,
    TemporalPrecedence,
    CausalHypothesis,
}

impl ClaimCausalClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Association => "association",
            Self::TemporalPrecedence => "temporal_precedence",
            Self::CausalHypothesis => "causal_hypothesis",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ClaimTemporalBasis {
    #[default]
    Current,
    Window,
    Historical,
    Snapshot,
}

impl ClaimTemporalBasis {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Current => "current",
            Self::Window => "window",
            Self::Historical => "historical",
            Self::Snapshot => "snapshot",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnswerClaimSpan {
    pub start: i64,
    pub end: i64,
}

impl AnswerClaimSpan {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=32000_i64).contains(&self.start) { return Err("start out of bounds"); }
        if !(1_i64..=32000_i64).contains(&self.end) { return Err("end out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnswerEvidenceRef {
    pub goal: String,
    pub node: String,
    pub row: Option<String>,
    pub field: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnswerLiteralBinding {
    pub span: Box<AnswerClaimSpan>,
    pub value: String,
    pub r#ref: Box<AnswerEvidenceRef>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnswerClaimProposition {
    pub subject: Option<String>,
    pub predicate: Option<String>,
    pub object: Option<String>,
    pub value: Option<String>,
    pub polarity: ClaimPolarity,
    pub quantifier: ClaimQuantifier,
    pub unit: Option<String>,
    pub currency: Option<String>,
    pub temporal_basis: Option<ClaimTemporalBasis>,
    pub time_zone: Option<String>,
    pub modality: ClaimModality,
    pub causal_class: ClaimCausalClass,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnswerClaim {
    pub id: String,
    pub kind: AnswerClaimKind,
    pub span: Box<AnswerClaimSpan>,
    pub refs: Vec<AnswerEvidenceRef>,
    pub proposition: Box<AnswerClaimProposition>,
    pub literals: Vec<AnswerLiteralBinding>,
    pub rows: Vec<String>,
    pub limitation_codes: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ComposedAnswer {
    pub schema_version: String,
    pub text: String,
    pub claims: Vec<AnswerClaim>,
}

impl ComposedAnswer {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

pub const ID: &str = "^[a-z][a-z0-9_.-]{0,79}$";
impl AnswerClaimSpan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn ordered(&self) -> Result<AnswerClaimSpan, &'static str> {
        if (self.end) <= (self.start) {
            return Err("answer claim span MUST be ordered");
        }
        Ok(self.clone())
    }
}

impl AnswerClaimProposition {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn causal_fields_are_consistent(&self) -> Result<AnswerClaimProposition, &'static str> {
        if (self.currency.is_some()) && (self.unit.is_none()) {
            return Err("currency claims MUST also declare a unit");
        }
        Ok(self.clone())
    }
}

impl ComposedAnswer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn spans_inside_text(&self) -> Result<ComposedAnswer, &'static str> {
        let size: i64 = (self.text.clone()).len() as i64;
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AnswerClaim", "AnswerClaimKind", "AnswerClaimProposition", "AnswerClaimSpan", "AnswerEvidenceRef", "AnswerLiteralBinding", "ClaimCausalClass", "ClaimModality", "ClaimPolarity", "ClaimQuantifier", "ClaimTemporalBasis", "ComposedAnswer", "MAX_ANSWER_CHARS", "MAX_CLAIMS"];
