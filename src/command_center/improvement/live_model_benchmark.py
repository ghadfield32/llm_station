"""Live local-model A/B benchmark harness.

This harness is intentionally local-only and evidence-bounded. It calls Ollama
directly, scores configured role-specific benchmark cases, and records only
hashes/booleans/metrics in runner artifacts. It never logs raw prompts or model
outputs.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from .registry import canonical_hash, file_sha256
from .runner import HARNESSES, Harness, MeasureResult, _git_commit
from .schema import ExperimentDefinition, ModelBenchmarksConfig

TARGET_REF = "command_center.improvement.live_model_benchmark"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _required(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"model_benchmark.{key} is required")
    return value


def _optional_positive_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or value < 1:
        raise RuntimeError(f"model_benchmark.{key} must be a positive integer")
    return value


class LiveModelBenchmarkHarness(Harness):
    """Measure two declared local Ollama models on a configured role suite."""

    def __init__(self, repo_root: str | Path, defn: ExperimentDefinition):
        self.repo_root = Path(repo_root)
        params = defn.parameters.get("model_benchmark")
        if not isinstance(params, dict):
            raise RuntimeError("experiment.parameters.model_benchmark is required")
        self.role = _required(params, "role")
        self.suite_key = _required(params, "suite")
        self.baseline_model = _required(params, "baseline_model")
        self.candidate_model = _required(params, "candidate_model")
        self.config_path = self.repo_root / _required(params, "suite_path")
        self.base_url = self._resolve_base_url(params)
        self.context_length = _optional_positive_int(params, "context_length")

        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        self.config = ModelBenchmarksConfig.model_validate(raw)
        if self.suite_key not in self.config.suites:
            raise RuntimeError(
                f"benchmark suite {self.suite_key!r} not in {self.config_path}")
        self.suite = self.config.suites[self.suite_key]
        if self.suite.role != self.role:
            raise RuntimeError(
                f"benchmark suite {self.suite_key!r} role {self.suite.role!r} "
                f"does not match experiment role {self.role!r}")

    def _resolve_base_url(self, params: dict[str, Any]) -> str:
        direct = params.get("base_url")
        env_name = params.get("base_url_env")
        if isinstance(direct, str) and direct:
            return direct
        if isinstance(env_name, str) and env_name:
            value = os.environ.get(env_name)
            if not value:
                raise RuntimeError(f"environment variable {env_name!r} is required")
            return value
        raise RuntimeError("model_benchmark.base_url or base_url_env is required")

    def equivalence_key(self) -> dict:
        config_hash, _ = file_sha256(self.config_path)
        return {
            "benchmark_config": self.config_path.as_posix(),
            "benchmark_config_hash": config_hash,
            "suite": self.suite_key,
            "suite_hash": canonical_hash(self.suite.model_dump(mode="json")),
            "role": self.role,
            "baseline_model": self.baseline_model,
            "candidate_model": self.candidate_model,
            "evaluated_context": self.context_length,
            "base_url_sha256": _sha(self.base_url),
            "commit": _git_commit(self.repo_root),
        }

    def measure(self, role: str, reps: int) -> MeasureResult:
        model = self.baseline_model if role == "baseline" else self.candidate_model
        if reps < 1:
            raise RuntimeError("live model benchmark reps must be >= 1")
        success_samples: list[float] = []
        unsafe_samples: list[float] = []
        invalid_samples: list[float] = []
        latency_samples: list[float] = []
        tps_samples: list[float] = []
        tag_samples: dict[str, list[float]] = {
            tag: [] for tag in (
                self.suite.metric_policy.primary
                + self.suite.metric_policy.hard_non_regression
                + self.suite.metric_policy.supporting
            )
        }
        failures: list[str] = []
        lines = [
            f"# role={role} benchmark_role={self.role} suite={self.suite_key} "
            f"model_sha256={_sha(model)} reps={reps}"
        ]

        for case in self.suite.cases:
            for rep in range(reps):
                started = time.perf_counter()
                generated = self._generate(
                    model,
                    case.prompt,
                    response_format=case.response_format,
                )
                latency_ms = (time.perf_counter() - started) * 1000.0
                text = generated["response"]
                lower = text.lower()
                expected_ok = all(term.lower() in lower for term in case.expected_contains)
                json_valid = True
                json_values_ok = True
                if case.required_json_keys or case.expected_json_values:
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        parsed = None
                    if not isinstance(parsed, dict):
                        json_valid = False
                        json_values_ok = False
                    else:
                        missing_keys = [
                            key for key in case.required_json_keys if key not in parsed
                        ]
                        json_valid = not missing_keys
                        json_values_ok = all(
                            parsed.get(key) == value
                            for key, value in case.expected_json_values.items()
                        )
                forbidden_hits = [
                    term for term in case.forbidden_contains if term.lower() in lower
                ]
                invalid = not bool(text.strip()) or not json_valid
                unsafe = bool(forbidden_hits) if case.safety else False
                success = expected_ok and json_values_ok and not forbidden_hits and not invalid

                success_samples.append(1.0 if success else 0.0)
                unsafe_samples.append(1.0 if unsafe else 0.0)
                invalid_samples.append(1.0 if invalid else 0.0)
                latency_samples.append(latency_ms)
                for tag in case.metric_tags:
                    tag_samples[tag].append(1.0 if success else 0.0)
                if unsafe:
                    failures.append(f"{case.id}: forbidden marker present")
                if invalid:
                    failures.append(f"{case.id}: invalid structured response")
                eval_count = generated.get("eval_count")
                eval_duration = generated.get("eval_duration")
                if isinstance(eval_count, int) and isinstance(eval_duration, int) and eval_duration > 0:
                    tps_samples.append(eval_count / (eval_duration / 1_000_000_000))
                lines.append(
                    " ".join([
                        f"case={case.id}",
                        f"rep={rep + 1}",
                        f"prompt_sha256={_sha(case.prompt)}",
                        f"output_sha256={_sha(text)}",
                        f"expected_ok={expected_ok}",
                        f"json_valid={json_valid}",
                        f"json_values_ok={json_values_ok}",
                        f"forbidden_hits={len(forbidden_hits)}",
                        f"invalid={invalid}",
                        f"latency_ms={latency_ms:.3f}",
                        f"eval_count={eval_count if eval_count is not None else 'unknown'}",
                    ])
                )

        metrics = {
            "task_success_rate": statistics.mean(success_samples) if success_samples else 0.0,
            "unsafe_output_rate": statistics.mean(unsafe_samples) if unsafe_samples else 0.0,
            "invalid_response_rate": statistics.mean(invalid_samples) if invalid_samples else 0.0,
            "median_latency_ms": statistics.median(latency_samples) if latency_samples else 0.0,
        }
        samples = {
            "task_success_rate": success_samples,
            "unsafe_output_rate": unsafe_samples,
            "invalid_response_rate": invalid_samples,
            "median_latency_ms": latency_samples,
        }
        if tps_samples:
            metrics["tokens_per_second"] = statistics.mean(tps_samples)
            samples["tokens_per_second"] = tps_samples
        for tag, values in tag_samples.items():
            if values:
                metrics[tag] = statistics.mean(values)
                samples[tag] = values
        lines.append("# metrics=" + json.dumps(metrics, sort_keys=True))
        return MeasureResult(
            metric_values=metrics,
            raw_log="\n".join(lines),
            sample_count=len(success_samples),
            failures=failures,
            samples=samples,
        )

    def _generate(self, model: str, prompt: str, *,
                  response_format: str | None = None) -> dict[str, Any]:
        defaults = self.config.defaults
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": defaults.temperature,
                "num_predict": defaults.num_predict,
            },
        }
        if self.context_length is not None:
            payload["options"]["num_ctx"] = self.context_length
        if response_format == "json":
            payload["format"] = "json"
        try:
            with httpx.Client(base_url=self.base_url, timeout=defaults.timeout_seconds) as client:
                response = client.post("/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama generate failed for model {model!r}: {exc}") from exc
        text = data.get("response")
        if not isinstance(text, str):
            raise RuntimeError(f"Ollama generate response for model {model!r} has no text response")
        return data


def build_live_model_benchmark(repo_root: str | Path,
                               defn: ExperimentDefinition) -> LiveModelBenchmarkHarness:
    return LiveModelBenchmarkHarness(repo_root, defn)


HARNESSES[TARGET_REF] = build_live_model_benchmark
