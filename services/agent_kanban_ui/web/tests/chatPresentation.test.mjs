import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/chatPresentation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText;
const module = { exports: {} };
new Function("exports", "module", compiled)(module.exports, module);
const { describeChatEvent, optionLabel, runtimeLabel } = module.exports;

test("unknown chat events stay collapsed and never expose a JSON dump", () => {
  const event = {
    type: "future_runtime_signal",
    secret: { token: "must-not-render" },
  };
  const described = describeChatEvent(event);

  assert.equal(described.kind, "activity");
  assert.equal(described.role, "system");
  assert.equal(described.text, "activity: future_runtime_signal");
  assert.notEqual(described.collapsedDetail, JSON.stringify(event));
  assert.doesNotMatch(described.collapsedDetail, /must-not-render|secret/);
});

test("runtime labels distinguish GatewayCore and both native agent kinds", () => {
  assert.deepEqual(runtimeLabel("GatewayCore"), {
    id: "GatewayCore", label: "GatewayCore", kind: "gateway",
  });
  assert.deepEqual(runtimeLabel({
    harness_id: "claude_code_local", label: "Claude Code",
  }), {
    id: "claude_code_local", label: "Claude Code", kind: "claude",
  });
  assert.deepEqual(runtimeLabel({
    harness_id: "codex_agent", label: "Codex Agent",
  }), {
    id: "codex_agent", label: "Codex Agent", kind: "codex",
  });
});

test("model options keep a short label and preserve full detail in the title", () => {
  const full = "anthropic/claude-sonnet-4.5 — ~$0.0123/turn · 3.4s median · 87% suite pass";
  assert.deepEqual(optionLabel(full), {
    label: "anthropic/claude-sonnet-4.5",
    title: full,
  });
});
