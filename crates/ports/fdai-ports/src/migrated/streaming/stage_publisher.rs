#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SseSinkStagePublisher {
    pub initialized: bool,
}

impl SseSinkStagePublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn emit(&self, mut event: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EventBusStagePublisher {
    pub initialized: bool,
}

impl EventBusStagePublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn emit(&self, mut event: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["EventBusStagePublisher", "SseSinkStagePublisher"];
