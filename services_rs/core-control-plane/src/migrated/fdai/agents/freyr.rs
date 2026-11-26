#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Freyr {
    pub initialized: bool,
}

impl Freyr {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bind_bus(&mut self, mut bus: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bind_utilization_sampler(&mut self, mut sampler: Option<String>) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn tracked_resource_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn on_typed_message(&self, mut topic: String, mut payload: std::collections::BTreeMap<String, String>) {
        if (topic.clone()) == (String::from("object.cost-anomaly")) {
            return;
        }
        if (topic.clone()) != (String::from("object.event")) {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["Freyr", "SizingRecommendation"];
