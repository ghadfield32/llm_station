import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/researchProgress.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText;
const module = { exports: {} };
new Function("exports", "module", compiled)(module.exports, module);
const { exactResearchProgressCounts } = module.exports;

const zero = {
  total: 0, titled: 0, complete: 0, pending: 0, missing_title: 0,
};
const paperLoaded = {
  total: 100, titled: 100, complete: 2, pending: 98, missing_title: 0,
};
const repoLoaded = {
  total: 10, titled: 10, complete: 4, pending: 6, missing_title: 0,
};

test("progress reports only exact committed strict counts", () => {
  assert.deepEqual(exactResearchProgressCounts(paperLoaded), paperLoaded);
});

test("pending and missing-title counts are derived from exact totals", () => {
  assert.deepEqual(exactResearchProgressCounts({
    total: 12, titled: 10, complete: 4, pending: 999, missing_title: 999,
  }), {
    total: 12, titled: 10, complete: 4, pending: 6, missing_title: 2,
  });
});

test("late unloaded sources remain exact instead of inheriting another source", () => {
  assert.deepEqual(exactResearchProgressCounts(zero), zero);
  assert.deepEqual(exactResearchProgressCounts(repoLoaded), repoLoaded);
});

test("invalid or stale counts are clamped to the exact count hierarchy", () => {
  assert.deepEqual(exactResearchProgressCounts({
    total: 5.9, titled: 9, complete: 12, pending: -1, missing_title: -1,
  }), {
    total: 5, titled: 5, complete: 5, pending: 0, missing_title: 0,
  });
});
