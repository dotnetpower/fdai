pub trait RcaReasoner {
    fn reason(&self, incident_summary: String, candidate_citations: Vec<String>) -> Option<String>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["RcaReasoner"];
