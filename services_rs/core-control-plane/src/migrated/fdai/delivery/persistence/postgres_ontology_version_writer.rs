#[derive(Clone, Debug, Default, PartialEq)]
pub struct VersionedGraphWrite {
    pub base_version: String,
    pub base_epoch: i64,
    pub prepared_version: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn begin_versioned_write(mut connection: String) -> Result<Option<VersionedGraphWrite>, &'static str> {
    Ok(Some(VersionedGraphWrite::default()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn finish_versioned_write(mut connection: String, mut write: Option<VersionedGraphWrite>) -> Result<(), &'static str> {
    let Some(mut write) = write.clone() else { return Ok(()); };
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn seal_versioned_write(mut connection: String, mut write: VersionedGraphWrite) -> Result<VersionedGraphWrite, &'static str> {
    Ok(VersionedGraphWrite::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn materialize_identity_changes(mut connection: String, mut version: String) -> Result<(), &'static str> {
    if connection.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

