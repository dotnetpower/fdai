#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn measure(mut document: String) -> String {
    if document.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn main() -> Result<i64, &'static str> {
    let result: String = measure(String::new());
    Ok(0_i64)
}

