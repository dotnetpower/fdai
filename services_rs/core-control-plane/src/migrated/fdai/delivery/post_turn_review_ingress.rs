pub const SEEN_LIMIT: i64 = 4096;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostTurnReviewRequestConsumer {
    pub publisher: Option<String>,
    pub group_id: String,
}

pub trait BragiPostTurnPublisher {
    fn publish_post_turn_review(&self, review: String) -> String;
}

impl PostTurnReviewRequestConsumer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut bus: String, mut stop: String) {
        if bus.is_empty() {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn handle(&self, mut bus: String, mut envelope: String) -> Result<bool, &'static str> {
        let bragi: Option<String> = self.bragi();
        if bragi.is_none() {
            return Ok(false);
        }
        let _ = self.remember(String::new());
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn bragi(&self) -> Option<String> {
        core::hint::black_box(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn remember(&self, mut key: String) {
        if key.is_empty() {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostTurnReviewRequestConsumer"];
