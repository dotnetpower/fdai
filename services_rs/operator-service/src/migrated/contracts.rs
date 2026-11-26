pub trait AsgiApplication {
    fn call(&self, scope: String, receive: String, send: String) -> String;
}

pub trait ApplicationLifecycle {
    fn start(&self) -> String;
}

pub trait ApplicationFactory {
    fn call(&self, environ: std::collections::BTreeMap<String, String>) -> String;
}

pub trait ApplicationFactoryResolver {
    fn call(&self, reference: String) -> String;
}

pub trait ServerRunner {
    fn call(&self, factory_reference: String, factory: bool, host: String, port: i64) -> String;
}

