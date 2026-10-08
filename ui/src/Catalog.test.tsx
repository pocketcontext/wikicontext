import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Catalog, {
  catalogHref,
  filterCatalog,
  type CatalogState,
} from "./Catalog";
import PropertiesPanel, { propertyText } from "./Properties";
import { classifyWelcomePage } from "./welcome";
import type { PageDetail, PageSummary } from "./types";
const deployment: PageSummary = {
  id: "dep-revision",
  page: "dep-id",
  title: "North cluster",
  slug: "north",
  kind: "entity",
  summary: "",
  properties: { catalog_type: "deployment" },
};
const resource: PageDetail = {
  id: "resource-rev",
  page: "resource-id",
  title: "Evidence bucket",
  slug: "bucket",
  kind: "entity",
  summary: "",
  body: "",
  citations: [],
  backlinks: [],
  links: [],
  properties: {
    catalog_type: "resource",
    provider: "Example",
    provider_id: "not-a-secret",
    accountable_owner: null,
    deployment_profiles: [deployment.page],
    provider_observed_at: "2026-10-08",
    lifecycle_status: "active",
    expires_at: null,
    expiry_observation: "Not returned",
  },
  property_evidence: { provider_observed_at: ["2"] },
};
const state: CatalogState = {
  type: "resource",
  query: "",
  provider: "",
  deployment: "",
  lifecycle: "",
  missingOwner: false,
  sort: "title",
  offset: 0,
};
describe("published property catalogs", () => {
  it("filters properties and relationship names without interpreting bodies or conflating unknown values", () => {
    const pages = [resource, deployment];
    expect(
      filterCatalog(pages, {
        ...state,
        query: "North cluster",
        provider: "Example",
        deployment: deployment.page,
        lifecycle: "active",
        missingOwner: true,
      }),
    ).toEqual([resource]);
    expect(filterCatalog(pages, { ...state, provider: "Other" })).toEqual([]);
    expect(filterCatalog(pages, { ...state, query: "not-a-secret" })).toEqual([
      resource,
    ]);
    expect(propertyText(null)).toBe("Needs verification");
    expect(propertyText(false)).toBe("No");
    expect(propertyText(0)).toBe("0");
    expect(propertyText("Not returned")).toBe("Not returned");
  });
  it("sorts relationships by publication-selected titles, not identifiers", () => {
    const first = { ...deployment, page: "z", title: "Alpha" };
    const last = { ...deployment, page: "a", title: "Zulu" };
    const a = {
      ...resource,
      page: "one",
      properties: { ...resource.properties, deployment_profiles: ["a"] },
    };
    const z = {
      ...resource,
      page: "two",
      properties: { ...resource.properties, deployment_profiles: ["z"] },
    };
    expect(
      filterCatalog([a, z, first, last], {
        ...state,
        sort: "deployment_profiles",
      }),
    ).toEqual([z, a]);
  });
  it("keeps complete catalog filters and publication in shareable pagination links", () => {
    const href = catalogHref(
      {
        ...state,
        query: "R&D",
        provider: "Example",
        deployment: "dep-id",
        lifecycle: "active",
        missingOwner: true,
        sort: "-title",
        offset: 50,
      },
      "publication-id",
    );
    const params = new URLSearchParams(href.split("?")[1]);
    expect(params.get("q")).toBe("R&D");
    expect(params.get("publication")).toBe("publication-id");
    expect(params.get("missingOwner")).toBe("true");
    expect(params.get("offset")).toBe("50");
    expect(params.get("deployment")).toBe("dep-id");
  });
  it("opens property-only evidence and links relationships within the selected publication", () => {
    const citation = vi.fn();
    render(
      <PropertiesPanel
        page={resource}
        pages={[resource, deployment]}
        publication="old-publication"
        onCitation={citation}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Evidence for Provider observed at: citation 2",
      }),
    );
    expect(citation).toHaveBeenCalledWith(2);
    fireEvent.click(screen.getByText(/All properties/));
    expect(screen.getByRole("link", { name: "North cluster" })).toHaveAttribute(
      "href",
      "#/page/north?publication=old-publication",
    );
    expect(screen.getByText("Not returned")).toBeInTheDocument();
  });
  it("does not add a panel to legacy pages and classifies catalog pages by metadata", () => {
    const { container } = render(
      <PropertiesPanel
        page={{ ...resource, properties: {} }}
        pages={[]}
        onCitation={() => {}}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(
      classifyWelcomePage({
        ...resource,
        title: "A mysterious item",
        slug: "item",
      }),
    ).toBe("platform-security");
  });
  it("paginates matching records and preserves publication in page links", () => {
    const pages = Array.from({ length: 51 }, (_, i) => ({
      ...resource,
      id: `rev-${i}`,
      page: `id-${i}`,
      slug: `bucket-${i}`,
      title: `Bucket ${String(i).padStart(2, "0")}`,
    }));
    render(<Catalog pages={pages} state={state} publication="history" />);
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "#/catalog/resource?publication=history&offset=50",
    );
    expect(screen.getByRole("row", { name: /Bucket 00/ })).toBeInTheDocument();
    expect(
      screen.queryByRole("row", { name: /Bucket 50/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "Bucket 00" })[0],
    ).toHaveAttribute("href", "#/page/bucket-0?publication=history");
  });
});
