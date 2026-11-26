pub const MAX_SHAPE_TOKENS: i64 = 24;

pub const LIST_READING: &str = "reading:list";
pub const BEYOND_LIST_READING: &str = "reading:beyond_list";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn reads_beyond_list(mut form: String) -> bool {
    if form.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn form_shape(mut form: String) -> Vec<String> {
    let mut tokens: Vec<String> = vec![if reads_beyond_list(form.clone()) { String::from(BEYOND_LIST_READING) } else { String::from(LIST_READING) }];
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["BEYOND_LIST_READING", "LIST_READING", "MAX_SHAPE_TOKENS", "form_shape", "reads_beyond_list"];
