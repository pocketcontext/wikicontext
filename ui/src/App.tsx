import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, pb } from "./api";
import type { Publication, PageSummary, PageDetail, Citation } from "./types";
import { Markdown, pageHref } from "./Markdown";
function safeDecode(value: string) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
function savedTheme() {
  try {
    return localStorage.getItem("wiki-theme") || "dark";
  } catch {
    return "dark";
  }
}
function route() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(query);
  return {
    slug: safeDecode(path.replace(/^page\//, "")),
    publication: params.get("publication") || "",
    heading: params.get("heading") || "",
  };
}
function message(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Unable to load the wiki. Please try again.";
}
export default function App() {
  const [authenticated, setAuthenticated] = useState(pb.authStore.isValid);
  const [current, setCurrent] = useState(route);
  const routeSelection = useRef(current);
  const [publications, setPublications] = useState<Publication[]>([]);
  const [snapshot, setSnapshot] = useState<{
    publication: Publication;
    pages: PageSummary[];
    page: PageDetail | null;
  } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [outline, setOutline] = useState<
    { level: number; title: string; id: string }[]
  >([]);
  const [results, setResults] = useState<PageSummary[] | null>(null);
  const [evidence, setEvidence] = useState<Citation | null>(null);
  const [original, setOriginal] = useState("");
  const [menu, setMenu] = useState(false);
  const [connected, setConnected] = useState(false);
  const [theme, setTheme] = useState(savedTheme);
  const generation = useRef(0);
  const historyOffset = useRef(0);
  const [moreHistory, setMoreHistory] = useState(false);
  const reader = useRef<HTMLElement>(null);
  const citationClose = useRef<HTMLButtonElement>(null);
  const lastCitationFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("wiki-theme", theme);
    } catch {
      /* Storage is optional. */
    }
  }, [theme]);
  useEffect(() => {
    const handler = () => {
      const next = route();
      const previous = routeSelection.current;
      if (
        next.slug !== previous.slug ||
        next.publication !== previous.publication
      ) {
        generation.current++;
        setSnapshot(null);
      }
      routeSelection.current = next;
      setCurrent(next);
      setEvidence(null);
      setMenu(false);
    };
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  useEffect(
    () =>
      pb.authStore.onChange(() => {
        const valid = pb.authStore.isValid;
        setAuthenticated(valid);
        if (!valid) {
          generation.current++;
          setSnapshot(null);
          setPublications([]);
          setEvidence(null);
          setOriginal("");
          setResults(null);
          setSearch("");
        }
      }, true),
    [],
  );
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (
        event.key === "/" &&
        !(event.target instanceof HTMLInputElement) &&
        !(event.target instanceof HTMLTextAreaElement)
      ) {
        event.preventDefault();
        setMenu(true);
        requestAnimationFrame(() =>
          document
            .querySelector<HTMLInputElement>('input[aria-label="Search pages"]')
            ?.focus(),
        );
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);
  const load = useCallback(async () => {
    if (!pb.authStore.isValid) return;
    const own = ++generation.current;
    setBusy(true);
    setError("");
    try {
      await api.refreshSession();
      const history = await api.listPublications();
      if (own === generation.current) {
        historyOffset.current = history.length;
        setMoreHistory(history.length === 50);
      }
      let publication = current.publication
        ? history.find((p) => p.id === current.publication)
        : history[0];
      if (current.publication && !publication) {
        publication =
          (await api.getPublication(current.publication)) || undefined;
        if (publication) history.push(publication);
      }
      if (!publication) {
        if (current.publication)
          throw new Error(
            "This publication is unavailable. Choose Live to return to the latest pages.",
          );
        if (own === generation.current) {
          setPublications(history);
          setSnapshot(null);
        }
        return;
      }
      const pages = await api.listPages(publication.id);
      const slug = current.slug || pages[0]?.slug;
      const page = slug ? await api.getPage(publication.id, slug) : null;
      if (own === generation.current) {
        setPublications(history);
        setSnapshot({ publication, pages, page });
        setEvidence((previous) =>
          previous && page?.citations.some((c) => c.id === previous.id)
            ? previous
            : null,
        );
      }
    } catch (e) {
      if (own === generation.current) setError(message(e));
    } finally {
      if (own === generation.current) setBusy(false);
    }
  }, [current.slug, current.publication]);
  useEffect(() => {
    if (!authenticated) return;
    void load();
    let disposed = false;
    let unsubscribe: (() => void) | undefined;
    api
      .watchPublications(() => {
        setConnected(navigator.onLine);
        void load();
      })
      .then((fn) => {
        if (disposed) fn();
        else {
          unsubscribe = fn;
          setConnected(navigator.onLine);
        }
      })
      .catch(() => setConnected(false));
    const focus = () => void load();
    const offline = () => setConnected(false);
    const online = () => {
      setConnected(false);
      void load();
    };
    window.addEventListener("offline", offline);
    window.addEventListener("online", online);
    window.addEventListener("focus", focus);
    const interval = window.setInterval(focus, 60000);
    return () => {
      disposed = true;
      unsubscribe?.();
      setConnected(false);
      window.removeEventListener("focus", focus);
      window.removeEventListener("offline", offline);
      window.removeEventListener("online", online);
      clearInterval(interval);
    };
  }, [authenticated, load]);
  useEffect(() => {
    reader.current?.scrollTo?.(0, 0);
  }, [current.slug, current.publication]);
  useEffect(() => {
    if (current.heading && snapshot)
      document
        .getElementById(current.heading)
        ?.scrollIntoView?.({ behavior: "smooth" });
  }, [current.heading, snapshot]);
  useEffect(() => {
    setResults(null);
    if (!search.trim() || !snapshot) return;
    let disposed = false;
    const timeout = setTimeout(() => {
      api
        .searchPages(snapshot.publication.id, search.trim())
        .then((rows) => {
          if (!disposed) setResults(rows);
        })
        .catch((e) => {
          if (!disposed) setError(message(e));
        });
    }, 180);
    return () => {
      disposed = true;
      clearTimeout(timeout);
    };
  }, [search, snapshot]);
  useEffect(() => {
    if (!evidence) return;
    setOriginal("");
    let disposed = false;
    citationClose.current?.focus();
    api
      .originalURL(evidence.source)
      .then((url) => {
        if (!disposed) setOriginal(url);
      })
      .catch((e) => {
        if (!disposed) setError(message(e));
      });
    return () => {
      disposed = true;
    };
  }, [evidence]);
  const closeEvidence = () => {
    setEvidence(null);
    setOriginal("");
    const previous = lastCitationFocus.current;
    const label = previous?.getAttribute("aria-label");
    requestAnimationFrame(() => {
      if (previous?.isConnected) previous.focus();
      else if (label)
        Array.from(document.querySelectorAll<HTMLElement>("button[aria-label]"))
          .find((node) => node.getAttribute("aria-label") === label)
          ?.focus();
    });
  };
  const navigatePublication = (id: string) => {
    location.hash = pageHref(
      current.slug || snapshot?.page?.slug || "",
      id === "live" ? undefined : id,
    ).slice(1);
  };
  useEffect(() => {
    setOutline(
      Array.from(
        reader.current?.querySelectorAll<HTMLElement>(
          ".markdown h1,.markdown h2,.markdown h3,.markdown h4,.markdown h5,.markdown h6",
        ) || [],
      ).map((node) => ({
        level: Number(node.tagName.slice(1)),
        title: node.textContent || "",
        id: node.id,
      })),
    );
  }, [snapshot?.page?.id]);
  const resolveSlug = useCallback(
    (target: string) =>
      snapshot?.pages.find(
        (p) =>
          p.slug === target || p.title.toLowerCase() === target.toLowerCase(),
      )?.slug || target,
    [snapshot?.pages],
  );
  const openCitation = useCallback(
    (marker: number) => {
      const citation = snapshot?.page?.citations.find(
        (c) => Number(c.marker) === marker,
      );
      if (citation) {
        lastCitationFocus.current = document.activeElement as HTMLElement;
        setEvidence(citation);
      }
    },
    [snapshot?.page],
  );
  const pinned = current.publication || undefined;
  if (!authenticated) return <Login theme={theme} setTheme={setTheme} />;
  const page = snapshot?.page;
  const pages = search.trim() ? results || [] : snapshot?.pages || [];
  return (
    <div className="workspace">
      <a
        className="skip-link"
        href="#reader"
        onClick={(e) => {
          e.preventDefault();
          reader.current?.focus();
        }}
      >
        Skip to page
      </a>
      <aside
        className={`sidebar ${menu ? "is-open" : ""}`}
        aria-label="Wiki navigation"
      >
        <a className="brand" href="#/">
          <span className="brand-mark">W</span>
          <span>
            WikiContext<small>YOUR CONNECTED KNOWLEDGE</small>
          </span>
        </a>
        <div className="workspace-label">
          <span className="workspace-dot" /> Shared workspace
        </div>
        <label className="search">
          <span aria-hidden="true">⌕</span>
          <input
            aria-label="Search pages"
            type="search"
            placeholder="Search your knowledge…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <kbd>/</kbd>
        </label>
        <div className="nav-label">
          {search ? "SEARCH RESULTS" : "PAGES"}
          <span>{pages.length}</span>
        </div>
        <nav className="page-list" aria-label="Pages">
          {pages.map((p) => (
            <a
              key={p.id}
              href={pageHref(p.slug, pinned)}
              className={p.slug === page?.slug ? "selected" : ""}
              aria-current={p.slug === page?.slug ? "page" : undefined}
            >
              <span className="page-icon" aria-hidden="true">
                ▤
              </span>
              <span>{p.title}</span>
            </a>
          ))}
          {search && pages.length === 50 && (
            <p className="nav-empty">
              Showing the first 50 matches. Refine your search to narrow the
              results.
            </p>
          )}
          {search && !pages.length && (
            <p className="nav-empty">
              {results ? "No pages match your search." : "Searching…"}
            </p>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection">
            <span className={connected ? "live-dot" : "offline-dot"} />
            {pinned
              ? "Historical publication"
              : connected
                ? "Live · updates automatically"
                : "Checking for updates"}
          </div>
          <button className="subtle-button" onClick={() => api.logout()}>
            Sign out <span aria-hidden="true">↗</span>
          </button>
        </div>
      </aside>
      <div className="main-area">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="Toggle navigation"
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
          >
            ☰
          </button>
          <div className="breadcrumb">
            Wiki <span>/</span>{" "}
            <strong>{page?.title || "Your knowledge"}</strong>
          </div>
          <div className="topbar-actions">
            <label className="publication-control">
              <span className="sr-only">Publication</span>
              <select
                aria-label="Publication"
                value={pinned || "live"}
                onChange={(e) => {
                  if (e.target.value === "more") {
                    void api
                      .listPublications(historyOffset.current, 50)
                      .then((rows) => {
                        historyOffset.current += rows.length;
                        setMoreHistory(rows.length === 50);
                        setPublications((previous) =>
                          [
                            ...new Map(
                              [...previous, ...rows].map((p) => [p.id, p]),
                            ).values(),
                          ].sort((a, b) => b.sequence - a.sequence),
                        );
                      })
                      .catch((e) => setError(message(e)));
                  } else navigatePublication(e.target.value);
                }}
              >
                <option value="live">Live publication</option>
                {publications.map((p) => (
                  <option key={p.id} value={p.id}>
                    Publication {p.sequence}
                  </option>
                ))}
                {moreHistory && (
                  <option value="more">Load older publications…</option>
                )}
              </select>
            </label>
            <button
              className="icon-button"
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? "☼" : "☾"}
            </button>
          </div>
        </header>
        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button onClick={() => void load()}>Retry</button>
          </div>
        )}
        {pinned && (
          <div className="history-banner">
            Viewing publication {snapshot?.publication.sequence}.{" "}
            <button onClick={() => navigatePublication("live")}>
              Return to live
            </button>
          </div>
        )}
        <div className="reading-layout">
          <main
            id="reader"
            ref={reader}
            className="reader"
            tabIndex={-1}
            aria-busy={busy}
          >
            {page ? (
              <article>
                <div className="page-eyebrow">
                  <span>{page.kind || "WIKI PAGE"}</span>
                  <span className="quiet">
                    Publication {snapshot?.publication.sequence}
                  </span>
                </div>
                <h1 className="page-title">{page.title}</h1>
                {page.summary && <p className="page-summary">{page.summary}</p>}
                <div className="page-rule" />
                <div className="markdown">
                  <Markdown
                    body={page.body}
                    publication={pinned}
                    resolveSlug={resolveSlug}
                    onCitation={openCitation}
                  />
                </div>
                {page.citations.length > 0 && (
                  <section className="sources-section">
                    <h2>Sources</h2>
                    {page.citations.map((c) => (
                      <button
                        key={c.id}
                        className="source-row"
                        onClick={(event) => {
                          lastCitationFocus.current = event.currentTarget;
                          setEvidence(c);
                        }}
                        aria-label={`Citation ${c.marker}: ${c.source.title}`}
                      >
                        <span className="source-number">{c.marker}</span>
                        <span>
                          <strong>{c.source.title}</strong>
                          <small>
                            {c.passage.locator ||
                              `Passage ${c.passage.ordinal}`}
                          </small>
                        </span>
                        <span aria-hidden="true">↗</span>
                      </button>
                    ))}
                  </section>
                )}
                <footer className="page-footer">
                  Published knowledge, connected to its evidence.
                </footer>
              </article>
            ) : (
              <div className="empty-state">
                <span className="empty-icon">▤</span>
                <h1>
                  {busy
                    ? "Opening your wiki…"
                    : current.slug
                      ? "Page unavailable"
                      : "A home for your knowledge"}
                </h1>
                <p>
                  {current.slug
                    ? "This page is not available in the selected publication. Choose a page from the sidebar."
                    : "Published pages will appear here as your workspace grows."}
                </p>
              </div>
            )}
          </main>
          <aside className="context-panel" aria-label="Page context">
            <div className="context-title">ON THIS PAGE</div>
            {outline.length ? (
              outline.map((item, i) => (
                <button
                  className={`outline-item indent-${item.level}`}
                  key={i}
                  onClick={() =>
                    document
                      .getElementById(item.id)
                      ?.scrollIntoView({ behavior: "smooth" })
                  }
                >
                  {item.title.replace(/[*_`]/g, "")}
                </button>
              ))
            ) : (
              <p className="context-empty">No section headings</p>
            )}
            <div className="context-title backlinks-title">
              BACKLINKS <span>{page?.backlinks.length || 0}</span>
            </div>
            {page?.backlinks.map((p) => (
              <a
                className="backlink"
                key={p.id}
                href={pageHref(p.slug, pinned)}
              >
                ↗ <span>{p.title}</span>
              </a>
            ))}
            {!page?.backlinks.length && (
              <p className="context-empty">
                Connections to this page will appear here.
              </p>
            )}
            {Boolean(page?.links.length) && (
              <>
                <div className="context-title backlinks-title">
                  RELATED PAGES
                </div>
                {page?.links.map((p) => (
                  <a
                    className="backlink"
                    key={p.id}
                    href={pageHref(p.slug, pinned)}
                  >
                    ↗ <span>{p.title}</span>
                  </a>
                ))}
              </>
            )}
            <div className="context-note">
              <span>◈</span>
              <p>
                Every page is part of a bigger picture.
                <br />
                Follow the links. Explore the evidence.
              </p>
            </div>
          </aside>
        </div>
      </div>
      {evidence && (
        <div className="evidence-backdrop" onClick={closeEvidence}>
          <section
            className="evidence-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="evidence-title"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === "Escape") closeEvidence();
              if (e.key === "Tab") {
                const focusable =
                  e.currentTarget.querySelectorAll<HTMLElement>(
                    "button,a[href]",
                  );
                const first = focusable[0],
                  last = focusable[focusable.length - 1];
                if (e.shiftKey && document.activeElement === first) {
                  e.preventDefault();
                  last?.focus();
                } else if (!e.shiftKey && document.activeElement === last) {
                  e.preventDefault();
                  first?.focus();
                }
              }
            }}
          >
            <header>
              <span className="page-eyebrow">
                SOURCE EVIDENCE · {evidence.marker}
              </span>
              <button
                ref={citationClose}
                className="icon-button"
                aria-label="Close evidence"
                onClick={closeEvidence}
              >
                ×
              </button>
            </header>
            <h2 id="evidence-title">{evidence.source.title}</h2>
            <p className="evidence-locator">
              {evidence.passage.locator ||
                `Passage ${evidence.passage.ordinal}`}
            </p>
            <blockquote className="passage">{evidence.passage.body}</blockquote>
            {evidence.note && <p>{evidence.note}</p>}
            <dl>
              <dt>Original</dt>
              <dd>{evidence.source.original_name}</dd>
              {evidence.source.source_date && (
                <>
                  <dt>Source date</dt>
                  <dd>{evidence.source.source_date}</dd>
                </>
              )}
            </dl>
            {original && (
              <a
                className="primary-button"
                href={original}
                onClick={(event) => {
                  event.preventDefault();
                  const popup = window.open("about:blank", "_blank");
                  if (popup) popup.opener = null;
                  void api
                    .originalURL(evidence.source)
                    .then((url) => {
                      if (popup) popup.location.replace(url);
                      else window.location.assign(url);
                    })
                    .catch((error) => {
                      popup?.close();
                      setError(message(error));
                    });
                }}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open original ↗
              </a>
            )}
            <p className="evidence-footnote">
              This passage is preserved from an immutable source.
            </p>
          </section>
        </div>
      )}
    </div>
  );
}
function Login({
  theme,
  setTheme,
}: {
  theme: string;
  setTheme: (value: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const login = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };
  const password = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void login(() =>
      api.loginPassword(
        String(form.get("email")),
        String(form.get("password")),
      ),
    );
  };
  return (
    <main className="login-shell">
      <button
        className="icon-button login-theme"
        aria-label="Switch theme"
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      >
        {theme === "dark" ? "☼" : "☾"}
      </button>
      <section className="login-card">
        <div className="brand-mark large">W</div>
        <div className="page-eyebrow">WIKICONTEXT</div>
        <h1>
          Your knowledge.
          <br />
          Connected.
        </h1>
        <p>
          A quiet place to explore your workspace’s knowledge, follow
          connections and get back to the source.
        </p>
        <button
          className="primary-button google-button"
          disabled={busy}
          onClick={() => void login(() => api.loginGoogle())}
        >
          Continue with Google <span>↗</span>
        </button>
        <p className="login-hint">Sign in with your Workspace account.</p>
        <details>
          <summary>Sign in with a password</summary>
          <form onSubmit={password}>
            <label>
              Email
              <input
                required
                name="email"
                type="email"
                autoComplete="username"
              />
            </label>
            <label>
              Password
              <input
                required
                name="password"
                type="password"
                autoComplete="current-password"
              />
            </label>
            <button className="secondary-button" disabled={busy}>
              Sign in
            </button>
          </form>
        </details>
        {error && (
          <p role="alert" className="login-error">
            {error}
          </p>
        )}
        <div className="login-footer">
          <span className="live-dot" /> Living pages. Traceable sources.
        </div>
      </section>
    </main>
  );
}
