export type BookCard = {
  card_id?: unknown;
  status?: unknown;
  [key: string]: unknown;
};

export type BookFacetKey =
  | "tier"
  | "author"
  | "genre"
  | "module"
  | "section"
  | "type"
  | "recommended_format"
  | "language"
  | "publisher";
export type BookNoteFilter = "" | "with" | "without";
export type BookReadingFilter = "" | "started" | "not-started";
export type BookSortDirection = "asc" | "desc";
export type BookSortField =
  | "title"
  | "status"
  | BookFacetKey
  | "hours"
  | "first_publish_year"
  | "page_count_median"
  | "progress"
  | "notes";

export type BookLibraryFilterState = {
  facets: Partial<Record<BookFacetKey, string>>;
  noteState: BookNoteFilter;
  readingState: BookReadingFilter;
  minHours: number | null;
  maxHours: number | null;
  minProgress: number | null;
  maxProgress: number | null;
  sortBy: BookSortField;
  sortDirection: BookSortDirection;
};

export const BOOK_MISSING_VALUE = "__book_field_not_set__";

export const BOOK_GROUP_FIELDS: ReadonlyArray<{
  key: BookFacetKey;
  label: string;
}> = [
  { key: "tier", label: "Priority" },
  { key: "author", label: "Author" },
  { key: "genre", label: "Genre" },
  { key: "module", label: "Collection / module" },
  { key: "section", label: "Section" },
  { key: "type", label: "Format / source label" },
  { key: "recommended_format", label: "Recommended format" },
  { key: "language", label: "Language" },
  { key: "publisher", label: "Publisher" },
];

export const BOOK_SORT_FIELDS: ReadonlyArray<{
  key: BookSortField;
  label: string;
}> = [
  { key: "title", label: "Title" },
  { key: "status", label: "Status" },
  ...BOOK_GROUP_FIELDS,
  { key: "hours", label: "Approx. audio length" },
  { key: "first_publish_year", label: "First published" },
  { key: "page_count_median", label: "Median page count" },
  { key: "progress", label: "Reading progress" },
  { key: "notes", label: "Note count" },
];

export const EMPTY_BOOK_FILTERS: BookLibraryFilterState = {
  facets: {},
  noteState: "",
  readingState: "",
  minHours: null,
  maxHours: null,
  minProgress: null,
  maxProgress: null,
  sortBy: "title",
  sortDirection: "asc",
};

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(text).filter(Boolean).join(" ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function bookNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(text(value));
  return Number.isFinite(parsed) ? parsed : null;
}

export function bookHours(card: BookCard): number | null {
  const value = bookNumber(card.hours);
  return value !== null && value >= 0 ? value : null;
}

export function bookProgress(card: BookCard): number | null {
  const explicit = bookNumber(card.progress_percent);
  if (explicit !== null && explicit >= 0 && explicit <= 100) return explicit;
  const page = bookNumber(card.current_page);
  const total = bookNumber(card.total_pages);
  if (page === null || total === null || total <= 0 || page < 0 || page > total) {
    return null;
  }
  return Math.round((page / total) * 100);
}

export function bookNoteCount(card: BookCard): number {
  const overview = text(card.notes).trim() ? 1 : 0;
  return overview + (Array.isArray(card.book_notes) ? card.book_notes.length : 0);
}

export function bookHasNotes(card: BookCard): boolean {
  return bookNoteCount(card) > 0;
}

export function bookHasPosition(card: BookCard): boolean {
  return !!text(card.current_chapter).trim()
    || bookNumber(card.current_page) !== null
    || bookProgress(card) !== null;
}

function bookSearchText(card: BookCard): string {
  return [
    card.title, card.author, card.description, card.genre, card.genres, card.tier,
    card.module, card.section, card.type, card.recommended_format,
    card.language, card.languages, card.publisher, card.publishers,
    card.isbn, card.isbns, card.subjects, card.first_publish_year,
    card.page_count_median, card.notes,
    card.current_chapter, card.book_notes,
  ].map(text).join(" ").normalize("NFKC").toLocaleLowerCase();
}

function facetValues(card: BookCard, field: BookFacetKey): string[] {
  const fields: unknown[] = field === "genre"
    ? [card.genre, card.genres]
    : field === "language"
      ? [card.language, card.languages]
      : field === "publisher"
        ? [card.publisher, card.publishers]
        : [card[field]];
  const values = fields.flatMap((value) => Array.isArray(value) ? value : [value])
    .map(text).map((value) => value.trim()).filter(Boolean);
  return [...new Set(values)];
}

function facetMatches(card: BookCard, field: BookFacetKey, selected: string): boolean {
  const values = facetValues(card, field);
  return selected === BOOK_MISSING_VALUE
    ? values.length === 0
    : values.includes(selected);
}

export function bookFacetOptions(
  cards: BookCard[],
  field: BookFacetKey,
): Array<{ value: string; label: string; count: number }> {
  const counts = new Map<string, number>();
  let missing = 0;
  cards.forEach((card) => {
    const values = facetValues(card, field);
    if (!values.length) {
      missing += 1;
      return;
    }
    values.forEach((value) => counts.set(value, (counts.get(value) ?? 0) + 1));
  });
  const options = [...counts].sort(([left], [right]) =>
    left.localeCompare(right, undefined, { sensitivity: "base", numeric: true }))
    .map(([value, count]) => ({ value, label: value, count }));
  if (missing > 0) {
    options.push({ value: BOOK_MISSING_VALUE, label: "Not set", count: missing });
  }
  return options;
}

export function bookMatchesLibraryFilters(
  card: BookCard,
  query: string,
  filters: BookLibraryFilterState,
): boolean {
  const tokens = query.normalize("NFKC").toLocaleLowerCase()
    .split(/\s+/).filter(Boolean);
  const haystack = bookSearchText(card);
  if (!tokens.every((token) => haystack.includes(token))) return false;
  for (const field of BOOK_GROUP_FIELDS) {
    const selected = filters.facets[field.key];
    if (selected && !facetMatches(card, field.key, selected)) return false;
  }
  const hasNotes = bookHasNotes(card);
  if (filters.noteState === "with" && !hasNotes) return false;
  if (filters.noteState === "without" && hasNotes) return false;
  const hasPosition = bookHasPosition(card);
  if (filters.readingState === "started" && !hasPosition) return false;
  if (filters.readingState === "not-started" && hasPosition) return false;
  if (filters.minHours !== null || filters.maxHours !== null) {
    const hours = bookHours(card);
    if (hours === null) return false;
    if (filters.minHours !== null && hours < filters.minHours) return false;
    if (filters.maxHours !== null && hours > filters.maxHours) return false;
  }
  if (filters.minProgress !== null || filters.maxProgress !== null) {
    const progress = bookProgress(card);
    if (progress === null) return false;
    if (filters.minProgress !== null && progress < filters.minProgress) return false;
    if (filters.maxProgress !== null && progress > filters.maxProgress) return false;
  }
  return true;
}

const BOOK_PRIORITY_ORDER: Record<string, number> = {
  essential: 0,
  companion: 1,
  reference: 2,
  fun: 3,
  optional: 4,
};

function compareText(left: string, right: string): number {
  return left.localeCompare(
    right, undefined, { sensitivity: "base", numeric: true });
}

function compareKnown<T>(
  left: T | null,
  right: T | null,
  direction: BookSortDirection,
  compare: (a: T, b: T) => number,
): number {
  if (left === null && right === null) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  const result = compare(left, right);
  return direction === "desc" ? -result : result;
}

function sortValue(card: BookCard, field: BookSortField): string | number | null {
  if (field === "hours") return bookHours(card);
  if (field === "first_publish_year" || field === "page_count_median") {
    return bookNumber(card[field]);
  }
  if (field === "progress") return bookProgress(card);
  if (field === "notes") return bookNoteCount(card);
  if (BOOK_GROUP_FIELDS.some((item) => item.key === field)) {
    const values = facetValues(card, field as BookFacetKey);
    return values.sort(compareText).join(" · ") || null;
  }
  const value = text(card[field]).trim();
  return value || null;
}

export function sortBooks<T extends BookCard>(
  cards: T[],
  field: BookSortField,
  direction: BookSortDirection,
): T[] {
  return [...cards].sort((left, right) => {
    let result: number;
    if (field === "tier") {
      const leftValue = text(left.tier).trim();
      const rightValue = text(right.tier).trim();
      const leftRank = leftValue
        ? BOOK_PRIORITY_ORDER[leftValue.toLocaleLowerCase()] ?? 99 : null;
      const rightRank = rightValue
        ? BOOK_PRIORITY_ORDER[rightValue.toLocaleLowerCase()] ?? 99 : null;
      result = compareKnown(
        leftRank, rightRank, direction, (a, b) => a - b,
      ) || compareKnown(
        leftValue || null, rightValue || null, direction, compareText,
      );
    } else {
      const leftValue = sortValue(left, field);
      const rightValue = sortValue(right, field);
      result = typeof leftValue === "number" || typeof rightValue === "number"
        ? compareKnown(
          typeof leftValue === "number" ? leftValue : null,
          typeof rightValue === "number" ? rightValue : null,
          direction,
          (a, b) => a - b,
        )
        : compareKnown(
          leftValue as string | null,
          rightValue as string | null,
          direction,
          compareText,
        );
    }
    const titleResult = compareKnown(
      text(left.title).trim() || null,
      text(right.title).trim() || null,
      "asc",
      compareText,
    );
    return result || titleResult;
  });
}
