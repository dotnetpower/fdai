pub trait WorkerFactory {
    fn call(&self, environ: std::collections::BTreeMap<String, String>) -> String;
}

