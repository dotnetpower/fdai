pub const RECEIPT_ROUTE_PATH: &str = "/runtime/integrations/notifications/delivery-receipt";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn make_notification_receipt_route(mut ingress: Option<String>) -> String {
    if ingress.is_none() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["RECEIPT_ROUTE_PATH", "make_notification_receipt_route"];
