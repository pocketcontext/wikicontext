import { useMemo, useRef, useState } from "react";
import { pageHref } from "./Markdown";
import type { PageSummary, Publication } from "./types";
import {
  filterWelcomePages,
  groupWelcomePages,
  onboardingPages,
} from "./welcome";
import "./welcome.css";

export default function WelcomePage({
  pages,
  publication,
  pinned,
}: {
  pages: PageSummary[];
  publication: Publication | null;
  pinned?: string;
}) {
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState("all");
  const [mode, setMode] = useState<"grouped" | "alphabetical">("grouped");
  const directory = useRef<HTMLHeadingElement>(null);
  const groups = useMemo(() => groupWelcomePages(pages), [pages]);
  const guides = useMemo(() => onboardingPages(pages), [pages]);
  const steps = guides.length ? [guides[0]] : [];
  for (const signal of [
    /\b(setup|install|installation|skills?)\b/i,
    /\b(login|sign.in|authentication)\b/i,
  ]) {
    const guide = guides.find(
      (page) =>
        !steps.includes(page) &&
        signal.test(`${page.title} ${page.slug.replaceAll("-", " ")}`),
    );
    if (guide) steps.push(guide);
  }
  const moreGuides = guides.filter((page) => !steps.includes(page));
  const selected = groups.find((group) => group.id === topic);
  const filtered = filterWelcomePages(selected?.pages ?? pages, query);
  const results =
    mode === "grouped"
      ? groupWelcomePages(filtered)
      : [{ id: "alphabetical", title: "Alphabetical index", pages: filtered }];
  const href = (page: PageSummary) => pageHref(page.slug, pinned);
  const showDirectory = () => {
    directory.current?.scrollIntoView?.({ block: "start" });
    directory.current?.focus({ preventScroll: true });
  };

  return (
    <div className="welcome-page">
      <section className="welcome-hero" aria-labelledby="welcome-heading">
        <div>
          <div className="welcome-eyebrow">The WikiContext wiki</div>
          <h1 id="welcome-heading">
            Welcome to <em>our shared context.</em>
          </h1>
          <p>
            Get started, find an answer, or pick up where someone left off.
            <br />
            Your guide to the people, tools and thinking behind our work.
          </p>
        </div>
        <div className="welcome-stat">
          <strong>{pages.length}</strong>
          <span>pages to explore</span>
        </div>
      </section>

      <div className="welcome-search">
        <span aria-hidden="true">⌕</span>
        <input
          type="search"
          aria-label="Search the page index"
          placeholder="Find a page, topic or guide…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") showDirectory();
            if (event.key === "Escape") {
              event.stopPropagation();
              setQuery("");
            }
          }}
        />
        {query && <button onClick={showDirectory}>See results ↓</button>}
      </div>
      <p className="welcome-search-note">
        Filter page titles, summaries and slugs. Use the sidebar search to
        search page contents.
      </p>

      <section
        className="welcome-onboarding"
        aria-labelledby="welcome-onboarding-heading"
      >
        <div className="welcome-onboard-intro">
          <div className="welcome-eyebrow">Start here</div>
          <h2 id="welcome-onboarding-heading">New to the workspace?</h2>
          <p>
            A short path from getting your workspace ready to finding your first
            workflow.
          </p>
          {guides[0] ? (
            <a className="welcome-primary" href={href(guides[0])}>
              Open onboarding <span aria-hidden="true">→</span>
            </a>
          ) : (
            <p>No onboarding guides are published in this view yet.</p>
          )}
        </div>
        {guides.length > 0 && (
          <div className="welcome-steps">
            {steps.map((page, index) => (
              <a className="welcome-step" href={href(page)} key={page.page}>
                <span className="welcome-step-number" aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span>
                  <strong>{page.title}</strong>
                  {page.summary && <small>{page.summary}</small>}
                </span>
                <span className="welcome-arrow" aria-hidden="true">
                  →
                </span>
              </a>
            ))}
          </div>
        )}
        {moreGuides.length > 0 && (
          <div className="welcome-guides">
            <span>More guides</span>
            {moreGuides.map((page) => (
              <a href={href(page)} key={page.page}>
                {page.title} <span aria-hidden="true">→</span>
              </a>
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="welcome-topics-heading">
        <div className="welcome-section-heading">
          <div>
            <h2 id="welcome-topics-heading">Explore by topic</h2>
            <p>Find a starting point, then follow the connections.</p>
          </div>
          <button
            onClick={() => {
              setTopic("all");
              setQuery("");
              showDirectory();
            }}
          >
            Browse all pages ↓
          </button>
        </div>
        <div className="welcome-topics">
          {groups
            .filter((group) => group.id !== "other" || group.pages.length > 0)
            .map((group, index) => (
              <button
                className="welcome-topic"
                aria-pressed={topic === group.id}
                key={group.id}
                onClick={() => {
                  setTopic(group.id);
                  setQuery("");
                  showDirectory();
                }}
              >
                <span className="welcome-topic-top">
                  <span aria-hidden="true">
                    {["↗", "◇", "▦", "⌘", "◎", "✧", "≡", "◷", "+"][index]}
                  </span>
                  <small>{group.pages.length} pages</small>
                </span>
                <strong>{group.title}</strong>
                <span className="welcome-topic-description">
                  {group.description}
                </span>
                <span className="welcome-topic-arrow" aria-hidden="true">
                  →
                </span>
              </button>
            ))}
        </div>
      </section>

      <section
        className="welcome-directory"
        aria-labelledby="welcome-directory-heading"
      >
        <div className="welcome-section-heading">
          <div>
            <h2 id="welcome-directory-heading" ref={directory} tabIndex={-1}>
              The complete page index
            </h2>
            <p>Every published page in this view.</p>
          </div>
        </div>
        <div className="welcome-controls">
          <div className="welcome-filter-info">
            <strong>{selected?.title ?? "All topics"}</strong>
            <span role="status">
              {filtered.length} of {pages.length} pages
            </span>
            {(query || topic !== "all") && (
              <button
                onClick={() => {
                  setQuery("");
                  setTopic("all");
                }}
              >
                Clear filters
              </button>
            )}
          </div>
          <div
            className="welcome-segmented"
            role="group"
            aria-label="Index view"
          >
            <button
              aria-pressed={mode === "grouped"}
              onClick={() => setMode("grouped")}
            >
              By topic
            </button>
            <button
              aria-pressed={mode === "alphabetical"}
              onClick={() => setMode("alphabetical")}
            >
              A–Z
            </button>
          </div>
        </div>
        {results
          .filter((group) => group.pages.length > 0)
          .map((group) => (
            <section
              className="welcome-index-group"
              aria-labelledby={`welcome-group-${group.id}`}
              key={group.id}
            >
              <div className="welcome-group-heading">
                <h3 id={`welcome-group-${group.id}`}>{group.title}</h3>
                <span>{group.pages.length}</span>
              </div>
              <ul className="welcome-entries">
                {group.pages.map((page) => (
                  <li key={page.page}>
                    <a href={href(page)} title={page.summary || undefined}>
                      <span>{page.title}</span>
                      <span aria-hidden="true">→</span>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        {filtered.length === 0 && (
          <p className="welcome-empty">
            {pages.length
              ? "No pages match these filters. Try another term or clear the filters."
              : "No pages have been published in this view yet."}
          </p>
        )}
      </section>
      <footer className="welcome-footer">
        <span>A shared place for what we know.</span>
        <span>
          {publication
            ? `${pinned ? "Historical" : "Live"} publication ${publication.sequence}`
            : "No publication yet"}
        </span>
      </footer>
    </div>
  );
}
