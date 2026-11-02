import { describe, expect, it } from "vitest";
import { readReaderRoute } from "./readerRoutes";

describe("reader routes", () => {
  it("leaves custom ordering unset so the published definition supplies it", () => {
    expect(
      readReaderRoute("#/catalog/custom/research").catalogState,
    ).toMatchObject({ custom: "research", sort: "" });
    expect(
      readReaderRoute("#/catalog/custom/research?sort=title").catalogState.sort,
    ).toBe("title");
    expect(
      readReaderRoute("#/catalog/custom/research?sort=-priority").catalogState
        .sort,
    ).toBe("-priority");
  });
  it("retains normal built-in catalog defaults", () => {
    expect(readReaderRoute("#/catalog/resource").catalogState).toMatchObject({
      type: "resource",
      sort: "title",
      custom: undefined,
    });
    expect(readReaderRoute("#/catalog/audio_recording").catalogState.type).toBe(
      "audio_recording",
    );
    expect(readReaderRoute("#/welcome").catalogState.type).toBe("resource");
  });
  it.each(["#/catalog/missing", "#/catalog/resource/extra", "#/catalog/"])(
    "does not silently substitute Resources for %s",
    (hash) => {
      expect(readReaderRoute(hash).catalogState.type).toBe("unavailable");
    },
  );
  it("retains evidence history, authorized space selection and cited source range", () => {
    expect(
      readReaderRoute(
        "#/sources/source000000001?space=space0000000001&publication=publication0001&passage=passage00000001",
      ),
    ).toMatchObject({
      collection: "sources",
      record: "source000000001",
      space: "space0000000001",
      publication: "publication0001",
      passage: "passage00000001",
    });
  });
  it("recognizes both the page directory and legacy topic links", () => {
    expect(
      readReaderRoute("#/pages?topic=research&filter=stars&sort=-title"),
    ).toMatchObject({
      directory: true,
      slug: "",
      topic: "research",
      filter: "stars",
      sort: "-title",
    });
    expect(readReaderRoute("#/welcome?topic=research").directory).toBe(true);
    expect(readReaderRoute("#/welcome").directory).toBe(false);
  });
});
