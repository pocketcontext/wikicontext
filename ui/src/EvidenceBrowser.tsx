import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, pb, query } from "./api";
import ImagePreview from "./ImagePreview";
import type { Source } from "./types";

export type EvidenceCollection = "sources" | "passages";
export function evidenceHref(collection: EvidenceCollection, id = "", term = "", publication = "", offset = 0) {
  const params = new URLSearchParams();
  if (term) params.set("q", term);
  if (offset) params.set("offset", String(offset));
  if (publication) params.set("publication", publication);
  return `#/${collection}/${encodeURIComponent(id)}${params.size ? `?${params}` : ""}`;
}
const literal = (value: string) => `'${value.replaceAll("'", "''")}'`;
type Row = { id: string; title: string; body?: string; locator?: string; source_id?: string };
export default function EvidenceBrowser({ collection, id, term, publication, offset, navigation }: { collection: EvidenceCollection; id: string; term: string; publication: string; offset: number; navigation: HTMLElement | null }) {
  const actionEpoch = useRef(0);
  useEffect(() => { actionEpoch.current++; return () => { actionEpoch.current++; }; }, [collection, id]);
  const [rows, setRows] = useState<Row[]>([]);
  const [selected, setSelected] = useState<Row | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    setBusy(true); setError(""); setRows([]); setSelected(null); setSource(null);
    const timer = setTimeout(() => void (async () => {
      try {
        const base = collection === "sources"
          ? "SELECT s.id, s.title FROM sources s"
          : "SELECT p.id, s.title, p.locator, p.body, s.id AS source_id FROM passages p JOIN renditions r ON r.id=p.rendition JOIN sources s ON s.id=r.source";
        const key = collection === "sources" ? "s.id" : "p.id";
        const fields = collection === "sources" ? "s.title || ' ' || s.original_name || ' ' || s.id" : "s.title || ' ' || p.locator || ' ' || p.body || ' ' || p.id || ' ' || s.id";
        const found = await query<Row>(`${base.replace("p.locator, p.body,", "p.locator,")} WHERE instr(lower(${fields}), lower(${literal(term)}))>0 ORDER BY ${key} LIMIT 21 OFFSET ${offset}`);
        const record = id ? (await query<Row>(`${base} WHERE ${key}=${literal(id)} LIMIT 1`))[0] : null;
        const original = record ? (await query<Source>(`SELECT id,title,original_name,original,media_type,source_date,sha256 FROM sources WHERE id=${literal(record.source_id || record.id)} LIMIT 1`))[0] : null;
        if (active) { setRows(found.slice(0,20)); setMore(found.length>20); setSelected(record || null); setSource(original || null); }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "Unable to load evidence"); }
      finally { if (active) setBusy(false); }
    })(), 200);
    return () => { active = false; clearTimeout(timer); };
  }, [collection, id, term, offset]);
  const results = <>
    <button onClick={() => void navigator.clipboard.writeText(new URL(evidenceHref(collection,"",term,publication,offset),location.href).href).catch(() => setError("Unable to copy link"))}>Copy search link</button>
    <nav className="page-list" aria-label="Evidence records">{rows.map(row => <a key={row.id} aria-current={row.id===id?"page":undefined} href={evidenceHref(collection,row.id,term,publication,offset)}>{row.title} {row.locator || ""}<small> · {row.id}</small></a>)}</nav>
    {!busy && !rows.length && <p>No matches.</p>}
    {offset>0 && <a href={evidenceHref(collection,id,term,publication,Math.max(0,offset-20))}>Previous</a>}
    {more && <a href={evidenceHref(collection,id,term,publication,offset+20)}>Next</a>}
  </>;
  return <section aria-busy={busy}>
    <h1>{collection === "sources" ? "Sources" : "Passages"}</h1>
    <p>Immutable source evidence. This collection includes evidence that has not been cited in a publication.</p>
    {error && <p role="alert">{error}</p>}
    {id ? selected ? <article>
      <h2>{selected.title}</h2>
      <p>{selected.locator}</p>
      {selected.body && <blockquote className="passage">{selected.body}</blockquote>}
      {selected.source_id && <p><a href={evidenceHref("sources", selected.source_id, "", publication)}>Source: {selected.title}</a></p>}
      <button onClick={() => void navigator.clipboard.writeText(new URL(evidenceHref(collection,id),location.href).href).catch(() => setError("Unable to copy link"))}>Copy record link</button>
      {source && <><p>{source.original_name} · {source.media_type}</p><button onClick={() => { const token = pb.authStore.token, epoch = actionEpoch.current; void api.originalURL(source).then(url => { if (epoch === actionEpoch.current && pb.authStore.isValid && token === pb.authStore.token) window.location.assign(url); }).catch(e => setError(String(e))); }}>Download original</button></>}
      {source && <ImagePreview source={source} />}
      {collection === "sources" && <p><a href={evidenceHref("passages", "", selected.id, publication)}>Browse evidence by source ID</a></p>}
    </article> : !busy && <p>Record unavailable.</p> : null}
    {navigation ? createPortal(results, navigation) : results}
  </section>;
}
