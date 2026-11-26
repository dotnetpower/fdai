#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PipelineRunnerStatus {
    #[default]
    Succeeded,
    Failed,
    TimedOut,
    Cancelled,
    Incomplete,
}

impl PipelineRunnerStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::TimedOut => "timed_out",
            Self::Cancelled => "cancelled",
            Self::Incomplete => "incomplete",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GeneratedPipelineClientContract {
    pub module_name: String,
    pub class_name: String,
    pub allowed_tools: Vec<String>,
    pub source: String,
    pub source_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PipelineRunSpec {
    pub run_id: String,
    pub source: String,
    pub source_digest: String,
    pub input_json: Vec<String>,
    pub capability_token: String,
    pub client: Box<GeneratedPipelineClientContract>,
    pub timeout_seconds: f64,
    pub max_stdout_bytes: i64,
    pub max_stderr_bytes: i64,
    pub max_final_json_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PipelineToolCall {
    pub run_id: String,
    pub capability_token: String,
    pub call_id: String,
    pub tool_id: String,
    pub arguments_json: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PipelineToolResponse {
    pub ok: bool,
    pub output_json: Option<String>,
    pub error_code: Option<String>,
    pub error_message: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PipelineRunnerOutput {
    pub status: PipelineRunnerStatus,
    pub stdout: String,
    pub stderr: String,
    pub final_json: Option<String>,
    pub duration_ms: i64,
    pub stdout_truncated: bool,
    pub stderr_truncated: bool,
    pub final_json_truncated: bool,
    pub detail: Option<String>,
}

pub trait PipelineToolBroker {
    fn dispatch(&self, call: PipelineToolCall) -> String;
}

pub trait ProgrammaticPipelineRunner {
    fn run(&self, spec: PipelineRunSpec, broker: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["GeneratedPipelineClientContract", "PipelineRunSpec", "PipelineRunnerOutput", "PipelineRunnerStatus", "PipelineToolBroker", "PipelineToolCall", "PipelineToolResponse", "ProgrammaticPipelineRunner"];
