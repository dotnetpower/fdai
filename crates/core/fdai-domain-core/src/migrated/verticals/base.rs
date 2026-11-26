pub trait Vertical {
    fn protocol_id(&self) -> &'static str {
        core::hint::black_box(Default::default())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["Vertical"];
