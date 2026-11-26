pub const EVALUATION_API_VERSION: &str = "1.0";
pub trait EvaluationSession {
    fn session_id(&self) -> String;
}

pub trait EvaluationHost {
    fn api_version(&self) -> String;
}

pub trait EvaluationAdapter {
    fn start(&self) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["EVALUATION_API_VERSION", "EvaluationAdapter", "EvaluationHost", "EvaluationSession"];
