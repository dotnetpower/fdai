#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ImmutableForsetiHistoricalReplaySource {
    pub initialized: bool,
}

impl ImmutableForsetiHistoricalReplaySource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_replay(&self, mut archive_ref: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ImmutableForsetiHistoricalReplaySource"];
