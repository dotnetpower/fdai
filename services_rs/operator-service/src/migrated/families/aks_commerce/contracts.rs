pub trait AksCommerceProjectionReader {
    fn read_latest(&self, service_id: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["AksCommerceProjectionReader"];
