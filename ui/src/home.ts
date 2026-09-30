import type { PageSummary, Publication } from "./types";

/** Page summaries are already ordered by immutable slug by the API. */
export function homePageSlug(publication: Publication, pages: PageSummary[]): string | undefined {
  return pages.find(page => page.page === publication.home)?.slug || pages[0]?.slug;
}
