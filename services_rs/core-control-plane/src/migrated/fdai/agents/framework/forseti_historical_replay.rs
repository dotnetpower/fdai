#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForsetiHistoricalQualitySample {
    pub key: String,
    pub event_type: String,
    pub action_type: String,
    pub risk_verdict: String,
    pub judgment_table_digest: String,
    pub tier: String,
    pub observed_at: String,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForsetiHistoricalReplay {
    pub archive_ref: String,
    pub content_digest: String,
    pub source_revision: String,
    pub review_ref: String,
    pub window_started_at: String,
    pub window_ended_at: String,
    pub evidence_refs: Vec<String>,
    pub samples: Vec<ForsetiHistoricalQualitySample>,
}

impl ForsetiHistoricalQualitySample {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn quality_sample(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("event_type"), self.event_type.clone()), (String::from("action_type"), self.action_type.clone()), (String::from("risk_verdict"), self.risk_verdict.clone()), (String::from("judgment_table_digest"), self.judgment_table_digest.clone()), (String::from("tier"), self.tier.clone())])
    }
}

pub trait ForsetiHistoricalReplaySource {
    fn read_replay(&self, archive_ref: String) -> Option<ForsetiHistoricalReplay>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ForsetiHistoricalQualitySample", "ForsetiHistoricalReplay", "ForsetiHistoricalReplaySource"];
