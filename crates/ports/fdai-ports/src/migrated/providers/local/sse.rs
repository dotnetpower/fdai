#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LocalSseSink {
    pub initialized: bool,
}

impl LocalSseSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish(&self, mut channel: String, mut event: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn subscribe(&self, mut channel: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn subscribe_2(&self, mut channel: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn subscriber_count(&self, mut channel: String) -> i64 {
        0_i64
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn offer(mut queue: String, mut event: String) {
    if queue.is_empty() {
        return;
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["LocalSseSink"];
