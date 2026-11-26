pub trait HandoverSemanticSource {
    fn read(&self, notice: String) -> Vec<String>;
}

pub trait HandoverSemanticPackageStore {
    fn claim(&self, key: String, identity: std::collections::BTreeMap<String, String>) -> bool;
    #[allow(clippy::type_complexity)]
    fn read(&self, key: String) -> Option<std::collections::BTreeMap<String, String>>;
    fn complete(&self, key: String, identity: std::collections::BTreeMap<String, String>, package: std::collections::BTreeMap<String, String>);
    fn reconcile(&self, notice: String, withdrawn: bool) -> i64;
}

pub trait HandoverSemanticCompiler {
    fn compile(&self, notice: String) -> String;
}

pub trait HandoverSemanticReviewer {
    fn review(&self, notice: String, receipt: String) -> String;
    fn maintain(&self, notice: String, withdrawn: bool) -> i64;
}

pub const PUBLIC_EXPORTS: &[&str] = &["HandoverSemanticCompiler", "HandoverSemanticPackageStore", "HandoverSemanticReviewer", "HandoverSemanticSource"];
