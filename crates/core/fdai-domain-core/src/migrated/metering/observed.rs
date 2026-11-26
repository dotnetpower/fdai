pub trait MeteringStore {
    fn protocol_id(&self) -> &'static str {
        core::hint::black_box(Default::default())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ObservedMeteringStore {
    pub initialized: bool,
}

impl ObservedMeteringStore {
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
    pub async fn observe(&self, mut invocation: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ObservedMeteringStore"];
