export interface Publication {
  id: string;
  sequence: number;
  run: string;
  created: string;
}

export interface PageSummary {
  /** Immutable revision identity. */
  id: string;
  /** Stable page identity. */
  page: string;
  slug: string;
  kind: string;
  title: string;
  summary: string;
}

export interface Source {
  id: string;
  title: string;
  original_name: string;
  original: string;
  media_type: string;
  source_date: string;
  sha256: string;
}

export interface Passage {
  id: string;
  ordinal: number;
  locator: string;
  body: string;
}

export interface Citation {
  id: string;
  marker: string;
  note: string;
  passage: Passage;
  source: Source;
}

export interface PageDetail extends PageSummary {
  body: string;
  citations: Citation[];
  backlinks: PageSummary[];
  links: PageSummary[];
}
