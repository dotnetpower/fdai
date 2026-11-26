#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProgrammaticPipelineBenchmark {
    pub tool_calls: i64,
    pub sequential_context_bytes: i64,
    pub compact_context_bytes: i64,
    pub sequential_estimated_ms: i64,
    pub programmatic_estimated_ms: i64,
}

impl ProgrammaticPipelineBenchmark {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn context_reduction_ratio(&self) -> f64 {
        if (self.sequential_context_bytes) == (0_i64) {
            return 0.0;
        }
        0.0_f64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn latency_reduction_ratio(&self) -> f64 {
        if (self.sequential_estimated_ms) == (0_i64) {
            return 0.0;
        }
        0.0_f64
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn benchmark_programmatic_pipeline(mut sequential_turns: Vec<std::collections::BTreeMap<String, String>>, mut compact_projection: std::collections::BTreeMap<String, String>, mut model_roundtrip_ms: i64, mut broker_roundtrip_ms: i64) -> Result<ProgrammaticPipelineBenchmark, &'static str> {
    if ((model_roundtrip_ms) < (0_i64)) || ((broker_roundtrip_ms) < (0_i64)) {
        return Err("benchmark roundtrip durations MUST be non-negative");
    }
    let compact_bytes: i64 = json_bytes(compact_projection.clone());
    let calls: i64 = (sequential_turns.clone()).len() as i64;
    Ok(ProgrammaticPipelineBenchmark { tool_calls: calls, compact_context_bytes: compact_bytes, sequential_estimated_ms: (calls).saturating_mul((model_roundtrip_ms).saturating_add(broker_roundtrip_ms)), programmatic_estimated_ms: (model_roundtrip_ms).saturating_add((calls).saturating_mul(broker_roundtrip_ms)), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn json_bytes(mut value: std::collections::BTreeMap<String, String>) -> i64 {
    0_i64
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProgrammaticPipelineBenchmark", "benchmark_programmatic_pipeline"];
