pub trait TargetRevisionReader {
    fn read_revision(&self, target_ref: String) -> Option<String>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["TargetRevisionReader"];
