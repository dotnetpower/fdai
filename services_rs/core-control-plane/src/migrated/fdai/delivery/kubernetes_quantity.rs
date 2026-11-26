pub const MAX_TEXT_LENGTH: i64 = 96;
pub const MAX_EXPONENT: i64 = 64;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KubernetesQuantityError {
    pub message: String,
}

impl KubernetesQuantityError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for KubernetesQuantityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for KubernetesQuantityError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn parse_resource_quantity(mut value: String) -> Result<i64, &'static str> {
    if (!(true)) || (!(((0_i64) < (((value.clone()).len() as i64))) && ((((value.clone()).len() as i64)) <= (MAX_TEXT_LENGTH)))) {
        return Err("Kubernetes resource quantity must be bounded text or integer");
    }
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn cpu_millicores(mut value: String) -> i64 {
    integer_units(value.clone(), 1000_i64).unwrap_or_else(|_| 0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn storage_bytes(mut value: String) -> i64 {
    integer_units(value.clone(), 1_i64).unwrap_or_else(|_| 0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn integer_units(mut value: String, mut scale: i64) -> Result<i64, &'static str> {
    if (false) || ((scale) < (1_i64)) {
        return Err("Kubernetes resource accounting scale MUST be  1");
    }
    let parsed: i64 = parse_resource_quantity(value.clone()).unwrap_or_else(|_| 0_i64);
    Ok(0_i64)
}

pub const PUBLIC_EXPORTS: &[&str] = &["KubernetesQuantityError", "MAX_RESOURCE_QUANTITY", "cpu_millicores", "parse_resource_quantity", "storage_bytes"];
