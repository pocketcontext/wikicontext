import type { PageSummary, Publication } from "./types";

/** No selection means the built-in welcome index, rather than an arbitrary page. */
export function homePageSlug(publication: Publication, pages: PageSummary[]): string | undefined {
  return pages.find(page => page.page === publication.home)?.slug;
}
