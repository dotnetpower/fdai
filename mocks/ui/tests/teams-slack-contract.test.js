const assert = require("node:assert/strict");
const { existsSync, readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const uiRoot = join(__dirname, "..");
const outcome = readFileSync(join(uiRoot, "assets", "teams-slack-outcome-template.html"), "utf8");
const teams = readFileSync(join(uiRoot, "conversation-teams.html"), "utf8");
const slack = readFileSync(join(uiRoot, "conversation-slack.html"), "utf8");
const directLine = readFileSync(join(uiRoot, "conversation-direct-line.html"), "utf8");
const directLineSetup = readFileSync(join(uiRoot, "providers", "direct-line-setup.html"), "utf8");
const functionBody = (name, nextName) => outcome.slice(
  outcome.indexOf(`function ${name}(`),
  outcome.indexOf(`function ${nextName}(`),
);
const teamsIncidentCard = functionBody("teamsIncidentCard", "teamsConversationApp");
const teamsConversation = functionBody("teamsConversationApp", "slackConversationApp");
const teamsSurface = `${teamsIncidentCard}\n${teamsConversation}`;
const slackConversation = functionBody("slackConversationApp", "directLineChannelApp");
const directLineChannel = functionBody("directLineChannelApp", "nativeConversationApp");
const teamsApproval = functionBody("teamsApprovalApp", "slackApprovalApp");
const slackApproval = functionBody("slackApprovalApp", "teamsCommandApp");
const teamsCommand = functionBody("teamsCommandApp", "slackCommandApp");
const slackCommand = functionBody("slackCommandApp", "teamsDeliveryDegradedApp");
const teamsDelivery = functionBody("teamsDeliveryDegradedApp", "slackDeliveryDegradedApp");
const slackDelivery = functionBody("slackDeliveryDegradedApp", "fdaiAnswerCard");
const connectionDetail = functionBody("connectionDetail", "groupedProviders");
const lifecycleConnections = functionBody("lifecycleConnections", "lifecycleAddIntegration");
const lifecycleAddIntegration = functionBody("lifecycleAddIntegration", "lifecycleConnectionDetails");
const lifecycleConnectionDetails = functionBody("lifecycleConnectionDetails", "lifecycleActivity");
const providerInstallPreview = functionBody("providerInstallPreview", "wizardStepBody");

test("integration hub template exposes the lifecycle", () => {
  assert.match(outcome, /data-outcome-state="epic-1"/);
  assert.match(outcome, /view: "lifecycle"/);
  assert.match(outcome, /const labels = \{ connections: copy\(.+add: copy\(.+activity: copy\(/);
  assert.match(outcome, /data-tab="\$\{id\}"/);
});

test("integration hub distinguishes connected providers from configuration prerequisites", () => {
  assert.match(outcome, /Teams operations connection/);
  ["Microsoft Teams", "Slack", "Direct Line custom channel", "Email", "Generic webhook"]
    .forEach((provider) => assert.match(outcome, new RegExp(provider)));
  assert.match(outcome, /definition\.connectable && !connections\.some/);
  assert.match(outcome, /data-add="\$\{providerId\}"/);
  assert.match(outcome, /const target = text\(connection\.name\)/);
  assert.match(outcome, /action === "test".+actor: "agent:Heimdall".+transition: "healthy -> healthy".+evidence: "evidence-demo-108"/);
  assert.match(outcome, /action === "disable".+actor: "operator@example\.com".+transition: "healthy -> disable requested".+evidence: "evidence-demo-109"/);
  assert.match(outcome, /connections\.push\(.+capabilities: \{ notifications:.+approvals:.+conversation:/);
});

test("legacy Skype archive surfaces are retired", () => {
  assert.equal(existsSync(join(uiRoot, "conversation-skype.html")), false);
  assert.equal(existsSync(join(uiRoot, "providers", "skype-install.html")), false);
  assert.doesNotMatch(outcome, /skype/i);
});

test("Direct Line is a notification-only custom channel outside app installation", () => {
  assert.match(outcome, /directline: \{ name: "Direct Line custom channel", mark: "DL", category: "notification-delivery"/);
  assert.match(outcome, /directline: \{[^\n]*connectable: false[^\n]*preview: "conversation-direct-line\.html"/);
  assert.match(outcome, /Protected deployment configuration required · rehearsal first/);
  assert.match(lifecycleAddIntegration, /definition\.preview/);
  assert.match(lifecycleAddIntegration, /Preview channel/);
  assert.match(directLine, /assets\/teams-slack-outcome-page\.js" data-outcome-state="issue-7"/);
  assert.match(outcome, /currentState === "issue-7" \? "directline"/);
  assert.match(outcome, /if \(provider === "directline"\) return directLineChannelApp\(\)/);
  assert.match(outcome, /conversation-direct-line\.html" class="is-active" aria-current="page"/);
  assert.match(outcome, /providers\/direct-line-setup\.html/);
  assert.match(directLineChannel, /A2 operational alerts and A4 digests only/);
  assert.match(directLineChannel, /Approvals \(A1\) and conversations or commands \(A3\) are unavailable here/);
  assert.match(directLineChannel, /stay in protected deployment configuration and never appear here/);
  assert.match(directLineChannel, /activated by deployment configuration after a zero-send rehearsal/);
  assert.match(directLineChannel, /Replies, approvals, and commands are not accepted in this channel/);
  assert.match(directLineChannel, /aria-describedby="direct-line-composer-note"/);
  assert.match(directLineChannel, /<input disabled aria-label=/);
  assert.ok(directLineChannel.includes('<button disabled aria-label="${text(copy("보내기 사용 불가", "Send unavailable"))}"'));
});

test("Direct Line cards carry the shared incident without approval or command controls", () => {
  ["incident.id", "incident.correlationId", "incident.auditId", "incident.ticketId", "incident.rollbackId"]
    .forEach((field) => assert.ok(directLineChannel.includes(field), field));
  assert.match(directLineChannel, /data-direct-line-card="a2-operational-alert"/);
  assert.match(directLineChannel, /data-direct-line-card="a4-digest"/);
  assert.match(directLineChannel, /Huginn[\s\S]+Forseti[\s\S]+Thor[\s\S]+Vidar/);
  ["Rendered and bounded", "Durable intent", "Provider accepted", "Publication pending", "Publication observed"]
    .forEach((label) => assert.match(directLineChannel, new RegExp(label)));
  assert.match(directLineChannel, /Only the activity-sha256 digest is recorded/);
  assert.match(directLineChannel, /Independent publication receipt required/);
  assert.doesNotMatch(directLineChannel, /<button(?![^>]*\bdisabled\b)/);
  assert.doesNotMatch(directLineChannel, /<a\s/);
  assert.doesNotMatch(directLineChannel, /Action\.Submit|onclick=|onsubmit=|data-approve|Reauthenticate/i);
  assert.doesNotMatch(directLineChannel, /\bapprove\b|\breject\b|Executing agent/i);
});

test("Direct Line setup boundary names protected references without collecting credentials", () => {
  assert.match(directLineSetup, /Rehearsal is the default mode/);
  assert.match(directLineSetup, /zero external sends/);
  assert.match(directLineSetup, /accepted, never as delivered/);
  assert.match(directLineSetup, /authenticated publication receipt/);
  assert.match(directLineSetup, /relay-reflected failure such as HTTP 502 stays ambiguous and is never resent automatically/);
  assert.match(directLineSetup, /must deduplicate on the activity idempotency key, and the router is the only retry layer/);
  ["endpoint_env", "conversation_id_env", "secret_env"]
    .forEach((field) => assert.match(directLineSetup, new RegExp(`<code>${field}</code>`)));
  assert.match(directLineSetup, /no approvals \(A1\), conversations, or commands \(A3\)/);
  assert.match(directLineSetup, /does not collect, store, or test any credential/);
  assert.match(directLineSetup, /href="\.\.\/conversation-direct-line\.html"/);
  assert.doesNotMatch(directLineSetup, /<input|<form|<button|OAuth|Install and connect/i);
  assert.doesNotMatch(directLineSetup, /https?:\/\//);
});

test("integration hub separates connected instances, addable services, and delivery prerequisites", () => {
  assert.match(lifecycleConnections, /const entries = connections\.map/);
  assert.match(lifecycleConnections, /data-manage="\$\{connection\.id\}"/);
  assert.match(lifecycleConnections, /data-open-add/);
  assert.doesNotMatch(lifecycleConnections, /connectionDetail\(/);
  assert.match(lifecycleAddIntegration, /definition\.connectable && !connections\.some/);
  assert.match(lifecycleAddIntegration, /data-add="\$\{providerId\}"/);
  assert.match(lifecycleAddIntegration, /Separate configuration/);
  assert.match(lifecycleAddIntegration, /not app-install integrations/);
  assert.match(outcome, /activeTab = "details"/);
  assert.match(lifecycleConnectionDetails, /data-back-to-connections/);
  assert.match(outcome, /activeTab = "connections"/);
});

test("setup preserves provider boundaries and recovery states", () => {
  [
    "Review permissions and roles",
    "Expected installation flow",
    "Confirm authorization result",
    "Configure destinations and capabilities",
    "Verify connection",
  ].forEach((stage) => assert.match(outcome, new RegExp(stage)));

  ["pending", "denied", "callback", "partial", "degraded", "revoked"].forEach((scenario) => {
    assert.ok(outcome.includes(`["${scenario}"`));
  });
  assert.match(outcome, /Entra consent, app installation, and team or chat resource consent are separate checkpoints/);
  assert.match(outcome, /Install directly in Slack or request administrator approval/);
  assert.match(providerInstallPreview, /Teams admin allows or approves app availability/);
  assert.match(providerInstallPreview, /Confirm Entra consent separately/);
  assert.match(providerInstallPreview, /Add the FDAI Operations app for the user or team/);
  assert.match(providerInstallPreview, /Return to FDAI to select shared channels and verify capabilities/);
  assert.match(providerInstallPreview, /Choose a workspace in the Add to Slack surface/);
  assert.match(providerInstallPreview, /app and bot capabilities/);
  assert.match(providerInstallPreview, /Return to FDAI after Slack authorization/);
  assert.match(providerInstallPreview, /invite the app when required/);
  assert.match(providerInstallPreview, /does not perform sign-in or installation/);
});

test("setup discloses external authorization and outbound data boundaries", () => {
  assert.match(outcome, /FDAI does not collect provider credentials/);
  assert.match(outcome, /Requested capabilities: notifications, approval callbacks, conversation ingress, and replies/);
  assert.match(outcome, /Outbound data: redacted messages, evidence IDs, and action state/);
  assert.match(outcome, /Record requesting user and executing agent identities separately/);
  assert.match(outcome, /Push and pull enablement are not derived from each other/);
});

test("connection detail separates installation, pairing, and shared-channel identity", () => {
  assert.match(connectionDetail, /Provider installation/);
  assert.match(connectionDetail, /FDAI pairing/);
  assert.match(connectionDetail, /Paired · provider authorization confirmed/);
  assert.match(connectionDetail, /FDAI channel workload identity · requester attribution remains separate/);
  assert.match(connectionDetail, /Allowlisted shared channels only · no DM or personal scope inherited/);
});

test("management exposes lifecycle impact and per-capability fallback", () => {
  assert.match(outcome, /Lifecycle change impact/);
  assert.match(outcome, /Disable or remove stops new delivery and conversation ingress while preserving prior evidence/);
  assert.match(outcome, /Per-capability trust preserved/);
  assert.match(outcome, /approval failures queue for HIL/);
  assert.match(outcome, /Rate-limit backoff visible/);
  assert.match(outcome, /Authority verified before capability enablement/);
});

test("activity separates requester, actor, transition, and evidence", () => {
  assert.match(outcome, /actor: "agent:Heimdall", requester: "operator@example\.com"/);
  assert.match(outcome, /Requested by/);
  assert.match(outcome, /State transition/);
  assert.match(outcome, /item\.evidence/);
  assert.match(outcome, /Executing agent.+Bragi.+Requested by.+operator@example\.com.+Action state.+read-only/);
  assert.match(outcome, /slack-block-kit.+Conversational agent.+Bragi.+Decision agent.+Forseti.+Executing agent.+Thor/);
});

test("native Teams and Slack routes remain independently addressable", () => {
  assert.match(teams, /data-outcome-state="issue-4"/);
  assert.match(slack, /data-outcome-state="issue-5"/);
  assert.match(outcome, /function teamsConversationApp\(\)/);
  assert.match(outcome, /function slackConversationApp\(\)/);
});

test("both native channels render one shared incident identity", () => {
  ["INC-240715-01", "inc-01J2-API-LATENCY", "OPS-1842", "rbk-01J2-773", "aud-01J2-941"]
    .forEach((id) => assert.match(outcome, new RegExp(id)));
  assert.match(teamsConversation, /operationalIncident\.id/);
  assert.match(slackConversation, /const incident = operationalIncident/);
});

test("incident activity preserves detector decision executor verifier order", () => {
  assert.match(outcome, /Huginn.+Forseti.+Thor.+Vidar/);
  assert.match(slackConversation, /Huginn.+Forseti.+Thor.+Vidar/);
  assert.match(outcome, /7 latency alerts and 1 deployment event/);
});

test("automatic remediation exposes authority and bounded execution", () => {
  assert.match(outcome, /AUTO · T0 · 1\.00/);
  assert.match(slackConversation, /AUTO · T0 · confidence 1\.00/);
  assert.match(outcome, /pr_native/);
  assert.match(outcome, /limited to one revision/);
});

test("Vidar owns visible post-rollback verification", () => {
  assert.match(outcome, /Five-minute baseline verification in progress · 3\/5 probes passed/);
  assert.match(slackConversation, /frozen pre-change baseline.+Three of five probes passed/);
  assert.match(slackConversation, /verification:3\/5/);
});

test("Teams and Slack have complementary operational roles", () => {
  assert.match(teamsSurface, /Customer impact/);
  assert.match(teamsSurface, /No operator intervention is needed now/);
  assert.match(slackConversation, /Execution evidence, rollback revision, and independent verification/);
  assert.match(slackConversation, /Execution thread open/);
});

test("automatic T0 flow has no approval control or Bragi execution claim", () => {
  assert.doesNotMatch(teamsSurface, /approve|reject|approval/i);
  assert.doesNotMatch(slackConversation, /approve|reject|approval/i);
  assert.doesNotMatch(teamsSurface, /Executing agent[^<]+Bragi/);
  assert.doesNotMatch(slackConversation, /Executing agent[^<]+Bragi/);
  assert.match(teamsSurface, /Conversational agent.+Bragi/);
  assert.match(slackConversation, /Conversational agent.+Bragi/);
});

test("native scenario routing defaults safely and preserves provider routes", () => {
  assert.match(outcome, /nativeScenarioIds = new Set\(\["t0-auto", "a1-approval", "a3-command", "delivery-degraded"\]\)/);
  assert.match(outcome, /nativeScenarioIds\.has\(requestedNativeScenario\) \? requestedNativeScenario : "t0-auto"/);
  assert.match(outcome, /conversation-teams\.html.+conversation-slack\.html/);
  assert.match(outcome, /nativeScenario === "a1-approval"/);
  assert.match(outcome, /nativeScenario === "a3-command"/);
  assert.match(outcome, /nativeScenario === "delivery-degraded"/);
});

test("A1 approval remains Entra-authorized, distinct, expiring, and fail-closed", () => {
  [teamsApproval, slackApproval].forEach((surface) => {
    assert.match(surface, /apr_7F3K9Q2M/);
    assert.match(surface, /Var/);
    assert.match(surface, /Entra.+reauth|reauthentication.+Entra/i);
    assert.match(surface, /1\s*\/\s*2/);
    assert.match(surface, /self-approval.+denied|self-approval.+거부/i);
    assert.match(surface, /TTL/);
    assert.match(surface, /HIL queue/);
    assert.match(surface, /no email fallback|이메일 fallback 없음/i);
  });
  assert.match(teamsApproval, /Expiry or callback verification failure results in no execution/);
  assert.match(slackApproval, /no change executes/);
});

test("A3 commands enforce roles and terminate writes at a draft PR", () => {
  [teamsCommand, slackCommand].forEach((surface) => {
    assert.match(surface, /Viewer/);
    assert.match(surface, /Contributor/);
    assert.match(surface, /Owner/);
    assert.match(surface, /draft PR/i);
    assert.match(surface, /live (resource )?mutation/i);
    assert.match(surface, /403 role_insufficient/);
    assert.match(surface, /audit-demo-a3-denied-403/);
  });
  assert.match(teamsCommand, /read commands are allowed for Viewer and above/i);
  assert.match(slackCommand, /Slack sender identity alone granted no authority/);
});

test("degraded delivery separates retry, ambiguity, and A1 fallback", () => {
  [teamsDelivery, slackDelivery].forEach((surface) => {
    assert.match(surface, /HTTP 429/);
    assert.match(surface, /bounded.+retri|2 backoff/i);
    assert.match(surface, /ambiguous|모호|response may be lost/i);
    assert.match(surface, /not retry automatically|automatic retry stopped|자동 재시도/i);
    assert.match(surface, /HIL queue/);
    assert.match(surface, /no email fallback|이메일 fallback/i);
  });
  assert.match(teamsDelivery, /Channel delivery success is not treated as approval or acknowledgement success/);
  assert.match(slackDelivery, /Provider delivery was not promoted into an authority outcome/);
  [teamsDelivery, slackDelivery].forEach((surface) => {
    assert.match(surface, /configured A2 notification fallback/);
    assert.match(surface, /A2 category (?:is )?preserved/);
  });
  assert.doesNotMatch(outcome, /ServiceNow/);
});
