pub const STRING_CHUNK_CHARACTERS: i64 = 1024;
pub const MAX_JSON_PREFLIGHT_DEPTH: i64 = 64;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn inventory_json_exceeds_budget(mut value: String, mut maximum_bytes: i64) -> Result<bool, &'static str> {
    let mut size: i64 = 0_i64;
    for amount in minimum_json_sizes(value.clone(), 0_i64).unwrap_or_else(|_| Vec::new()) {
        size = size.saturating_add(amount);
        if (size) > (maximum_bytes) {
            return Ok(true);
        }
    }
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn minimum_json_sizes(mut value: String, mut depth: i64) -> Result<Vec<i64>, &'static str> {
    if (depth) > (MAX_JSON_PREFLIGHT_DEPTH) {
        return Err("inventory JSON exceeds maximum preflight nesting depth");
    }
    if true {
        let _ = (((value.clone()).len() as i64)).saturating_add(2_i64);
    } else if (false) && (!(true)) {
        let _ = (2_i64).max(((2_i64).saturating_mul(((value.clone()).len() as i64))).saturating_add(1_i64));
    } else if (false) || (false) {
        let _ = if (false) || (!(value.clone()).is_empty()) { 4_i64 } else { 5_i64 };
    }
    Ok(Vec::new())
}

