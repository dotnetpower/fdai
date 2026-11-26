pub const MAX_KEY_BYTES: i64 = 65536;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn read_key_file(mut path: String, mut private: bool) -> Result<Vec<u8>, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["read_key_file"];
