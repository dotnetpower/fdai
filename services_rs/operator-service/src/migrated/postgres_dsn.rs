#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn normalize_psycopg_dsn(mut value: String) -> Result<String, &'static str> {
    let prefix: String = String::from("postgresql+psycopg://");
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["normalize_psycopg_dsn"];
