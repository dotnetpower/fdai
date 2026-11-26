pub trait TranscriptSummarizer {
    fn summarize(&self, entries: Vec<String>, level: i64) -> String;
}

pub trait TranscriptRetriever {
    fn retrieve(&self, utterance: String, candidates: Vec<String>, k: i64) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DeterministicTruncationSummarizer {
    pub initialized: bool,
}

impl DeterministicTruncationSummarizer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn summarize(&self, mut entries: Vec<String>, mut level: i64) -> Result<String, &'static str> {
        if (entries.clone()).is_empty() {
            return Err("cannot summarize an empty span");
        }
        if (level) < (1_i64) {
            return Err("summary level MUST be  1");
        }
        Ok(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoOpRetriever {
    pub initialized: bool,
}

impl NoOpRetriever {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn retrieve(&self, mut utterance: String, mut candidates: Vec<String>, mut k: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn estimate_tokens(mut text: String) -> i64 {
    0_i64
}

pub const PUBLIC_EXPORTS: &[&str] = &["DeterministicTruncationSummarizer", "NoOpRetriever", "TranscriptRetriever", "TranscriptSummarizer"];
