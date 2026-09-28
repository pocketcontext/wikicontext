import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, SearchChangedError, type SearchPage } from "./api";
import SearchResults from "./SearchResults";

const hit = (id: string) => ({
  id,
  page: id,
  slug: id,
  title: id,
  kind: "concept",
  summary: "",
  score: -1,
  excerpt: "<img src=x onerror=alert(1)>",
});
const batch = (id: string, more = true): SearchPage => ({
  generation: "g1",
  hits: [hit(id)],
  hasMore: more,
});
afterEach(() => vi.restoreAllMocks());
it("renders excerpts as text, appends one generation, and clears mixed results on conflict", async () => {
  const search = vi
    .spyOn(api, "searchPages")
    .mockResolvedValueOnce(batch("first"))
    .mockResolvedValueOnce(batch("second"))
    .mockRejectedValueOnce(new SearchChangedError())
    .mockResolvedValueOnce(batch("new", false));
  render(
    <SearchResults
      publication="publication0001"
      query="term"
      visible
      epoch={0}
    />,
  );
  await screen.findByRole("link", { name: "first" });
  expect(document.querySelector("img")).toBeNull();
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Load more results" }));
  await screen.findByRole("link", { name: "second" });
  expect(search.mock.calls[1]).toEqual([
    "publication0001",
    "term",
    1,
    20,
    "g1",
  ]);
  fireEvent.click(screen.getByRole("button", { name: "Load more results" }));
  await screen.findByRole("button", { name: "Restart search" });
  expect(screen.queryByRole("link", { name: "first" })).toBeNull();
  expect(screen.queryByRole("link", { name: "second" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Restart search" }));
  await screen.findByRole("link", { name: "new" });
});
it("ignores old pending requests after a query or publication change", async () => {
  let finish!: (page: SearchPage) => void;
  vi.spyOn(api, "searchPages")
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    )
    .mockResolvedValueOnce(batch("current", false));
  const rendered = render(
    <SearchResults
      publication="publication0001"
      query="old"
      visible
      epoch={0}
    />,
  );
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  rendered.rerender(
    <SearchResults
      publication="publication0002"
      query="new"
      visible
      epoch={0}
    />,
  );
  await screen.findByRole("link", { name: "current" });
  await act(async () => finish(batch("stale")));
  expect(screen.queryByRole("link", { name: "stale" })).toBeNull();
  expect(screen.getByRole("link", { name: "current" })).toBeVisible();
});
