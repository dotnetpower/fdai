pub const CHUNK_BYTES: i64 = 65536;

pub const BOUNDED_ACCEPT_ENCODING: &str = "gzip, deflate";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ResponseBodyTooLargeError {
    pub message: String,
}

impl ResponseBodyTooLargeError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ResponseBodyTooLargeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ResponseBodyTooLargeError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn read_bounded_response(mut response: String, mut max_bytes: Option<i64>) -> Result<Vec<u8>, &'static str> {
    let mut raw_deflate_fallback: bool = false;
    let mut wire_bytes: i64 = 0_i64;
    Ok(Vec::new())
}

