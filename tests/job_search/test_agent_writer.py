"""The agent writer: full-bank prompts, section parsing, claim validation with
corrective retry, and the persisted trace (prompts + raw outputs on disk)."""
from __future__ import annotations

import json

import pytest

from command_center.job_search.achievement_bank import default_bank
from command_center.job_search.agent_writer import (
    AgentWriterError,
    MaterialInputs,
    WriterConfig,
    build_messages,
    generate_materials,
    read_trace,
)

BANK = default_bank()
ALL_IDS = [a.id for a in BANK.achievements]


def _inputs(**overrides) -> MaterialInputs:
    base = dict(
        company="Acme Analytics",
        role_title="Senior Data Scientist",
        description_text="Own experimentation and ML delivery for the product org.",
        apply_url="https://example.com/apply",
        resume_variant="applied_ml_data_scientist",
        matched_keywords=["python", "experimentation"],
        fit_reasons=["strong experimentation background"],
        fit_score=88,
    )
    base.update(overrides)
    return MaterialInputs(**base)


def _valid_output(claim_ids: list[str]) -> str:
    return "\n".join([
        "=== RESUME ===",
        "# Geoffrey Hadfield",
        "Target: Acme Analytics — Senior Data Scientist",
        "## Summary",
        "Applied ML data scientist.",
        "## Claim Traceability",
        *[f"- `{c}`" for c in claim_ids],
        "=== COVER LETTER ===",
        "Dear Acme hiring team, ...",
        "=== RECRUITER MESSAGE ===",
        "Hi — interested in the Senior Data Scientist role.",
        "=== CLAIM IDS ===",
        *claim_ids,
    ])


def _fake_post(responses: list[str]):
    calls: list[list[dict]] = []

    def post(config: WriterConfig, messages: list[dict]) -> dict:
        calls.append(messages)
        return {"choices": [{"message": {"content": responses[len(calls) - 1]}}],
                "usage": {"total_tokens": 1234}}
    return post, calls


CFG = WriterConfig(base_url="http://fake:4000/v1", api_key="k", model="chat")


def test_prompt_carries_the_complete_achievement_bank():
    messages = build_messages(_inputs(reviewer_notes=["lead with the NBA work"]), BANK)
    user = messages[1]["content"]
    for achievement_id in ALL_IDS:
        assert achievement_id in user
    # full STAR stories, not just bullets — the writer sees everything
    assert user.count("full story:") == len(ALL_IDS)
    assert "lead with the NBA work" in user
    assert "REVIEWER NOTES" in user


def test_generate_writes_materials_and_full_trace(tmp_path):
    post, calls = _fake_post([_valid_output(["wms_founder_platform", "jpmc_ab_testing_framework"])])
    out = generate_materials(
        _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
        config=CFG, post_fn=post)
    assert out.claim_ids == ["wms_founder_platform", "jpmc_ab_testing_framework"]
    assert out.attempts == 1
    assert "Geoffrey Hadfield" in out.resume
    assert "hiring team" in out.cover_letter
    trace = read_trace(tmp_path)
    assert len(trace) == 1
    entry = trace[0]
    assert entry["ok"] is True
    # the reviewable context: full prompt messages AND the raw model output
    assert entry["messages"][0]["role"] == "system"
    assert "ACHIEVEMENT BANK" in entry["messages"][1]["content"]
    assert entry["response"].startswith("=== RESUME ===")
    assert entry["claim_ids"] == ["wms_founder_platform", "jpmc_ab_testing_framework"]
    assert entry["usage"] == {"total_tokens": 1234}


def test_invalid_claim_id_gets_one_corrective_retry(tmp_path):
    post, calls = _fake_post([
        _valid_output(["made_up_achievement"]),
        _valid_output(["nba_player_value_platform"]),
    ])
    out = generate_materials(
        _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
        config=CFG, post_fn=post)
    assert out.attempts == 2
    assert out.claim_ids == ["nba_player_value_platform"]
    # the retry message names the exact problem — no silent smoothing
    retry_messages = calls[1]
    assert "unknown achievement id: made_up_achievement" in retry_messages[-1]["content"]
    trace = read_trace(tmp_path)
    assert [t["ok"] for t in trace] == [False, True]
    assert "unknown achievement id: made_up_achievement" in trace[0]["problems"][0]


def test_still_invalid_after_retries_raises(tmp_path):
    post, _ = _fake_post([_valid_output(["nope_1"]), _valid_output(["nope_2"])])
    with pytest.raises(AgentWriterError, match="unknown achievement id"):
        generate_materials(
            _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
            config=CFG, post_fn=post)
    assert len(read_trace(tmp_path)) == 2


def test_missing_section_is_a_problem_not_a_crash(tmp_path):
    partial = "=== RESUME ===\nonly a resume, nothing else"
    post, _ = _fake_post([partial, _valid_output(["wms_founder_platform"])])
    out = generate_materials(
        _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
        config=CFG, post_fn=post)
    assert out.attempts == 2
    first = read_trace(tmp_path)[0]
    assert any("missing or empty section" in p for p in first["problems"])


def test_transport_error_is_traced_then_raised(tmp_path):
    def boom(config, messages):
        raise ConnectionError("litellm unreachable")
    with pytest.raises(AgentWriterError, match="litellm unreachable"):
        generate_materials(
            _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
            config=CFG, post_fn=boom)
    trace = read_trace(tmp_path)
    assert trace[0]["ok"] is False
    assert "litellm unreachable" in trace[0]["error"]
    # even the failed attempt preserves the exact context that was sent
    assert trace[0]["messages"][1]["content"]


def test_trace_file_is_appended_jsonl(tmp_path):
    post, _ = _fake_post([_valid_output(["wms_founder_platform"])] * 2)
    for _ in range(2):
        generate_materials(
            _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
            config=CFG, post_fn=post)
    lines = (tmp_path / "agent_trace.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)
