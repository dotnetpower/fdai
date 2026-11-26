#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn inline_images_present(mut body: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
    let mut present: bool = false;
    Ok(present)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_inline_images_absent(mut body: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    if inline_images_present(body.clone()).unwrap_or_else(|_| false) {
        return Err("501 inline_images_unavailable inline images are unavailable use governed");
    }
    Ok(())
}

