pub const MAX_ACTIVITY_TARGET_CHARS: i64 = 128;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionEndpoint {
    pub method: String,
    pub path: String,
}

impl ExecutionEndpoint {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.method.as_str(), "GET" | "POST" | "PUT" | "PATCH" | "DELETE") { return Err("invalid method literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutionTarget {
    pub interface_kind: String,
    pub service: String,
    pub component: String,
    pub operation: String,
    pub source_kind: Option<String>,
    pub transport: Option<String>,
    #[allow(clippy::type_complexity)]
    pub endpoint: Option<Box<ExecutionEndpoint>>,
}

impl ExecutionTarget {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.interface_kind.as_str(), "internal_query" | "http" | "cli" | "sdk") { return Err("invalid interface_kind literal"); }
        Ok(())
    }
}

