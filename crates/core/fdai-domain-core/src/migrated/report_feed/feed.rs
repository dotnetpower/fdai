pub trait SignalSource {
    fn name(&self) -> String;
    fn signals(&self, since: String, until: String) -> Vec<String>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticSignalSource {
    pub initialized: bool,
}

impl StaticSignalSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn name(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn signals(&self, mut since: String, mut until: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReportFeed {
    pub initialized: bool,
}

impl ReportFeed {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn register(&self, mut source: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn collect(&self, mut since: String, mut until: String, mut category: Option<String>) -> String {
        let mut collected: Vec<String> = Vec::<String>::new();
        let mut errors: Vec<(String, String)> = Vec::<(String, String)>::new();
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn neg_ts(mut at: String) -> f64 {
    0.0_f64
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReportFeed", "SignalSource", "StaticSignalSource"];
