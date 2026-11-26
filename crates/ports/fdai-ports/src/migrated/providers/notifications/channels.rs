pub trait TeamsChannel {
    fn send(&self, message: String) -> String;
}

pub trait SlackChannel {
    fn send(&self, message: String) -> String;
}

pub trait EmailChannel {
    fn send(&self, message: String) -> String;
}

pub trait WebhookChannel {
    fn send(&self, message: String) -> String;
}

pub trait PagerDutyChannel {
    fn send(&self, message: String) -> String;
}

pub trait SmsChannel {
    fn send(&self, message: String) -> String;
}

pub trait DirectLineChannel {
    fn send(&self, message: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["DirectLineChannel", "EmailChannel", "PagerDutyChannel", "SlackChannel", "SmsChannel", "TeamsChannel", "WebhookChannel"];
