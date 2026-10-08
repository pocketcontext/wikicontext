import { useState } from "react";
import { pageHref } from "./Markdown";
import type { PageDetail, PageSummary, PropertyValue } from "./types";

export const relationshipKeys = new Set([
  "deployment_profiles",
  "applications",
  "resources",
  "credentials",
  "consumers",
  "replaces",
  "replaced_by",
]);
export function propertyLabel(key: string): string {
  return key
    .replaceAll("_", " ")
    .replace(/^./, (letter) => letter.toUpperCase());
}
export function propertyText(value: PropertyValue | undefined): string {
  if (
    value === undefined ||
    value === null ||
    value === "" ||
    (Array.isArray(value) && !value.length)
  )
    return "Needs verification";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return Array.isArray(value) ? value.join(", ") : String(value);
}
export function PropertyDisplay({
  name,
  value,
  pages,
  publication,
}: {
  name: string;
  value: PropertyValue | undefined;
  pages: PageSummary[];
  publication?: string;
}) {
  if (relationshipKeys.has(name) && Array.isArray(value) && value.length) {
    return (
      <span className="property-links">
        {value.map((id) => {
          const target = pages.find((page) => page.page === id);
          return target ? (
            <a key={id} href={pageHref(target.slug, publication)}>
              {target.title}
            </a>
          ) : (
            <span key={id}>Unavailable in this publication</span>
          );
        })}
      </span>
    );
  }
  const text = propertyText(value);
  // Display dates in their recorded precision; never infer an observation time.
  return typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}(T.*)?$/.test(value) ? (
    <time dateTime={value}>{text}</time>
  ) : (
    <span>{text}</span>
  );
}
const prominent = [
  "catalog_type",
  "resource_type",
  "provider",
  "lifecycle_status",
  "accountable_owner",
  "provider_observed_at",
];
export default function PropertiesPanel({
  page,
  pages,
  publication,
  onCitation,
}: {
  page: PageDetail;
  pages: PageSummary[];
  publication?: string;
  onCitation: (marker: number) => void;
}) {
  const properties = page.properties || {};
  const [copied, setCopied] = useState("");
  const keys = Object.keys(properties);
  if (!keys.length) return null;
  const main = prominent.filter((key) => Object.hasOwn(properties, key));
  const rest = keys.filter((key) => !main.includes(key)).sort();
  const fields = (names: string[]) => (
    <dl className="property-grid">
      {names.map((name) => (
        <div key={name}>
          <dt>{propertyLabel(name)}</dt>
          <dd>
            <PropertyDisplay
              name={name}
              value={properties[name]}
              pages={pages}
              publication={publication}
            />
            {name === "provider_id" && typeof properties[name] === "string" && (
              <button
                className="property-copy"
                aria-label="Copy provider ID"
                onClick={() => {
                  void navigator.clipboard
                    .writeText(String(properties[name]))
                    .then(
                      () => setCopied("Provider ID copied"),
                      () => setCopied("Unable to copy provider ID"),
                    );
                }}
              >
                Copy
              </button>
            )}
            {!page.property_evidence?.[name]?.length &&
              properties[name] != null &&
              properties[name] !== "" && (
                <small className="property-unverified">No cited evidence</small>
              )}
            {(page.property_evidence?.[name] || []).map((marker) => (
              <button
                key={marker}
                className="property-evidence"
                aria-label={`Evidence for ${propertyLabel(name)}: citation ${marker}`}
                onClick={() => onCitation(Number(marker))}
              >
                [{marker}]
              </button>
            ))}
          </dd>
        </div>
      ))}
    </dl>
  );
  return (
    <section className="properties-panel" aria-label="Page properties">
      <h2>Properties</h2>
      {main.length > 0 && fields(main)}
      {rest.length > 0 && (
        <details>
          <summary>
            All properties <span>({keys.length})</span>
          </summary>
          {fields(rest)}
        </details>
      )}
      {copied && <p role="status">{copied}</p>}
    </section>
  );
}
