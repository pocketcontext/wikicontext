import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import * as readerAPI from "./api";
import EvidenceBrowser from "./EvidenceBrowser";

vi.mock("./ImagePreview", () => ({ default: () => null }));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("reloads evidence when a background copy completes without another navigation", async () => {
  vi.spyOn(readerAPI, "query")
    .mockResolvedValueOnce([{ id: "source000000001", title: "Earlier source" }])
    .mockResolvedValueOnce([{ id: "source000000002", title: "New source" }]);
  const props = {
    space: "companyspace001",
    collection: "sources" as const,
    id: "",
    term: "",
    publication: "",
    offset: 0,
    navigation: null,
  };
  const view = render(<EvidenceBrowser {...props} snapshotGeneration="old" />);
  await screen.findByRole("link", { name: "Earlier source" });
  view.rerender(<EvidenceBrowser {...props} snapshotGeneration="new" />);
  await screen.findByRole("link", { name: "New source" });
  expect(screen.queryByRole("link", { name: "Earlier source" })).toBeNull();
});

it("keeps a deep-linked source visible when it is outside the result page, without listing raw IDs", async () => {
  const selected = { id: "source000000001", title: "Synthetic source" };
  vi.spyOn(readerAPI, "query")
    .mockResolvedValueOnce([{ id: "source000000002", title: "Other source" }])
    .mockResolvedValueOnce([selected])
    .mockResolvedValueOnce([
      {
        ...selected,
        original_name: "slide.png",
        original: "slide.png",
        media_type: "image/png",
        source_date: "",
        sha256: "synthetic",
      },
    ]);
  const onTitleChange = vi.fn();
  render(
    <EvidenceBrowser
      space="companyspace001"
      collection="sources"
      id={selected.id}
      term=""
      publication=""
      offset={20}
      navigation={null}
      onTitleChange={onTitleChange}
    />,
  );
  const current = await screen.findByRole("navigation", {
    name: "Current evidence record",
  });
  expect(
    within(current).getByRole("link", { name: selected.title }),
  ).toHaveAttribute("aria-current", "page");
  expect(current).not.toHaveTextContent(selected.id);
  expect(
    screen.getByRole("link", { name: "View source passages" }),
  ).toHaveAttribute("href", `#/passages/?q=${selected.id}`);
  expect(
    screen.getByRole("group", { name: "Record actions" }),
  ).toContainElement(screen.getByRole("button", { name: "Download original" }));
  expect(onTitleChange).toHaveBeenLastCalledWith(selected.title);
  expect(readerAPI.query).toHaveBeenNthCalledWith(
    1,
    expect.stringContaining("WHERE s.space='companyspace001' AND"),
  );
  expect(readerAPI.query).toHaveBeenNthCalledWith(
    2,
    expect.stringContaining("WHERE s.space='companyspace001' AND"),
  );
});

it("verifies a source-scoped passage before highlighting the original and keeps fixed links", async () => {
  const previews = await import("./sourcePreview");
  vi.spyOn(previews, "sourceText").mockResolvedValue("First\nSecond\nFirst");
  const source = {
    id: "source000000001",
    title: "Text source",
    original_name: "note.txt",
    original: "note.txt",
    media_type: "text/plain",
    source_date: "",
    sha256: "a".repeat(64),
  };
  const passage = {
    id: "passage00000001",
    body: "First",
    locator: "document; characters 14-18",
    kind: "text",
    ordinal: 2,
  };
  vi.spyOn(readerAPI, "query")
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([source])
    .mockResolvedValueOnce([source])
    .mockResolvedValueOnce([passage]);
  const { container } = render(
    <EvidenceBrowser
      space="companyspace001"
      collection="sources"
      id={source.id}
      passage={passage.id}
      term=""
      publication="publication0001"
      offset={0}
      navigation={null}
    />,
  );
  await screen.findByText("Cited passage");
  expect(container.querySelector(".source-content mark")).toHaveTextContent(
    "First",
  );
  expect(container.querySelector(".source-content pre")?.textContent).toBe(
    "First\nSecond\nFirst",
  );
  expect(readerAPI.query).toHaveBeenLastCalledWith(
    expect.stringContaining(
      "p.space='companyspace001' AND r.source='source000000001'",
    ),
  );
});

it("never highlights a passage unavailable in the source's authorized space", async () => {
  const previews = await import("./sourcePreview");
  vi.spyOn(previews, "sourceText").mockResolvedValue("Private source");
  const source = {
    id: "source000000001",
    title: "Text source",
    original_name: "note.txt",
    original: "note.txt",
    media_type: "text/plain",
    source_date: "",
    sha256: "a".repeat(64),
  };
  vi.spyOn(readerAPI, "query")
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([source])
    .mockResolvedValueOnce([source])
    .mockResolvedValueOnce([]);
  const { container } = render(
    <EvidenceBrowser
      space="companyspace001"
      collection="sources"
      id={source.id}
      passage="passage00000001"
      term=""
      publication=""
      offset={0}
      navigation={null}
    />,
  );
  await screen.findByText("This passage is unavailable for this original.");
  expect(container.querySelector("mark")).toBeNull();
});

it("aborts a protected original when leaving its view and ignores its late response", async () => {
  const previews = await import("./sourcePreview");
  let finish!: (value: string) => void;
  const read = vi.spyOn(previews, "sourceText").mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const source = {
    id: "source000000001",
    title: "Text source",
    original_name: "note.txt",
    original: "note.txt",
    media_type: "text/plain",
    source_date: "",
    sha256: "a".repeat(64),
  };
  vi.spyOn(readerAPI, "query")
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce([source])
    .mockResolvedValueOnce([source]);
  const view = render(
    <EvidenceBrowser
      space="companyspace001"
      collection="sources"
      id={source.id}
      term=""
      publication=""
      offset={0}
      navigation={null}
    />,
  );
  await screen.findByText("Loading verified original…");
  await vi.waitFor(() => expect(read).toHaveBeenCalled());
  const signal = read.mock.calls[0][1]!;
  view.unmount();
  expect(signal.aborted).toBe(true);
  finish("Late private original");
  expect(screen.queryByText("Late private original")).toBeNull();
});
