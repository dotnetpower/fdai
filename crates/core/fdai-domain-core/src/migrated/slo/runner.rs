#[derive(Clone, Debug, Default, PartialEq)]
pub struct SloBurnRunReport {
    pub evaluated: i64,
    pub breached: i64,
    pub published: i64,
    pub insufficient: i64,
    pub publish_errors: Vec<String>,
    pub evaluation_errors: Vec<String>,
}

pub const SLO_BURN_EVENT_TOPIC: &str = "fdai.slo.events";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SloBurnRunner {
    pub initialized: bool,
}

impl SloBurnRunner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_once(&self, mut now: Option<String>) -> Result<SloBurnRunReport, &'static str> {
        let mut evaluated: i64 = 0_i64;
        let mut breached: i64 = 0_i64;
        let mut published: i64 = 0_i64;
        let mut insufficient: i64 = 0_i64;
        let mut publish_errors: Vec<(String, String)> = Vec::<(String, String)>::new();
        let mut evaluation_errors: Vec<(String, String)> = Vec::<(String, String)>::new();
        Ok(SloBurnRunReport { evaluated: evaluated, breached: breached, published: published, insufficient: insufficient, ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn default_clock() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["SLO_BURN_EVENT_TOPIC", "SloBurnRunReport", "SloBurnRunner"];
