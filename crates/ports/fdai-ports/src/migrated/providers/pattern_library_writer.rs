pub trait PatternLibraryWriter {
    fn upsert_pattern(&self, vector: Vec<f64>, action: String);
}

pub const PUBLIC_EXPORTS: &[&str] = &["PatternLibraryWriter"];
