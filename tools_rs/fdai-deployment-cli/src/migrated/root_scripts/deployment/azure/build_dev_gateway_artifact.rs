pub const EXCLUDED_NAMES: &[&str] = &[".funcignore", "README.md"];
pub const REQUIRED: &[&str] = &["function_app.py", "gateway.py", "host.json", "requirements.txt"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build(mut source: String, mut target: String) -> Result<Vec<String>, &'static str> {
    if source.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn main() -> Result<i64, &'static str> {
    let _ = build(String::new(), String::new()).unwrap_or_else(|_| Vec::new());
    Ok(0_i64)
}

