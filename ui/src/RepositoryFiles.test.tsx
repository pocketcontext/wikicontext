import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Catalog, { type CatalogState } from "./Catalog";
import { documentDestinations, githubFileHref } from "./RepositoryFiles";
import type { PageSummary } from "./types";
afterEach(cleanup);
const doc: PageSummary = {
  id: "doc-v1",
  page: "doc",
  slug: "shared-readme",
  kind: "entity",
  title: "Shared README",
  summary: "",
  properties: {
    catalog_type: "repository_document",
    document_type: "readme",
    output_mode: "markdown",
  },
};
const dest: PageSummary = {
  ...doc,
  id: "dest-v1",
  page: "dest",
  slug: "readme-copy",
  title: "README copy",
  properties: {
    catalog_type: "repository_destination",
    documents: ["doc"],
    github_repository: "example/one",
    github_branch: "feature/docs",
    github_path: "docs/README.md",
  },
};
const sync: PageSummary = {
  ...doc,
  id: "sync-v1",
  page: "sync",
  slug: "sync-check",
  title: "Sync check",
  properties: {
    catalog_type: "repository_sync",
    destinations: ["dest"],
    synced_document_revision: "doc-v1",
    synced_destination_revision: "dest-v1",
    sync_status: "current",
    checked_at: "2026-10-10T10:00:00Z",
  },
};
const state: CatalogState = {
  type: "repository_document",
  query: "",
  provider: "",
  deployment: "",
  lifecycle: "",
  missingOwner: false,
  sort: "title",
  offset: 0,
};
it("resolves observations only within the publication and detects source and destination changes", () => {
  expect(documentDestinations(doc, [doc, dest, sync])[0].status).toBe(
    "current",
  );
  expect(
    documentDestinations({ ...doc, id: "doc-v2" }, [dest, sync])[0].status,
  ).toBe("behind");
  expect(
    documentDestinations(doc, [{ ...dest, id: "dest-v2" }, sync])[0].status,
  ).toBe("unknown");
  expect(documentDestinations(doc, [dest])[0].status).toBe("unknown");
  const later = {
    ...sync,
    id: "later",
    properties: {
      ...sync.properties,
      sync_status: "diverged",
      checked_at: "2026-10-10T10:00:00.100Z",
    },
  };
  expect(documentDestinations(doc, [dest, later, sync])[0].status).toBe(
    "diverged",
  );
});
it("groups multiple copies, keeps history in links, and preserves filters in navigation", () => {
  const navigate = vi.fn();
  render(
    <Catalog
      pages={[
        doc,
        dest,
        sync,
        {
          ...dest,
          page: "dest2",
          title: "Second copy",
          properties: { ...dest.properties, github_repository: "example/two" },
        },
      ]}
      state={state}
      publication="old"
      onNavigate={navigate}
    />,
  );
  expect(screen.getByRole("link", { name: "Shared README" })).toHaveAttribute(
    "href",
    "#/page/shared-readme?publication=old",
  );
  expect(screen.getByRole("link", { name: "Second copy" })).toBeVisible();
  expect(screen.getByText("current", { selector: "strong" })).toBeVisible();
  expect(screen.getByText("No check recorded.")).toBeVisible();
  fireEvent.change(screen.getByLabelText("Repository"), {
    target: { value: "example/two" },
  });
  expect(navigate).toHaveBeenCalledWith(
    "#/catalog/repository_document?publication=old&repository=example%2Ftwo",
  );
});
it("filters destination status and repository together", () => {
  render(
    <Catalog
      pages={[doc, dest, sync]}
      state={{ ...state, repository: "example/one", syncStatus: "behind" }}
    />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("0 documents");
});
it("constructs only safe GitHub URLs and encodes branch and path", () => {
  expect(githubFileHref(dest)).toBe(
    "https://github.com/example/one/blob/feature%2Fdocs/docs/README.md",
  );
  for (const github_path of [
    "../LICENSE",
    "/LICENSE",
    "foo\\bar",
    "a/./LICENSE",
  ])
    expect(
      githubFileHref({
        ...dest,
        properties: { ...dest.properties, github_path },
      }),
    ).toBeUndefined();
});
