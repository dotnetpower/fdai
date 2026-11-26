pub trait ChannelEdgeComposition {
    #[allow(clippy::type_complexity)]
    fn build_runtime(&self, environ: Option<std::collections::BTreeMap<String, String>>) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn create_app(mut environ: Option<std::collections::BTreeMap<String, String>>, mut composition: Option<String>) -> String {
    if environ.is_none() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["create_app"];
