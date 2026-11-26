pub trait ConsoleUpdatePublicationTarget {
    fn subscription_id(&self) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn publish_console_update(mut source_root: String, mut work_dir: String, mut archive: String, mut archive_digest: String, mut target: String, mut scripts: String, mut timeout_seconds: i64, mut verify_only: bool, mut verify_service_contracts: bool) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["publish_console_update"];
