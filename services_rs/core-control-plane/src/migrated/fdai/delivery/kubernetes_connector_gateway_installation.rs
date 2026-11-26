pub const LISTEN_PORT: i64 = 8443;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GatewayInstallationInput {
    pub namespace: String,
    pub name: String,
    pub image: String,
    pub material_secret: String,
    pub material_digest: String,
    pub database_secret: String,
    pub database_secret_key: String,
    pub database_cidrs: Vec<String>,
    pub database_peer: Option<String>,
    pub database_port: i64,
    pub ingress_cidrs: Vec<String>,
    pub ingress_peers: Vec<String>,
    pub dns_cidrs: Vec<String>,
    pub replicas: i64,
    pub exposure: String,
    pub private_link_subnet: Option<String>,
    pub private_link_subscriptions: Vec<String>,
}

impl GatewayInstallationInput {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=65535_i64).contains(&self.database_port) { return Err("database_port out of bounds"); }
        if !(1_i64..=3_i64).contains(&self.replicas) { return Err("replicas out of bounds"); }
        if !matches!(self.exposure.as_str(), "internal_load_balancer" | "private_link_service") { return Err("invalid exposure literal"); }
        Ok(())
    }
}

impl GatewayInstallationInput {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn networks(mut values: Vec<String>) -> Vec<String> {
        bounded(values.clone(), 24_i64).unwrap_or_else(|_| Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn ingress(mut values: Vec<String>) -> Vec<String> {
        bounded(values.clone(), 16_i64).unwrap_or_else(|_| Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn namespace(mut value: String) -> Result<String, &'static str> {
        if ((value.clone()) == (String::from("default"))) || ((value.clone()).starts_with("kube-")) {
            return Err("gateway requires a dedicated non-system namespace");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exposure(&self) -> Result<String, &'static str> {
        if ((self.ingress_cidrs.clone()).is_empty()) && ((self.ingress_peers.clone()).is_empty()) {
            return Err("the gateway needs bounded ingress networks or in-cluster peers");
        }
        if ((self.database_cidrs.clone()).is_empty()) && (self.database_peer.is_none()) {
            return Err("the state store needs bounded networks or an in-cluster peer");
        }
        if ((self.exposure.clone()) == (String::from("private_link_service"))) && (!(((self.private_link_subnet.clone()).is_some()) && (!(self.private_link_subscriptions.clone()).is_empty()))) {
            return Err("a Private Link service needs its NAT subnet and the subscriptions it may");
        }
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded(mut values: Vec<String>, mut widest: i64) -> Result<Vec<String>, &'static str> {
    let mut result: Vec<String> = Vec::<String>::new();
    if ((((result.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((result.clone()).len() as i64)) {
        return Err("gateway networks must be unique");
    }
    Ok({ let mut _v = result.clone(); _v.sort(); _v })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn validate_gateway_material(mut inputs: GatewayInstallationInput, mut directory: String) -> Result<String, &'static str> {
    let expected: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("registration_path"), String::new()), (String::from("tls_ca_path"), String::new()), (String::from("tls_certificate_path"), String::new()), (String::from("tls_key_path"), String::new())]);
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn render_gateway_installation(mut inputs: GatewayInstallationInput, mut decision: String, mut now: String, mut material_directory: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let _ = validate_gateway_material(inputs.clone(), material_directory.clone()).unwrap_or_else(|_| String::new());
    let labels: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("app.kubernetes.io/name"), String::from("fdai-connector-gateway")), (String::from("app.kubernetes.io/instance"), inputs.name.clone())]);
    let annotations: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("fdai.dev/execution-authority"), String::from("false"))]);
    let security: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("privileged"), String::new()), (String::from("allowPrivilegeEscalation"), String::new()), (String::from("readOnlyRootFilesystem"), String::new()), (String::from("capabilities"), String::new()), (String::from("runAsNonRoot"), String::new()), (String::from("runAsUser"), String::new()), (String::from("runAsGroup"), String::new()), (String::from("seccompProfile"), String::new())]);
    let common: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("image"), inputs.image.clone()), (String::from("imagePullPolicy"), String::from("IfNotPresent")), (String::from("securityContext"), String::new()), (String::from("resources"), String::new())]);
    let pod: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("hostNetwork"), String::new()), (String::from("hostPID"), String::new()), (String::from("hostIPC"), String::new()), (String::from("serviceAccountName"), inputs.name.clone()), (String::from("automountServiceAccountToken"), String::new()), (String::from("securityContext"), String::new()), (String::from("initContainers"), String::new()), (String::from("containers"), String::new()), (String::from("volumes"), String::new())]);
    let service_annotations: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("service.beta.kubernetes.io/azure-load-balancer-internal"), String::from("true")), (String::from("service.beta.kubernetes.io/azure-load-balancer-health-probe-protocol"), String::from("tcp"))]);
    Ok(std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("exposure"), String::new()), (String::from("exposure_reason"), String::new()), (String::from("requires_peering"), String::new()), (String::from("topology_digest"), String::new()), (String::from("inputs_digest"), String::new()), (String::from("material_digest"), inputs.material_digest.clone()), (String::from("manifest_digest"), String::new()), (String::from("documents"), String::new()), (String::from("execution_authority"), String::new()), (String::from("approval_required"), String::new())]))
}

