pub trait ServerRunner {
    fn call(&self, factory_reference: String, factory: bool, host: String, port: i64) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn run_uvicorn(mut factory_reference: String, mut factory: bool, mut host: String, mut port: i64) -> String {
    if factory_reference.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn serve(mut environ: Option<std::collections::BTreeMap<String, String>>, mut runner: String) -> i64 {
    0_i64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main() -> i64 {
    serve(None, String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["main", "serve"];
