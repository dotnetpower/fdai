/** Authorization relationships belong to access evidence, not the operational resource roster. */
export function isOperationalResourceType(resourceType: string): boolean {
  return resourceType !== "authorization.role-assignment";
}
