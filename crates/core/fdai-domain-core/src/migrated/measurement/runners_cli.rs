#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MeasurementMode {
    #[default]
    Baseline,
    Growth,
}

impl MeasurementMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Baseline => "baseline",
            Self::Growth => "growth",
        }
    }
}

pub const ENV_MODE: &str = "FDAI_MEASUREMENT_MODE";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resolve_mode() -> Option<MeasurementMode> {
    core::hint::black_box(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn run_baseline() -> i64 {
    3_i64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn run_growth() -> i64 {
    3_i64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn configure_logging() {
    core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn amain() -> i64 {
    let _ = configure_logging();
    let mode: Option<MeasurementMode> = resolve_mode();
    if mode.is_none() {
        return 2_i64;
    }
    run_growth().await
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main() -> i64 {
    0_i64
}

