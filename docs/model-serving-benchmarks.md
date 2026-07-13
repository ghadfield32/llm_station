# Serving-performance benchmarks (quality_eval != serving_eval)

A model can win every quality suite and still be the wrong choice if it is too slow for the
Command Center workflow. So model selection has **two** gates: the role **quality** suites
(`configs/model-benchmarks.yaml`) and this **serving** evaluation. Raw `tokens/sec` is never a
promotion metric by itself — it conflates workloads (1,000 tokens of RAG extraction ≠ 1,000
tokens of code generation) and ignores request rate.

## The three latency numbers (not one)

| Metric | Meaning | From Ollama `/api/generate` (ns) |
|---|---|---|
| **TTFT** | time to first token | `load_duration + prompt_eval_duration` |
| **ITL** | inter-token latency | `eval_duration / eval_count` |
| **TTLT** | time to last token (total wait) | `total_duration` |

`src/command_center/improvement/serving_benchmark.py` (`parse_ollama_timings`) derives all
three from Ollama's own timing fields and fails loud on a missing field or a zero-token
response — never a fabricated duration. (NVIDIA's AIPerf tracks the same family: request
latency, TTFT, ITL, request/token throughput, token-length distributions.)

## Scenario workloads + SLOs

`configs/model-serving-benchmarks.yaml` declares realistic workloads, each with input/output
token sizes and a p90 latency SLO: `repo_triage` (short, latency-sensitive), `code_patch`
(moderate in, larger out), `long_repo_reader` (long-context, prompt-processing dominated).

## The operating point (the chart that matters)

Minimum latency (one request at a time) is not the operating point — GPUs are throughput
devices, so single-request throughput is 10–20× below peak. The real question: **the highest
request rate where p90 latency still meets the SLO.** `serving_slo.py` is the pure, unit-tested
analysis:

- `percentile` → p50/p90/p95/p99 (fails on an empty sample set);
- `predict_p90_ttlt` → the **three-nineties rule**: `p90 TTLT ≈ p90 TTFT + p90 ITL × output_tokens`
  (predict the tail without production traffic);
- `operating_point` → sweeps the `concurrency_sweep` points and returns the highest-RPS point
  meeting both SLOs (and not erroring out), or an explicit `found: false` with the reason.

## Required serving evidence for a promotion

`time to first token · inter-token latency · time to last token · requests/sec ·
p50/p90/p95/p99 · input/output token distribution · VRAM/RAM used · failure/saturation point`.
The selected model is the one that **passes its role quality gate** *and* has the **best
operating point under the workload SLO**.

## Load driver (implemented)

`serving_load_driver.py` is the concurrency-sweep executor on top of `measure_once`:
`run_point` issues `concurrency` requests at once (thread pool) and counts failures;
`point_to_sweep` turns the batch into a `SweepPoint` (p90 TTFT/TTLT + sustained
`rps = completed / batch_wall` + `error_rate`); `sweep_and_operating_point` runs the full
`concurrency_sweep` and returns the operating point. The per-request `measure_fn` and the wall
clock are **injectable**, so the sweep + analysis are unit-tested deterministically with no live
Ollama. For a real run, `build_measure_fn(model, input_tokens, output_tokens, base_url)` binds a
synthetic-prompt request sized to a scenario. Privacy posture matches the quality harness: only
timing/metric numbers are produced — never raw prompts or generated text. An all-failed point
reports `rps=0 / error_rate=1` with the observed wall as its latency, never a fabricated number.

## Serving engines (runtime experiments, not quality signals)

vLLM / SGLang / TensorRT-LLM do **not** tell you whether a model is *smarter* — they tell you
whether a given **model + quant + runtime** is usable under your workload. Treat `runtime` as an
axis (`ollama | llama.cpp | vllm | sglang`):

- **Ollama** stays the default ergonomic local runner.
- **vLLM** is the first throughput/concurrency experiment (OpenAI-compatible endpoint → plugs
  into the existing evaluator clients). Prove the serving benchmark against Ollama first, then
  one vLLM-served model.
- **SGLang** later for agent/tool workloads; **TensorRT-LLM** last (higher setup/tuning cost).

Do not overengineer this — it is a measured experiment behind the same human-gated promotion
wall, not a new default.
