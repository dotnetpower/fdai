pub trait Stage {
    fn handle(&self, ctx: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["Stage"];
