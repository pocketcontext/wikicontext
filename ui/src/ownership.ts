import type { PageSummary, PropertyValue } from "./types";

export const ids = (page: PageSummary, key: string): string[] => {
  const value = page.properties?.[key];
  return Array.isArray(value) ? value : [];
};
export const groupsFor = (page: PageSummary, pages: PageSummary[]) =>
  pages.filter(
    (group) =>
      group.properties?.catalog_type === "group" &&
      ids(group, "members").includes(page.page),
  );
export const ownedBy = (
  groupIds: string[],
  pages: PageSummary[],
  role?: string,
) =>
  pages.filter((page) =>
    (role ? [role] : ["accountable_owners", "backup_owners"]).some((key) =>
      ids(page, key).some((id) => groupIds.includes(id)),
    ),
  );
export function catalogValue(
  page: PageSummary,
  key: string,
  pages: PageSummary[],
): PropertyValue | undefined {
  if (key === "groups")
    return groupsFor(page, pages).map((group) => group.page);
  if (key === "owned_resources" || key === "owned_deployments")
    return ownedBy([page.page], pages).filter(
      (item) =>
        item.properties?.catalog_type ===
        (key === "owned_resources" ? "resource" : "deployment"),
    ).length;
  if (key === "accountable_owners" && !ids(page, key).length)
    return page.properties?.accountable_owner;
  return page.properties?.[key];
}
