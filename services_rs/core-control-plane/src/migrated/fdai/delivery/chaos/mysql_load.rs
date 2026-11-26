pub const DEFAULT_ITERATIONS: i64 = 20000000;

pub const LOAD_QUERY: &str = "SELECT BENCHMARK(%d, SHA2(RAND(), 512))";
pub trait Connection {
    fn cursor(&self) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzMysqlQueryLoadInjector {
    pub initialized: bool,
}

impl AzMysqlQueryLoadInjector {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn worker(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn inject(&mut self, mut target: String, mut params: std::collections::BTreeMap<String, String>) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn stop(&mut self, mut target: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureMonitorDbCpuProbe {
    pub initialized: bool,
}

impl AzureMonitorDbCpuProbe {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observed(&self, mut signal: String, mut targets: Vec<String>) -> bool {
        self.initialized
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzMysqlQueryLoadInjector", "AzureMonitorDbCpuProbe"];
