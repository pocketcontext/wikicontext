import { expect, test } from "vitest";
import {
  navigationGroups,
  navigationKeys,
  UNASSIGNED_TOPIC,
  validCatalogColumn,
} from "./navigation";
import type { PageSummary } from "./types";
const page = (
  slug: string,
  properties: PageSummary["properties"] = {},
): PageSummary => ({
  id: `rev-${slug}`,
  page: `page-${slug}`,
  slug,
  title: slug,
  summary: "",
  kind: "concept",
  properties,
});
test("discovers explicit multi-membership, unique per-group counts and unassigned pages", () => {
  const a = page("a", { topics: ["science", "science", "engineering"] }),
    b = page("b"),
    def = page("science", {
      navigation_kind: "topic",
      topics: ["science"],
      navigation_order: 0,
    });
  def.title = "Scientific work";
  def.summary = "Selected topic description";
  const groups = navigationGroups([a, a, b, def], "topic");
  expect(groups.map((g) => g.id)).toEqual([
    "science",
    "engineering",
    UNASSIGNED_TOPIC,
  ]);
  expect(groups[0]).toMatchObject({
    title: "Scientific work",
    description: "Selected topic description",
    pages: [a],
  });
  expect(groups[1].pages).toEqual([a]);
  expect(groups[2].pages).toEqual([b]);
  expect(groups.flatMap((g) => g.pages)).not.toContain(def);
});
test("selected publication alone controls definitions, labels, columns and membership", () => {
  const item = page("tool", { catalogs: ["developer-tools"] });
  const old = page("developer-tools", {
    navigation_kind: "catalog",
    catalog_columns: ["title", "provider"],
    catalog_sort: "-provider",
  });
  old.title = "Earlier tools";
  const newer = {
    ...old,
    id: "new-revision",
    title: "Current tools",
    properties: { ...old.properties, catalog_columns: ["title", "license"] },
  };
  expect(navigationGroups([item, old], "catalog")[0]).toMatchObject({
    title: "Earlier tools",
    columns: ["title", "provider"],
    sort: "-provider",
    pages: [item],
  });
  expect(navigationGroups([item, newer], "catalog")[0]).toMatchObject({
    title: "Current tools",
    columns: ["title", "license"],
    sort: "title",
  });
  expect(navigationGroups([item], "catalog")[0].title).toBe("Developer tools");
  expect(navigationGroups([old], "catalog")[0].pages).toEqual([]);
});
test("ignores malformed properties, preserves valid other/all keys and limits fields", () => {
  expect(
    navigationKeys(
      page("test", {
        topics: ["other", "all", "bad_key", "bad/slash", "x".repeat(65)],
      }),
      "topic",
    ),
  ).toEqual(["other", "all"]);
  expect(navigationKeys(page("wrong", { topics: "science" }), "topic")).toEqual(
    [],
  );
  const def = page("safe", {
    navigation_kind: "catalog",
    catalog_columns: [
      "constructor",
      "prototype",
      "<script>",
      "title",
      "summary",
      ...Array.from({ length: 20 }, (_, i) => `field_${i}`),
    ],
    catalog_sort: "__proto__",
    navigation_order: -2,
  });
  const group = navigationGroups([def], "catalog")[0];
  expect(group.columns).toHaveLength(12);
  expect(group.columns).not.toContain("constructor");
  expect(group.sort).toBe("title");
});

test("catalog columns follow backend display-field exceptions and allow explicit navigation metadata", () => {
  const allowed = [
    "title",
    "summary",
    "slug",
    "kind",
    "provider",
    "topics",
    "catalogs",
    "navigation_kind",
    "navigation_order",
    "catalog_columns",
    "catalog_sort",
  ];
  for (const key of allowed) expect(validCatalogColumn(key), key).toBe(true);
  const group = navigationGroups(
    [
      page("metadata", {
        navigation_kind: "catalog",
        catalog_columns: allowed,
        catalog_sort: "topics",
      }),
    ],
    "catalog",
  )[0];
  expect(group.columns).toEqual(allowed);
  expect(group.sort).toBe("topics");
  for (const key of [
    "wikicontext_page",
    "wikicontext_revision",
    "id",
    "page",
    "page_id",
    "revision",
    "revision_id",
    "publication",
    "publication_id",
    "body",
    "archived",
    "run",
    "base_revision",
    "created",
    "updated",
    "created_by",
    "updated_by",
    "properties",
    "property_evidence",
    "constructor",
    "prototype",
    "__proto__",
  ])
    expect(validCatalogColumn(key), key).toBe(false);
  for (const key of [
    null,
    123,
    true,
    "",
    "Title",
    "property-name",
    "key.with.dot",
    "x".repeat(65),
  ])
    expect(validCatalogColumn(key), String(key)).toBe(false);
  expect(validCatalogColumn("x".repeat(64))).toBe(true);
});

test("legacy publications retain inferred topics until explicit metadata is published", () => {
  const old = page("platform-security-guide");
  expect(navigationGroups([old], "topic")[0].id).toBe("platform-security");
  const adopted = {
    ...old,
    id: "new-revision",
    properties: { topics: ["engineering"] },
  };
  const unassigned = page("company-strategy");
  expect(
    navigationGroups([adopted, unassigned], "topic").map((group) => group.id),
  ).toEqual(["engineering", UNASSIGNED_TOPIC]);
  expect(navigationGroups([old], "topic")[0].id).toBe("platform-security");
  expect(old.properties).toEqual({});
  expect(
    navigationGroups([{ ...old, properties: { topics: [] } }], "topic")[0].id,
  ).toBe(UNASSIGNED_TOPIC);
});

test("malformed historical navigation metadata does not opt a legacy publication into explicit topics", () => {
  const bad = page("platform-security-guide", {
    topics: "Old generic metadata",
    catalogs: "Not a list",
    navigation_kind: "old-kind",
  });
  const malformed = page("company-strategy", { topics: ["Bad key"] });
  const groups = navigationGroups([bad, malformed], "topic");
  expect(groups.map((group) => group.id)).toEqual([
    "company-strategy",
    "platform-security",
  ]);
  expect(navigationGroups([bad, malformed], "catalog")).toEqual([]);
  const invalidDefinition = page("x".repeat(65), { navigation_kind: "topic" });
  expect(
    navigationGroups([bad, invalidDefinition], "topic").some(
      (group) => group.id === "platform-security",
    ),
  ).toBe(true);
});

test("missing definitions use stable keys and definitions removed from a selection do not retain labels", () => {
  const member = page("example", {
    topics: ["engineering"],
    catalogs: ["tools"],
  });
  const definition = page("engineering", { navigation_kind: "topic" });
  definition.title = "Earlier engineering label";
  expect(navigationGroups([member, definition], "topic")[0].title).toBe(
    "Earlier engineering label",
  );
  expect(navigationGroups([member], "topic")[0].title).toBe("Engineering");
  expect(navigationGroups([member], "catalog")[0]).toMatchObject({
    id: "tools",
    title: "Tools",
    pages: [member],
  });
  expect(navigationGroups([], "catalog")).toEqual([]);
});
