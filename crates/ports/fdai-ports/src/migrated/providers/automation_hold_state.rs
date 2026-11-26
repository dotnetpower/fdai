pub trait AutomationHoldStateReader {
    #[allow(clippy::type_complexity)]
    fn read_hold_record(&self, target_ref: String) -> Option<std::collections::BTreeMap<String, String>>;
}

pub trait HoldReleaseAuthorizationReader {
    #[allow(clippy::type_complexity)]
    fn read_dispatch_authorization(&self, target_ref: String, process_id: String, step_id: String) -> Option<std::collections::BTreeMap<String, String>>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["AutomationHoldStateReader", "HoldReleaseAuthorizationReader"];
