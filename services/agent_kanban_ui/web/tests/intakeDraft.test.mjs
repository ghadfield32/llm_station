import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/intakeDraft.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText;
const module = { exports: {} };
new Function("exports", "module", compiled)(module.exports, module);
const { buildRunDocDraft } = module.exports;

test("buildRunDocDraft assembles the PROC-2 intake sections", () => {
  const answers = {
    objective: "Ship a guided intake with a checkable definition of done.",
    research: "Verified the existing prepare-to-chat seam in App.tsx.",
    kpis: "Baseline is unmeasured; step 1 measures blank chat starts.",
    plan: "1. Build the helper.\n2. Add the stepped wizard.",
    openQuestions: "Decision: keep persistence out of packet 1.",
  };

  const draft = buildRunDocDraft(answers, "Guided intake wizard", "KAN-11");

  assert.match(draft, /^# RUNDOC — KAN-11 · Guided intake wizard/m);
  for (const heading of [
    "## 1. Objective & definition of done",
    "## 2. Research",
    "## 3. KPIs & baseline",
    "## 4. Plan (bounded)",
    "## 5. Open questions / decisions",
  ]) {
    assert.ok(draft.includes(heading), `missing heading: ${heading}`);
  }
  for (const answer of Object.values(answers)) {
    assert.ok(draft.includes(answer), `missing answer: ${answer}`);
  }
});

test("buildRunDocDraft fills placeholders for empty answers and title/itemId", () => {
  const draft = buildRunDocDraft(
    { objective: "", research: "  ", kpis: "", plan: "", openQuestions: "" },
    "", "");
  assert.match(draft, /^# RUNDOC — UNASSIGNED · Untitled project/m);
  assert.ok(draft.includes("_Not answered yet._"));
});
