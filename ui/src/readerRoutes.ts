import { catalogTypes, type CatalogState, type CatalogType } from "./Catalog";
function safeDecode(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
export function readReaderRoute(hash = location.hash) {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(query);
  return {
    slug:
      path.startsWith("catalog/") ||
      path === "welcome" ||
      path === "pages" ||
      /^(sources|passages)\//.test(path)
        ? ""
        : safeDecode(path.replace(/^page\//, "")),
    welcome: path === "welcome",
    directory:
      path === "pages" ||
      (path === "welcome" && (params.has("topic") || params.has("view"))),
    filter: params.get("filter") || "",
    sort: params.get("sort") || "title",
    view: params.get("view") || "",
    passage: params.get("passage") || "",
    catalog: path.startsWith("catalog/"),
    catalogState: {
      custom:
        path.split("/")[1] === "custom"
          ? safeDecode(path.split("/").slice(2).join("/"))
          : undefined,
      type:
        path.startsWith("catalog/") && path.split("/")[1] !== "custom"
          ? path.split("/").length === 2 &&
            catalogTypes.includes(path.split("/")[1] as CatalogType)
            ? (path.split("/")[1] as CatalogType)
            : ("unavailable" as CatalogType)
          : "resource",
      query: params.get("q") || "",
      language: params.get("language") || "",
      bundle: params.get("bundle") || "",
      targetAgent: params.get("targetAgent") || "",
      requiredSkill: params.get("requiredSkill") || "",
      repository: params.get("repository") || "",
      documentType: params.get("documentType") || "",
      syncStatus: params.get("syncStatus") || "",
      group: params.get("group") || "",
      member: params.get("member") || "",
      provider: params.get("provider") || "",
      deployment: params.get("deployment") || "",
      lifecycle: params.get("lifecycle") || "",
      missingOwner: params.get("missingOwner") === "true",
      sort:
        params.get("sort") ||
        (path.startsWith("catalog/custom/") ? "" : "title"),
      offset: Math.min(
        100000,
        Math.max(0, parseInt(params.get("offset") || "0", 10) || 0),
      ),
    } as CatalogState,
    topic: params.get("topic") || "",
    collection: path.startsWith("sources/")
      ? ("sources" as const)
      : path.startsWith("passages/")
        ? ("passages" as const)
        : ("pages" as const),
    record: /^(sources|passages)\//.test(path)
      ? safeDecode(path.split("/")[1] || "")
      : "",
    publication: params.get("publication") || "",
    space: params.has("space") ? params.get("space")! : undefined,
    offset: Math.min(
      100000,
      Math.max(0, parseInt(params.get("offset") || "0", 10) || 0),
    ),
    heading: params.get("heading") || "",
    query: params.get("q") || "",
  };
}
