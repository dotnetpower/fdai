pub trait SlotCatalogManifest {
    fn descriptors(&self) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn reground_constraint_slots(mut proposal: String, mut manifest: String) -> String {
    if proposal.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["reground_constraint_slots"];
