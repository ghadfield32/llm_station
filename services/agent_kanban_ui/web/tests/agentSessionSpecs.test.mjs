import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/agentSessionSpecs.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText;
const module = { exports: {} };
new Function("exports", "module", compiled)(module.exports, module);
const { agentSessionSpecOptionLabel, parseAgentSessionSpecs } = module.exports;

test("spec list parsing keeps only the redacted display contract", () => {
  const parsed = parseAgentSessionSpecs([
    {
      name: "codex-analysis",
      harness: "codex_agent",
      capability_profile: "generalist",
      effort: "high",
      mode: "analysis",
      instructions_source: "inline",
      policy_refs: ["session-os-approval"],
      instructions: "MUST_NOT_RENDER",
    },
    {
      name: "malformed",
      error: { code: "invalid_agent_session_spec", message: "invalid" },
    },
    { name: "incomplete" },
  ]);

  assert.deepEqual(parsed, [{
    name: "codex-analysis",
    harness: "codex_agent",
    capability_profile: "generalist",
    effort: "high",
    mode: "analysis",
    instructions_source: "inline",
    policy_refs: ["session-os-approval"],
  }]);
  assert.doesNotMatch(JSON.stringify(parsed), /MUST_NOT_RENDER|instructions:/);
  assert.equal(
    agentSessionSpecOptionLabel(parsed[0]),
    "codex-analysis — codex_agent · generalist",
  );
});

test("missing, invalid, and error-only payloads degrade to an empty list", () => {
  assert.deepEqual(parseAgentSessionSpecs(undefined), []);
  assert.deepEqual(parseAgentSessionSpecs({ detail: "not found" }), []);
  assert.deepEqual(parseAgentSessionSpecs([
    { name: "bad", error: { code: "invalid_agent_session_spec" } },
  ]), []);
});
