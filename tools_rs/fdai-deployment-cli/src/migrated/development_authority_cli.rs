#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn selected_development_authority(mut args: String, mut cwd: String) -> Result<(Option<String>, bool), &'static str> {
    Ok((None, false))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_development_authority_command(mut args: String, mut profile: Option<String>, mut clear: bool) -> Result<(), &'static str> {
    if (profile.is_none()) && (!(clear)) {
        return Ok(());
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["selected_development_authority", "validate_development_authority_command"];
