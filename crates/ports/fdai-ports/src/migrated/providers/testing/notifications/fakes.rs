#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecordingChannel {
    pub channel_id: String,
    pub trust_tiers: Vec<String>,
}

impl RecordingChannel {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn arm_delivery_failures(&mut self, mut n: i64) -> Result<(), &'static str> {
        if (n) < (0_i64) {
            return Err("n MUST be  0");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn arm_raises(&mut self, mut n: i64, mut message: Option<String>) -> Result<(), &'static str> {
        if (n) < (0_i64) {
            return Err("n MUST be  0");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn send(&mut self, mut message: String) -> Result<String, &'static str> {
        if message.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn records(&self) -> Vec<String> {
        core::hint::black_box(Vec::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FakeTeamsChannel {
    pub initialized: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FakeSlackChannel {
    pub initialized: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FakeEmailChannel {
    pub initialized: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FakeWebhookChannel {
    pub initialized: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FakePagerDutyChannel {
    pub initialized: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FakeSmsChannel {
    pub initialized: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FakeHilEscalationSink {
    pub initialized: bool,
}

impl FakeHilEscalationSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn escalate(&self, mut message: String, mut reason: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::type_complexity)]
    pub fn entries(&self) -> Vec<(String, String)> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["FakeEmailChannel", "FakeHilEscalationSink", "FakePagerDutyChannel", "FakeSlackChannel", "FakeSmsChannel", "FakeTeamsChannel", "FakeWebhookChannel"];
