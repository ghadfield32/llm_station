# Agentic Process Improvements — 2026-06-20

This note records how the four reviewed ideas enter the Command Center without
changing authority boundaries.

## Headroom Compression Pilot

Decision: pilot, not default.

The experiment contract is `EXP-headroom-context-compression-001` in
`configs/improvement.yaml`. It measures judge accuracy, input-token reduction,
original-snippet retrieval, and secret exclusion before any proxy or wrapper can
become part of the normal path.

The contract is deliberately `automated: false`: it may be registered as a
Proposed experiment, but the runner refuses to execute it until a real
measurement harness and evidence source are declared.

Adoption gates:

1. Build a small labeled log/tool-output case set.
2. Run raw-context and compressed-context judge comparisons.
3. Preserve raw inputs, compressed inputs, retrieval attempts, and metric
   summaries as verifier evidence.
4. Promote only through the improvement lifecycle and human canary approval.

Do not enable a global Headroom wrapper, `headroom learn`, or shared proxy mode
until the pilot proves the cache, retrieval, and log-retention risks are bounded.

## Airflow Failure RCA

Decision: adopt the workflow pattern behind proactive gates.

`configs/proactive.yaml` now includes `airflow-failure-rca-intake`. The runner
collects only real evidence. The Airflow adapter in
`services/proactive_runner/collectors.py` stays dormant unless
`PROACTIVE_AIRFLOW_EVIDENCE_DIR` points at redacted JSON snapshots containing:

- `dag_runs.json`
- `task_logs.json`
- `changed_files.json`
- `output_partitions.json`
- `deterministic_checks.json`

Each snapshot must be a JSON object with:

```json
{
  "schema_version": "command-center.airflow-evidence.v1",
  "redaction_status": "redacted",
  "data": {}
}
```

Missing snapshot files, unredacted snapshots, wrong schema versions, and
secret-bearing field names fail loudly; they are not converted into partial
judge evidence.

The strongest autonomous action remains `open_rca_mission`; patches still flow
through the normal lease, static checks, judge array, and human approval wall.

The matching improvement experiment is also `automated: false`. It documents
the proposed measurement plan without allowing runner execution from synthetic
or missing Airflow evidence.

## ARD-Style Metadata

Decision: extract the catalog pattern.

`configs/capabilities.yaml` adds ARD-style metadata for internal tools, skills,
workflows, and model candidates: owner, type, representative queries, risk tier,
updated date, trust metadata, and provenance. This improves routing/discovery
without granting new execution authority.

## Gemma 4 12B

Decision: model candidate only.

Gemma 4 12B is tracked as
`urn:air:command-center.local:model-candidate:gemma-4-12b` in the capability
catalog. It is not added to `configs/models.yaml` and is not promoted.

Required path:

1. Resolve exact local Ollama tag, license, source model URL, model-card hash,
   local digest, parameter size, quantization, and context length.
2. Add a curated record only after the identity join can pass
   `configs/model-scout-curated-openweight.yaml`.
3. Run `make model-scout`, then `make model-fit MODEL=<tag>`.
4. If fit and eval evidence justify it, use
   `make models-canary ROLE=<role> MODEL=ollama_chat/<tag>`.
5. Run `make evals`.
6. Promote manually only after clean canary telemetry.
