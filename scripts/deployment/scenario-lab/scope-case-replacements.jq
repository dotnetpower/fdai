# Emit the plan addresses whose replacement only normalizes the letter case of a runner AKS
# role-assignment scope recorded by an out-of-band recovery. Principal, role, and scope stay the
# same grant, so ordinary apply may accept exactly these replacements and still refuses every
# other delete or replacement.
[
  .resource_changes[]? |
  select(
    .address == "azurerm_role_assignment.runner_aks_credentials" or
    .address == "azurerm_role_assignment.runner_aks_admin"
  ) |
  select(.change.actions == ["delete", "create"]) |
  select((.change.replace_paths // []) == [["scope"]]) |
  select(
    (.change.before.scope | type) == "string" and
    (.change.after.scope | type) == "string"
  ) |
  select(.change.before.scope != .change.after.scope) |
  select((.change.before.scope | ascii_downcase) == (.change.after.scope | ascii_downcase)) |
  select(
    (.change.before.principal_id | type) == "string" and
    .change.before.principal_id == .change.after.principal_id
  ) |
  select(
    ((.change.before.role_definition_name // "") | ascii_downcase) ==
    ((.change.after.role_definition_name // "-") | ascii_downcase)
  ) |
  .address
]
