import PocketBase, { BaseAuthStore, type RecordAuthResponse } from "pocketbase";
import type {
  Citation,
  PageDetail,
  PageSummary,
  Publication,
  Source,
} from "./types";

// Keep credentials per-tab; closing the tab ends its stored session.
const authStore = new BaseAuthStore();
const sessionKey = "wikicontext.reader.auth";
try {
  const stored =
    typeof window === "undefined"
      ? null
      : window.sessionStorage.getItem(sessionKey);
  if (stored) {
    const session = JSON.parse(stored);
    if (
      typeof session.token === "string" &&
      session.record?.collectionName === "users"
    )
      authStore.save(session.token, session.record);
  }
} catch {
  /* Browser storage may be disabled; memory authentication still works. */
}
authStore.onChange((token, record) => {
  try {
    if (typeof window === "undefined") return;
    if (token && record?.collectionName === "users")
      window.sessionStorage.setItem(
        sessionKey,
        JSON.stringify({ token, record }),
      );
    else window.sessionStorage.removeItem(sessionKey);
  } catch {
    /* Continue with the in-memory session. */
  }
});
export const pb = new PocketBase(
  typeof window === "undefined" ? "http://localhost" : window.location.origin,
  authStore,
);
// Concurrent page/evidence queries share an endpoint but must not cancel each other.
pb.autoCancellation(false);

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
  try {
    const result = await pb.send<SQLResult>("/api/context/query", {
      method: "POST",
      body: { sql },
    });
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
  // Read selected revisions inside SQL so a manifest larger than maxBytes remains usable.
  return `FROM publications pub JOIN pages p ON 1=1 JOIN page_revisions r ON r.page=p.id AND r.id=json_extract(pub.manifest, '$.' || p.id) WHERE pub.id=${identity(publicationId)} AND r.archived=0`;
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
  return allRows(
    `SELECT ${summary} ${published(publicationId)} ORDER BY p.slug`,
  );
}
export async function searchPages(
  publicationId: string,
  term: string,
  offset = 0,
  limit = 50,
): Promise<PageSummary[]> {
  windowSize(offset, limit);
  if (term.length > 500)
    throw new Error("Search must be 500 characters or fewer");
  const words = term.trim().split(/\s+/).filter(Boolean);
  const conditions = words
    .map(
      (word) =>
        ` AND instr(lower(p.slug || ' ' || r.title || ' ' || r.summary || ' ' || r.body), lower(${literal(word)}))>0`,
    )
    .join("");
  return query(
    `SELECT ${summary} ${published(publicationId)}${conditions} ORDER BY p.slug LIMIT ${limit} OFFSET ${offset}`,
  );
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

export async function loginGoogle(): Promise<void> {
  await pb.collection("users").authWithOAuth2({ provider: "google" });
}
export async function loginPassword(
  email: string,
  password: string,
): Promise<void> {
  await pb.collection("users").authWithPassword(email, password);
}
export async function refreshSession(): Promise<void> {
  const initiatingToken = pb.authStore.token;
  if (!initiatingToken) throw new Error("Please sign in to continue");
  try {
    // Save explicitly: the SDK authRefresh helper saves even after a user signs out.
    const result = await pb.send<RecordAuthResponse>(
      "/api/collections/users/auth-refresh",
      {
        method: "POST",
        headers: { Authorization: initiatingToken },
      },
    );
    if (pb.authStore.token !== initiatingToken) return;
    if (result.record.collectionName !== "users")
      throw new Error("Invalid workspace identity");
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
  const unsubscribeConnected = await pb.realtime.subscribe(
    "PB_CONNECT",
    callback,
  );
  try {
    const unsubscribePublications = await pb
      .collection("publications")
      .subscribe("*", callback);
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
