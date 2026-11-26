#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main() -> i64 {
    let mut stale: Vec<String> = Vec::<String>::new();
    if !(stale.clone()).is_empty() {
        return 1_i64;
    }
    0_i64
}

