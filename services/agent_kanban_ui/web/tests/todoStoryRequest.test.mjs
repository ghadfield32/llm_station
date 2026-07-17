import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/todoStoryRequest.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText;
const module = { exports: {} };
new Function("exports", "module", compiled)(module.exports, module);
const {
  TodoStoryRequestGate,
  TodoStoryMutationGate,
  isDescriptionConflictStatus,
} = module.exports;

test("a newer story request aborts and supersedes an older response", () => {
  const gate = new TodoStoryRequestGate();
  const older = gate.begin();
  const newer = gate.begin();
  assert.equal(older.signal.aborted, true);
  assert.equal(gate.isCurrent(older), false);
  assert.equal(gate.isCurrent(newer), true);
});

test("closing the drawer aborts the active load and rejects its late response", () => {
  const gate = new TodoStoryRequestGate();
  const active = gate.begin();
  gate.close();
  assert.equal(active.signal.aborted, true);
  assert.equal(gate.isCurrent(active), false);
});

test("the same generation gate rejects a late inventory filter response", () => {
  const gate = new TodoStoryRequestGate();
  const oldFilter = gate.begin();
  const currentFilter = gate.begin();
  assert.equal(oldFilter.signal.aborted, true);
  assert.equal(gate.isCurrent(oldFilter), false);
  assert.equal(gate.isCurrent(currentFilter), true);
});

test("only HTTP 409 establishes the stale-description conflict state", () => {
  assert.equal(isDescriptionConflictStatus(409), true);
  assert.equal(isDescriptionConflictStatus(400), false);
  assert.equal(isDescriptionConflictStatus(503), false);
});

test("opening another story invalidates a late description mutation", () => {
  const gate = new TodoStoryMutationGate();
  const storyA = gate.begin("work:A");
  gate.invalidate();
  assert.equal(storyA.signal.aborted, true);
  assert.equal(gate.isCurrent(storyA, "work:B"), false);
});

test("closing a story invalidates a late 409 from its description mutation", () => {
  const gate = new TodoStoryMutationGate();
  const active = gate.begin("work:A");
  gate.invalidate();
  assert.equal(active.signal.aborted, true);
  assert.equal(gate.isCurrent(active, null), false);
});

test("selecting another TODO aborts and rejects a late assignment response", () => {
  const gate = new TodoStoryMutationGate();
  const firstAssignment = gate.begin("capture:A");
  gate.invalidate();
  const secondAssignment = gate.begin("work:B");
  assert.equal(firstAssignment.signal.aborted, true);
  assert.equal(gate.isCurrent(firstAssignment, "capture:A"), false);
  assert.equal(gate.isCurrent(secondAssignment, "work:B"), true);
});
