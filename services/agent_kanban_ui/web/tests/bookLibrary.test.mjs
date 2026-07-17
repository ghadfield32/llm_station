import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/bookLibrary.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText;
const module = { exports: {} };
new Function("exports", "module", compiled)(module.exports, module);
const {
  BOOK_GROUP_FIELDS,
  BOOK_MISSING_VALUE,
  EMPTY_BOOK_FILTERS,
  bookFacetOptions,
  bookMatchesLibraryFilters,
  sortBooks,
} = module.exports;

const cards = [
  {
    card_id: "book-shannon",
    title: "A Mind at Play",
    author: "Soni & Goodman",
    tier: "Optional",
    genre: "Biography",
    genres: ["Biography & Autobiography", "Computers"],
    module: "Computing",
    section: "12",
    type: "Print",
    recommended_format: "Audiobook",
    languages: ["eng"],
    publishers: ["Simon & Schuster"],
    status: "Reading",
    hours: "10",
    notes: "Claude Shannon and information theory.",
    current_chapter: "The idea factory",
    current_page: 90,
    total_pages: 384,
    book_notes: [{ text: "A useful relay insight.", chapter: "The idea factory" }],
  },
  {
    card_id: "book-essential",
    title: "Essential Systems",
    author: "Ada Author",
    tier: "Essential",
    module: "Computing",
    section: "2",
    status: "To read",
    hours: "5",
    book_notes: [],
  },
  {
    card_id: "book-untagged",
    title: "Untagged Book",
    author: "",
    status: "To read",
    book_notes: [],
  },
];

test("every meaningful categorical book grouping is registered", () => {
  assert.deepEqual(
    BOOK_GROUP_FIELDS.map((field) => field.key),
    [
      "tier", "author", "genre", "module", "section", "type",
      "recommended_format", "language", "publisher",
    ],
  );
});

test("facet options include exact counts and an explicit missing bucket", () => {
  assert.deepEqual(bookFacetOptions(cards, "tier"), [
    { value: "Essential", label: "Essential", count: 1 },
    { value: "Optional", label: "Optional", count: 1 },
    { value: BOOK_MISSING_VALUE, label: "Not set", count: 1 },
  ]);
  assert.deepEqual(bookFacetOptions(cards, "genre"), [
    { value: "Biography", label: "Biography", count: 1 },
    { value: "Biography & Autobiography", label: "Biography & Autobiography", count: 1 },
    { value: "Computers", label: "Computers", count: 1 },
    { value: BOOK_MISSING_VALUE, label: "Not set", count: 2 },
  ]);
});

test("facets compose with keyword, notes, position, length, and progress filters", () => {
  const filters = {
    ...EMPTY_BOOK_FILTERS,
    facets: {
      tier: "Optional",
      author: "Soni & Goodman",
      genre: "Biography",
      module: "Computing",
      section: "12",
      type: "Print",
      recommended_format: "Audiobook",
      language: "eng",
      publisher: "Simon & Schuster",
    },
    noteState: "with",
    readingState: "started",
    minHours: 8,
    maxHours: 12,
    minProgress: 20,
    maxProgress: 30,
  };
  assert.equal(
    bookMatchesLibraryFilters(cards[0], "relay information", filters), true);
  assert.equal(bookMatchesLibraryFilters(cards[1], "", filters), false);
  assert.equal(bookMatchesLibraryFilters(cards[2], "", {
    ...EMPTY_BOOK_FILTERS,
    facets: { genre: BOOK_MISSING_VALUE, author: BOOK_MISSING_VALUE },
  }), true);
});

test("every registered grouping can sort in either direction", () => {
  const sortable = [
    "title", "status", ...BOOK_GROUP_FIELDS.map((field) => field.key),
    "hours", "progress", "notes",
  ];
  for (const field of sortable) {
    assert.equal(sortBooks(cards, field, "asc").length, cards.length);
    assert.equal(sortBooks(cards, field, "desc").length, cards.length);
  }
  assert.equal(sortBooks(cards, "author", "asc")[0].card_id, "book-essential");
  assert.equal(sortBooks(cards, "tier", "asc")[0].card_id, "book-essential");
  assert.equal(sortBooks(cards, "hours", "desc")[0].card_id, "book-shannon");
  assert.equal(sortBooks(cards, "progress", "desc")[0].card_id, "book-shannon");
  assert.equal(sortBooks(cards, "notes", "desc")[0].card_id, "book-shannon");
});
