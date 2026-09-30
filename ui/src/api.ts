import PocketBase, { BaseAuthStore, LocalAuthStore, type SendOptions, type RecordAuthResponse } from "pocketbase";
import type {
  Citation,
  PageDetail,
  PageSummary,
  Publication,
  Source,
} from "./types";

// The SDK synchronizes this application's credentials across same-origin tabs.
const sessionKey = "wikicontext.reader.auth";
const authStore = new LocalAuthStore(sessionKey);
// Discard legacy per-tab credentials; never resurrect them after shared logout.
try { window.sessionStorage.removeItem(sessionKey); } catch { /* Optional storage. */ }
if (authStore.record?.collectionName !== "users" || !authStore.isValid) authStore.clear();
export let sessionGeneration = 0;
function identityKey() {
  return authStore.token ? `${authStore.record?.collectionName}:${authStore.record?.id}` : "";
}
let activeIdentity = identityKey();
let realtimeCleanup: Promise<void> = Promise.resolve();
authStore.onChange(() => {
  const next = identityKey();
  if (next === activeIdentity) {
    // A sibling tab already renewed this identity; do not renew it again on focus.
    if (next) { refreshedAt = Date.now(); refreshedToken = authStore.token; }
    return;
  }
  activeIdentity = next;
  sessionGeneration++;
  realtimeCleanup = realtimeCleanup.then(() => pb.realtime.unsubscribe()).catch(() => {});
});
export const pb = new PocketBase(
  typeof window === "undefined" ? "http://localhost" : window.location.origin,
  authStore,
);
// Concurrent page/evidence queries share an endpoint but must not cancel each other.
pb.autoCancellation(false);
// Reject fully parsed responses from a previous identity before callers see them.
const send = pb.send.bind(pb);
pb.send = async <T = unknown>(path: string, options: SendOptions = {}): Promise<T> => {
  const generation = sessionGeneration;
  const token = authStore.token;
  const identity = identityKey();
  try {
    const result = await send<T>(path, options);
    if (generation !== sessionGeneration || identity !== identityKey()) throw new Error("Session changed");
    return result;
  } catch (error) {
    const status = (error as { status?: number }).status;
    if (generation === sessionGeneration && token && token === authStore.token && (status === 401 || status === 403))
      authStore.clear();
    throw error;
  }
};

interface SQLResult {
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
}
export class TruncatedQueryError extends Error {
  constructor() {
    super(
      "This content exceeds the query response limit. Narrow the selection and retry.",
    );
  }
}

function literal(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}
function identity(value: string): string {
  if (!/^[a-z0-9]{15}$/.test(value)) throw new Error("Invalid record identity");
  return literal(value);
}
function windowSize(offset: number, limit: number): void {
  if (
    !Number.isSafeInteger(offset) ||
    offset < 0 ||
    !Number.isSafeInteger(limit) ||
    limit < 1 ||
    limit > 200
  )
    throw new Error("Invalid query page");
}

export async function query<T>(sql: string): Promise<T[]> {
  const initiatingToken = pb.authStore.token;
  const generation = sessionGeneration;
  try {
    const result = await pb.send<SQLResult>("/api/context/query", {
      method: "POST",
      body: { sql },
    });
    if (generation !== sessionGeneration) throw new Error("Session changed");
    if (result.truncated) throw new TruncatedQueryError();
    return result.rows.map(
      (row) =>
        Object.fromEntries(
          result.columns.map((column, index) => [column, row[index]]),
        ) as T,
    );
  } catch (error) {
    if (error && typeof error === "object" && "status" in error) {
      if (
        (error.status === 401 || error.status === 403) &&
        pb.authStore.token === initiatingToken
      )
        pb.authStore.clear();
      if (error.status === 413) throw new TruncatedQueryError();
    }
    throw error;
  }
}

// Small adaptive pages respect both the row and byte limits, including long summaries/passages.
async function allRows<T>(sql: string, initialSize = 100): Promise<T[]> {
  const result: T[] = [];
  let size = initialSize;
  for (;;) {
    let rows: T[];
    try {
      rows = await query<T>(`${sql} LIMIT ${size} OFFSET ${result.length}`);
    } catch (error) {
      if (error instanceof TruncatedQueryError && size > 1) {
        size = Math.max(1, Math.floor(size / 2));
        continue;
      }
      throw error;
    }
    result.push(...rows);
    if (rows.length < size) return result;
  }
}

const summary = "r.id, r.page, p.slug, p.kind, r.title, r.summary";
function published(publicationId: string): string {
  // Expand only the selected immutable manifest, rather than testing every page
  // identity against it. Never download the manifest or select a revision by age.
  return `FROM publications pub JOIN json_each(pub.manifest) m JOIN pages p ON p.id=m.key JOIN page_revisions r ON r.page=p.id AND r.id=m.value WHERE pub.id=${identity(publicationId)} AND m.type='text' AND r.archived=0`;
}

async function validatePublication(publicationId: string): Promise<boolean> {
  // Validate before inner joins can discard broken entries. Publications and
  // their revisions are immutable, so subsequent paged reads share this check.
  const rows = await query<{
    manifest_type: string;
    total: number;
    unique_keys: number;
    invalid: number;
  }>(
    `SELECT json_type(pub.manifest) AS manifest_type, count(m.key) AS total,
      count(DISTINCT m.key) AS unique_keys,
      coalesce(sum(CASE WHEN m.key IS NULL THEN 0
        WHEN length(m.key)!=15 OR m.key GLOB '*[^a-z0-9]*'
        OR m.type!='text' OR length(m.value)!=15 OR m.value GLOB '*[^a-z0-9]*'
        OR p.id IS NULL OR r.id IS NULL THEN 1 ELSE 0 END),0) AS invalid
     FROM publications pub LEFT JOIN json_each(pub.manifest) m ON 1=1
     LEFT JOIN pages p ON p.id=m.key
     LEFT JOIN page_revisions r ON r.id=m.value AND r.page=p.id
     WHERE pub.id=${identity(publicationId)} GROUP BY pub.id LIMIT 1`,
  );
  if (!rows.length) return false;
  const check = rows[0];
  if (
    check.manifest_type !== "object" ||
    check.invalid !== 0 ||
    check.total !== check.unique_keys
  )
    throw new Error("This publication is incomplete or invalid");
  return true;
}

export async function listPublications(
  offset = 0,
  limit = 50,
): Promise<Publication[]> {
  windowSize(offset, limit);
  return query(
    `SELECT id, sequence, run, created FROM publications ORDER BY sequence DESC LIMIT ${limit} OFFSET ${offset}`,
  );
}
export async function latestPublication(): Promise<Publication | null> {
  return (await listPublications(0, 1))[0] ?? null;
}
export async function getPublication(id: string): Promise<Publication | null> {
  return (
    (
      await query<Publication>(
        `SELECT id, sequence, run, created FROM publications WHERE id=${identity(id)} LIMIT 1`,
      )
    )[0] ?? null
  );
}
export async function listPages(publicationId: string): Promise<PageSummary[]> {
  if (!(await validatePublication(publicationId))) return [];
  return allRows(
    `SELECT ${summary} ${published(publicationId)} ORDER BY p.slug`,
  );
}
export interface SearchPage {
  generation: string;
  hits: (PageSummary & { score: number; excerpt: string })[];
  hasMore: boolean;
}
export class SearchChangedError extends Error {
  constructor() {
    super("Search changed. Restart to see consistent results.");
  }
}
export async function searchPages(
  publicationId: string,
  term: string,
  offset = 0,
  limit = 20,
  expectedGeneration?: string,
): Promise<SearchPage> {
  windowSize(offset, limit);
  identity(publicationId);
  if (limit > 100 || offset > 10000 || (offset > 0 && !expectedGeneration))
    throw new Error("Invalid search page");
  if (!term.trim() || term.length > 500 || term.trim().split(/\s+/).length > 16)
    throw new Error(
      "Search must contain 1 to 500 characters and at most 16 words",
    );
  if (!(await validatePublication(publicationId)))
    throw new Error("This publication is unavailable");
  const token = pb.authStore.token;
  let result: {
    index: string;
    scope: string;
    generation: string;
    hits: { id: string; score: number; excerpt: string }[];
    hasMore: boolean;
    truncated: boolean;
  };
  try {
    result = await pb.send("/api/context/search", {
      method: "POST",
      body: {
        index: "pages",
        query: term.trim(),
        scope: publicationId,
        limit,
        offset,
        ...(expectedGeneration ? { expectedGeneration } : {}),
      },
    });
  } catch (error) {
    if (error && typeof error === "object" && "status" in error) {
      if (
        (error.status === 401 || error.status === 403) &&
        pb.authStore.token === token
      )
        pb.authStore.clear();
      if (error.status === 409) throw new SearchChangedError();
    }
    throw error;
  }
  if (
    result.index !== "pages" ||
    result.scope !== publicationId ||
    typeof result.generation !== "string" ||
    !result.generation ||
    result.generation.length > 128 ||
    result.generation.includes("\0") ||
    (expectedGeneration && result.generation !== expectedGeneration)
  )
    throw new SearchChangedError();
  if (
    !Array.isArray(result.hits) ||
    result.hits.length > limit ||
    typeof result.hasMore !== "boolean" ||
    result.truncated !== result.hasMore ||
    (result.hasMore && !result.hits.length) ||
    new Set(result.hits.map((h) => h.id)).size !== result.hits.length
  )
    throw new Error("Invalid search response");
  if (!result.hits.length)
    return { generation: result.generation, hits: [], hasMore: result.hasMore };
  for (let i = 1; i < result.hits.length; i++) {
    const previous = result.hits[i - 1],
      current = result.hits[i];
    if (
      previous.score > current.score ||
      (previous.score === current.score && previous.id >= current.id)
    )
      throw new Error("Invalid search ranking");
  }
  const ids = result.hits.map((h) => {
    if (!Number.isFinite(h.score) || typeof h.excerpt !== "string")
      throw new Error("Invalid search hit");
    return identity(h.id);
  });
  const rows = await allRows<PageSummary>(
    `SELECT ${summary} ${published(publicationId)} AND r.id IN (${ids.join(",")}) ORDER BY r.id`,
    20,
  );
  const byID = new Map(rows.map((row) => [row.id, row]));
  if (byID.size !== result.hits.length || rows.length !== byID.size)
    throw new Error("Search results do not match the selected publication");
  return {
    generation: result.generation,
    hasMore: result.hasMore,
    hits: result.hits.map((hit) => {
      const page = byID.get(hit.id);
      if (!page)
        throw new Error("Search result is unavailable in this publication");
      return { ...page, score: hit.score, excerpt: hit.excerpt };
    }),
  };
}

interface CitationRow {
  id: string;
  marker: string;
  note: string;
  passage_id: string;
  ordinal: number;
  locator: string;
  passage_body: string;
  source_id: string;
  source_title: string;
  original_name: string;
  original: string;
  media_type: string;
  source_date: string;
  sha256: string;
}

export async function getPage(
  publicationId: string,
  slug: string,
): Promise<PageDetail | null> {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug))
    throw new Error("Invalid page slug");
  if (!(await validatePublication(publicationId))) return null;
  const page = (
    await query<PageSummary & { body: string }>(
      `SELECT ${summary}, r.body ${published(publicationId)} AND p.slug=${literal(slug)} LIMIT 1`,
    )
  )[0];
  if (!page) return null;
  const [rows, backlinks, links] = await Promise.all([
    allRows<CitationRow>(
      `SELECT c.id, c.marker, c.note, t.id AS passage_id, t.ordinal, t.locator, t.body AS passage_body, s.id AS source_id, s.title AS source_title, s.original_name, s.original, s.media_type, s.source_date, s.sha256 FROM citations c JOIN passages t ON t.id=c.passage JOIN renditions e ON e.id=t.rendition JOIN sources s ON s.id=e.source WHERE c.page_revision=${identity(page.id)} ORDER BY c.id`,
      10,
    ),
    allRows<PageSummary>(
      `SELECT ${summary} ${published(publicationId)} AND r.id IN (SELECT l.page_revision FROM page_links l WHERE l.target=${identity(page.page)}) ORDER BY p.slug`,
    ),
    allRows<PageSummary>(
      `SELECT ${summary} ${published(publicationId)} AND p.id IN (SELECT l.target FROM page_links l WHERE l.page_revision=${identity(page.id)}) ORDER BY p.slug`,
    ),
  ]);
  const citations: Citation[] = rows
    .map((row) => ({
      id: row.id,
      marker: row.marker,
      note: row.note,
      passage: {
        id: row.passage_id,
        ordinal: row.ordinal,
        locator: row.locator,
        body: row.passage_body,
      },
      source: {
        id: row.source_id,
        title: row.source_title,
        original_name: row.original_name,
        original: row.original,
        media_type: row.media_type,
        source_date: row.source_date,
        sha256: row.sha256,
      },
    }))
    .sort((a, b) => Number(a.marker) - Number(b.marker));
  return { ...page, citations, backlinks, links };
}

async function signIn(email?: string, password?: string): Promise<void> {
  const generation = sessionGeneration, token = authStore.token;
  const client = new PocketBase(pb.baseURL, new BaseAuthStore());
  try {
    const auth = client.collection("users");
    const result = email === undefined
      ? await auth.authWithOAuth2({ provider: "google" })
      : await auth.authWithPassword(email, password!);
    if (generation !== sessionGeneration || token !== authStore.token) throw new Error("Session changed");
    if (result.record.collectionName !== "users") throw new Error("Invalid workspace identity");
    authStore.save(result.token, result.record);
  } finally { await client.realtime.unsubscribe(); }
}
export async function loginGoogle(): Promise<void> { await signIn(); }
export async function loginPassword(email: string, password: string): Promise<void> { await signIn(email, password); }
let refreshedAt = 0;
let refreshedToken = "";
export async function refreshSession(): Promise<void> {
  const initiatingToken = pb.authStore.token;
  if (!initiatingToken) throw new Error("Please sign in to continue");
  const generation = sessionGeneration;
  if (initiatingToken === refreshedToken && Date.now() - refreshedAt < 300000) return;
  try {
    // Save explicitly: the SDK authRefresh helper saves even after a user signs out.
    const result = await pb.send<RecordAuthResponse>(
      "/api/collections/users/auth-refresh",
      {
        method: "POST",
        headers: { Authorization: initiatingToken },
      },
    );
    if (pb.authStore.token !== initiatingToken || generation !== sessionGeneration) return;
    if (result.record.collectionName !== "users")
      throw new Error("Invalid workspace identity");
    refreshedAt = Date.now();
    refreshedToken = result.token;
    pb.authStore.save(result.token, result.record);
  } catch (error) {
    if (
      error &&
      typeof error === "object" &&
      "status" in error &&
      (error.status === 401 || error.status === 403) &&
      pb.authStore.token === initiatingToken
    )
      pb.authStore.clear();
    throw error;
  }
}
export function logout(): void {
  pb.authStore.clear();
}
export async function originalURL(source: Source): Promise<string> {
  identity(source.id);
  const token = await pb.files.getToken();
  return pb.files.getURL(
    { id: source.id, collectionName: "sources" },
    source.original,
    { token, download: true },
  );
}
export async function watchPublications(
  callback: () => void,
): Promise<() => void> {
  const generation = sessionGeneration;
  await realtimeCleanup;
  if (generation !== sessionGeneration || !pb.authStore.isValid) return () => {};
  const notify = () => { if (generation === sessionGeneration) callback(); };
  const unsubscribeConnected = await pb.realtime.subscribe(
    "PB_CONNECT",
    notify,
  );
  try {
    const unsubscribePublications = await pb
      .collection("publications")
      .subscribe("*", notify);
    return () => {
      void unsubscribePublications().catch(() => {});
      void unsubscribeConnected().catch(() => {});
    };
  } catch (error) {
    void unsubscribeConnected().catch(() => {});
    throw error;
  }
}

export const api = {
  loginGoogle,
  loginPassword,
  refreshSession,
  logout,
  listPublications,
  latestPublication,
  getPublication,
  listPages,
  getPage,
  searchPages,
  originalURL,
  watchPublications,
};
