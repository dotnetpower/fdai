#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_analysis_rules(mut root: String) -> Result<Vec<String>, &'static str> {
    let mut rules: Vec<String> = Vec::<String>::new();
    Ok(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["load_analysis_rules"];
