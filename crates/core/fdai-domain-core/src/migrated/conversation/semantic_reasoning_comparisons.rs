#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn comparison_goal(mut goal: String, mut ctx: String) -> Option<String> {
    if goal.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn compare_windows(mut goal: String, mut ctx: String) -> String {
    let mut windows: Vec<(String, String)> = Vec::<(String, String)>::new();
    let mut spans: Vec<i64> = Vec::<i64>::new();
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["comparison_goal"];
