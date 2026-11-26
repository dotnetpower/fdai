pub const MAXIMUM_ASSET_BYTES: i64 = 2097152;
pub const MAXIMUM_DIMENSION: i64 = 4096;
pub const MAXIMUM_PIXELS: i64 = 16777216;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PackagedReferenceImage {
    pub content: Vec<u8>,
    pub width: i64,
    pub height: i64,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn verify_reference_image_bytes(mut image: String, mut content: Vec<u8>) -> Result<PackagedReferenceImage, &'static str> {
    if (((content.clone()).len() as i64)) > (MAXIMUM_ASSET_BYTES) {
        return Err("WARA reference image exceeds its byte limit");
    }
    let mut chunks: i64 = 0_i64;
    Ok(PackagedReferenceImage { content: content.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_packaged_reference_image(mut image: String) -> Result<PackagedReferenceImage, &'static str> {
    Ok(verify_reference_image_bytes(image.clone(), Vec::new()).unwrap_or_else(|_| Default::default()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["PackagedReferenceImage", "load_packaged_reference_image", "verify_reference_image_bytes"];
