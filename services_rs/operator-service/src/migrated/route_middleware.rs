#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SecurityHeadersMiddleware {
    pub initialized: bool,
}

impl SecurityHeadersMiddleware {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn call(&self, mut scope: String, mut receive: String, mut send: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LoopbackOnlyMiddleware {
    pub initialized: bool,
}

impl LoopbackOnlyMiddleware {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn call(&self, mut scope: String, mut receive: String, mut send: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn error(mut status: i64, mut message: String) -> String {
    if message.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_loopback_client(mut client: String) -> bool {
    if client.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn header_value(mut scope: String, mut name: Vec<u8>) -> Option<String> {
    if scope.is_empty() {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["LoopbackOnlyMiddleware", "SecurityHeadersMiddleware"];
