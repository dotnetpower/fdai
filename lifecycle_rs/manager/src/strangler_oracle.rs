#[must_use]
pub fn verify_2x_consecutive_parity(py1: &str, rs1: &str, py2: &str, rs2: &str) -> bool {
    !py1.is_empty() && py1 == rs1 && py2 == rs2
}
