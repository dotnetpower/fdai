pub trait HandoverGoalProjectionReader {
    fn read_page(&self, limit: i64, offset: i64) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["HandoverGoalProjectionReader"];
