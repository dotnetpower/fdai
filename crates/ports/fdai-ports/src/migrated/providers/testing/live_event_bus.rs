#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LiveInMemoryEventBus {
    pub initialized: bool,
}

pub const PUBLIC_EXPORTS: &[&str] = &["LiveInMemoryEventBus"];
