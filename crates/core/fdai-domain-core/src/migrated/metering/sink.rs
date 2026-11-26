pub const DEFAULT_MAX_RECORDS: i64 = 50000;

pub trait MeteringSink {
    fn record(&self, invocation: String);
}

pub trait MeteringReader {
    fn invocations(&self) -> Vec<String>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryMeteringSink {
    pub initialized: bool,
}

impl InMemoryMeteringSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record(&self, mut invocation: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn invocations(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn dunder_len(&self) -> i64 {
        0_i64
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryMeteringSink", "MeteringReader", "MeteringSink"];
