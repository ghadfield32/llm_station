import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/researchAnalysis.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText;
const module = { exports: {} };
new Function("exports", "module", compiled)(module.exports, module);
const { researchAnalysisComplete, researchDetailBadge } = module.exports;

const projects = ["betts_basketball", "llm_station"];
const fits = [
  {
    project: "betts_basketball", fit_score: 64,
    item_evidence: "The paper evaluates forecast calibration.",
    project_capability: "Bayesian sports models and evaluation",
    why: "Could support model evaluation.",
    suggested_application: "Run one offline benchmark.",
  },
  {
    project: "llm_station", fit_score: 91,
    item_evidence: "The paper evaluates tool-using agent traces.",
    project_capability: "LLM and agent model routing and evaluation",
    why: "Directly supports governed agent evaluation.",
    suggested_application: "Add one trace fixture.",
  },
];
const summary = [
  "- llm_station · 91/100 — Item evidence: The paper evaluates tool-using "
    + "agent traces. Project capability: LLM and agent model routing and evaluation. "
    + "Why: Directly supports governed agent evaluation. "
    + "Suggested application: Add one trace fixture.",
  "- betts_basketball · 64/100 — Item evidence: The paper evaluates forecast "
    + "calibration. Project capability: Bayesian sports models and evaluation. "
    + "Why: Could support model evaluation. "
    + "Suggested application: Run one offline benchmark.",
].join("\n");
const valid = {
  analysis_schema_version: "growthos.research-analysis.v5",
  analysis_status: "complete",
  analysis_model: "resolved-local-model",
  analysis_generated_at: "2026-07-16T12:00:00+00:00",
  analysis_input_sha256: "a".repeat(64),
  analysis_origin: "local_model",
  analysis_error_code: "",
  useful_for_us: "Useful",
  pros: ["Pro"], cons: ["Con"], key_details: ["Detail"],
  implementation_notes: ["Try it"], work_areas: ["Evaluation"],
  use_cases: ["Trace testing"], research_priority: "high",
  relevance_score: 91, potential_impact_score: 82,
  implementation_readiness_score: 75, evidence_confidence_score: 78,
  estimated_effort: "small", project_fits: fits,
  applicable_projects: ["llm_station", "betts_basketball"],
  best_project: "llm_station", best_project_fit_score: 91,
  project_fit_summary: summary,
};

test("the UI accepts the same strict complete contract as the backfill gate", () => {
  assert.equal(researchAnalysisComplete(valid, projects), true);
  assert.deepEqual(researchDetailBadge(valid, projects), {
    label: "Details complete", tone: "good",
  });
});

for (const [name, patch] of [
  ["missing registered project", { project_fits: fits.slice(1) }],
  ["numeric string", { relevance_score: "90" }],
  ["float score", { potential_impact_score: 82.5 }],
  ["negative project fit", {
    project_fits: [fits[0], { ...fits[1], fit_score: -1 }],
  }],
  ["project fit above 100", {
    project_fits: [fits[0], { ...fits[1], fit_score: 101 }],
  }],
  ["too many pros", { pros: Array(9).fill("Repeated pro") }],
  ["overlong list item", { cons: ["x".repeat(1201)] }],
  ["overlong usefulness", { useful_for_us: "x".repeat(1201) }],
  ["overlong fit reason", {
    project_fits: [fits[0], { ...fits[1], why: "x".repeat(601) }],
  }],
  ["blank fit explanation", {
    project_fits: [{ ...fits[0], why: "" }, fits[1]],
  }],
  ["blank item evidence", {
    project_fits: [{ ...fits[0], item_evidence: "" }, fits[1]],
  }],
  ["blank project capability", {
    project_fits: [{ ...fits[0], project_capability: "" }, fits[1]],
  }],
  ["inflated no-direct-match score", {
    project_fits: [
      { ...fits[0], project_capability: "no direct match", fit_score: 25 },
      fits[1],
    ],
  }],
  ["extra fit field", {
    project_fits: [{ ...fits[0], invented: true }, fits[1]],
  }],
  ["stale error", { analysis_error_code: "old_failure" }],
  ["non-string error", { analysis_error_code: { stale: true } }],
  ["invalid calendar date", {
    analysis_generated_at: "2026-02-30T12:00:00+00:00",
  }],
  ["invalid priority", { research_priority: "urgent" }],
  ["priority inconsistent with scores", {
    research_priority: "high", relevance_score: 10,
    potential_impact_score: 40, implementation_readiness_score: 20,
    evidence_confidence_score: 60,
  }],
  ["incorrect derived best", { best_project: "betts_basketball" }],
]) {
  test(`incomplete: ${name}`, () => {
    assert.equal(researchAnalysisComplete({ ...valid, ...patch }, projects), false);
  });
}

test("failed and unavailable states stay truthful", () => {
  assert.deepEqual(
    researchDetailBadge({ ...valid, analysis_status: "failed" }, projects),
    { label: "Analysis failed", tone: "bad" },
  );
  assert.deepEqual(
    researchDetailBadge({ ...valid, analysis_status: "unavailable" }, projects),
    { label: "Analysis unavailable", tone: "bad" },
  );
});

test("an empty applicable-project set must still be explicitly stored", () => {
  const lowFits = [
    { ...fits[0], fit_score: 10 },
    { ...fits[1], fit_score: 20 },
  ];
  const lowSummary = [
    "- llm_station · 20/100 — Item evidence: The paper evaluates tool-using "
      + "agent traces. Project capability: LLM and agent model routing and evaluation. "
      + "Why: Directly supports governed agent evaluation. "
      + "Suggested application: Add one trace fixture.",
    "- betts_basketball · 10/100 — Item evidence: The paper evaluates forecast "
      + "calibration. Project capability: Bayesian sports models and evaluation. "
      + "Why: Could support model evaluation. "
      + "Suggested application: Run one offline benchmark.",
  ].join("\n");
  const low = {
    ...valid,
    relevance_score: 20,
    research_priority: "low",
    project_fits: lowFits,
    best_project: "llm_station",
    best_project_fit_score: 20,
    applicable_projects: [],
    project_fit_summary: lowSummary,
  };
  assert.equal(researchAnalysisComplete(low, projects), true);
  const { applicable_projects: _missing, ...withoutApplicable } = low;
  assert.equal(researchAnalysisComplete(withoutApplicable, projects), false);
  assert.equal(researchAnalysisComplete({
    ...low, applicable_projects: "none",
  }, projects), false);
  assert.equal(researchAnalysisComplete({
    ...low, applicable_projects: [""],
  }, projects), false);
});
