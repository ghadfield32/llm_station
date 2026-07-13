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


def _valid_output(claim_ids: list[str], *, with_master_sections: bool = False,
                  resume_extra: str = "", cover_extra: str = "",
                  contact_line: str = "") -> str:
    resume = [
        "# GEOFFREY HADFIELD",
        *( [contact_line] if contact_line else [] ),
        "DATA SCIENTIST | EXPERIMENTATION | ML DELIVERY",
        "## Professional Summary",
        "Applied ML data scientist.",
        "## Experience",
        "World Model Sports LLC | Founder (2026 - Present)",
        "- Built Hoops World Model decision-support workflows",
        "JPMorgan Chase | Analytics Engineer, Associate (Jun 2023 - Aug 2025)",
        "- Built an A/B testing framework (Statsmodels + GitHub Actions); "
        "standardized experiment guardrails",
        "Driveline Baseball | Sports Science Intern (Feb 2025 - Mar 2025)",
        "- Built time-series fatigue workflows on biomechanical signals",
    ]
    if with_master_sections:
        resume.extend([
            "## Core Expertise",
            "Modeling: PyMC | Engineering: Python, SQL",
            "## Selected Technical Projects",
            "- NBA Player Value Forecasting System",
            "## Education",
            "M.S. Data Science — University of West Florida",
        ])
    if resume_extra:
        resume.append(resume_extra)
    # 250-ish words: the writer enforces the 250-350 standard with slack
    cover_body = " ".join(["evidence-backed sentence content"] * 80)
    return "\n".join([
        "=== RESUME ===",
        *resume,
        "=== COVER LETTER ===",
        f"Dear Acme hiring team, {cover_body}{cover_extra}",
        "=== OUTREACH ===",
        "## Recruiter Direct Message",
        "Hi — interested in the Senior Data Scientist role.",
        "=== ANSWERS ===",
        "## Why are you interested in this role?",
        "Situation: ... Decision: ... Action: ... Result: ... Learning: ...",
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
    assert "GEOFFREY HADFIELD" in out.resume
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
            config=CFG, post_fn=post, max_attempts=2)
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


def test_malformed_gateway_response_is_traced_then_raised(tmp_path):
    """A 200 with a bodiless payload must follow the same AgentWriterError +
    trace contract as a transport failure — not escape as a bare KeyError."""
    def empty_choices(config, messages):
        return {"choices": []}
    with pytest.raises(AgentWriterError, match="malformed completion payload"):
        generate_materials(
            _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
            config=CFG, post_fn=empty_choices)
    trace = read_trace(tmp_path)
    assert trace[0]["ok"] is False
    assert "malformed gateway response" in trace[0]["error"]


def test_malformed_claim_tokens_are_flagged_not_dropped(tmp_path):
    """A hallucinated 'JPMC-AB-Testing' style id must FAIL claim validation and
    trigger the corrective retry — silently discarding it would let unvalidated
    claims through."""
    post, calls = _fake_post([
        _valid_output(["JPMC-AB-Testing"]),
        _valid_output(["jpmc_ab_testing_framework"]),
    ])
    out = generate_materials(
        _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
        config=CFG, post_fn=post)
    assert out.attempts == 2
    first = read_trace(tmp_path)[0]
    assert any("JPMC-AB-Testing" in p for p in first["problems"])


def test_non_numeric_timeout_env_is_a_writer_error():
    with pytest.raises(AgentWriterError, match="JOB_SEARCH_WRITER_TIMEOUT"):
        WriterConfig.from_env({"JOB_SEARCH_WRITER_TIMEOUT": "5m"})


MASTER_BANK = "\n".join([
    "PROFESSIONAL SUMMARIES",
    "Applied ML Data Scientist",
    "Applied data scientist blending machine learning and production delivery.",
    "EXPERIENCE BULLETS",
    "JP Morgan Chase — Analytics Engineer, Associate (Jun 2023 - Aug 2025)",
    "Built an A/B testing framework; ~12% engagement lift [Applied ML]",
    "CORE SKILLS SECTIONS",
    "Applied ML Data Scientist Skills",
    "Modeling: PyMC | Engineering: Python, SQL",
    "EDUCATION",
    "M.S. Data Science — University of West Florida",
])


def test_master_bank_lands_in_prompt_with_format_contract():
    messages = build_messages(_inputs(master_bank=MASTER_BANK), BANK)
    system, user = messages[0]["content"], messages[1]["content"]
    assert "MASTER RESUME BANK" in user
    assert "M.S. Data Science" in user
    # the format contract demands Geoff's real structure and voice
    assert "## Core Expertise" in system
    assert "## Education" in system
    assert "## Selected Technical Projects" in system
    assert "3-4 bullets" in system
    assert "spearheaded" in system   # banned-phrase list is spelled out
    assert "near-verbatim" in system
    # employer-facing hygiene is an explicit prompt rule
    assert "Do NOT include: a 'Target:' line" in system


def test_contact_and_held_claims_and_exemplar_land_in_prompt():
    contact = {"location": "Sanford, FL", "phone": "253-245-7959",
               "email": "ghadfield32@gmail.com",
               "portfolio": "portfolio.ghadfield.com"}
    held = [{"id": "uptime_10k_predictions",
             "claim": "99.9% uptime serving 10K+ daily predictions",
             "reason": "appears in only one source variant",
             "detect": ["99.9%"]}]
    messages = build_messages(
        _inputs(contact=contact, held_claims=held,
                format_example="GEOFFREY HADFIELD\nEXEMPLAR BODY"), BANK)
    system, user = messages[0]["content"], messages[1]["content"]
    assert "Sanford, FL | 253-245-7959 | ghadfield32@gmail.com" in system
    assert "HELD CLAIMS" in user
    assert "99.9% uptime serving 10K+ daily predictions" in user
    assert "APPROVED RESUME EXEMPLAR" in user
    assert "EXEMPLAR BODY" in user


def test_master_bank_resume_missing_education_gets_retry(tmp_path):
    post, _ = _fake_post([
        _valid_output(["wms_founder_platform"]),                        # no Education
        _valid_output(["wms_founder_platform"], with_master_sections=True),
    ])
    out = generate_materials(
        _inputs(master_bank=MASTER_BANK), BANK,
        trace_path=tmp_path / "agent_trace.jsonl", config=CFG, post_fn=post)
    assert out.attempts == 2
    first = read_trace(tmp_path)[0]
    assert any("## Education" in p for p in first["problems"])
    assert "M.S. Data Science" in out.resume


def test_surviving_tone_flags_are_kept_not_template_fallback(tmp_path):
    stubborn = _valid_output(
        ["wms_founder_platform"], cover_extra=" I am thrilled to leverage this!")
    post, _ = _fake_post([stubborn, stubborn])
    out = generate_materials(
        _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
        config=CFG, post_fn=post, max_attempts=2)
    # retried once for tone, then ACCEPTED with the flags surfaced — a word
    # choice never forces the deterministic-template fallback
    assert out.attempts == 2
    assert any("thrilled" in f for f in out.tone_flags)
    assert any("exclamation" in f for f in out.tone_flags)
    trace = read_trace(tmp_path)
    assert [t["ok"] for t in trace] == [True, True]   # tone flags are soft
    assert all(t["problems"] for t in trace)          # but never hidden


def test_held_claim_leak_gets_corrective_retry(tmp_path):
    held = [{"id": "uptime_10k_predictions",
             "claim": "99.9% uptime serving 10K+ daily predictions",
             "reason": "single source variant",
             "detect": ["99.9%", "10k+ daily"]}]
    post, calls = _fake_post([
        _valid_output(["wms_founder_platform"],
                      cover_extra=" Maintained 99.9% uptime."),
        _valid_output(["wms_founder_platform"]),
    ])
    out = generate_materials(
        _inputs(held_claims=held), BANK,
        trace_path=tmp_path / "agent_trace.jsonl", config=CFG, post_fn=post)
    assert out.attempts == 2
    first = read_trace(tmp_path)[0]
    assert any("held claim leaked" in p for p in first["problems"])
    assert "never using a held claim" in calls[1][-1]["content"]
    assert "99.9%" not in out.cover_letter


def test_missing_contact_header_gets_corrective_retry(tmp_path):
    contact = {"email": "ghadfield32@gmail.com", "phone": "253-245-7959"}
    line = "Sanford, FL | 253-245-7959 | ghadfield32@gmail.com"
    post, _ = _fake_post([
        _valid_output(["wms_founder_platform"]),                  # no contact
        _valid_output(["wms_founder_platform"], contact_line=line),
    ])
    out = generate_materials(
        _inputs(contact=contact), BANK,
        trace_path=tmp_path / "agent_trace.jsonl", config=CFG, post_fn=post)
    assert out.attempts == 2
    first = read_trace(tmp_path)[0]
    assert any("contact header" in p for p in first["problems"])
    assert "ghadfield32@gmail.com" in out.resume


def test_internal_content_in_resume_gets_corrective_retry(tmp_path):
    post, _ = _fake_post([
        _valid_output(["wms_founder_platform"],
                      resume_extra="Target: Acme — Senior DS"),
        _valid_output(["wms_founder_platform"]),
    ])
    out = generate_materials(
        _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
        config=CFG, post_fn=post)
    assert out.attempts == 2
    first = read_trace(tmp_path)[0]
    assert any("internal-only content" in p for p in first["problems"])
    assert "Target:" not in out.resume


def test_dropped_employer_and_short_cover_get_retry(tmp_path):
    good = _valid_output(["wms_founder_platform"])
    bad = good.replace("Driveline Baseball | Sports Science Intern", "Elsewhere")
    bad = bad.replace(" ".join(["evidence-backed sentence content"] * 80),
                      "short cover")
    post, _ = _fake_post([bad, good])
    out = generate_materials(
        _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
        config=CFG, post_fn=post)
    assert out.attempts == 2
    problems = read_trace(tmp_path)[0]["problems"]
    assert any("Driveline Baseball" in p and "dropped" in p for p in problems)
    assert any("cover letter is" in p and "250-350" in p for p in problems)
    assert "Driveline Baseball" in out.resume


def test_outreach_and_answers_are_returned(tmp_path):
    post, _ = _fake_post([_valid_output(["wms_founder_platform"])])
    out = generate_materials(
        _inputs(), BANK, trace_path=tmp_path / "agent_trace.jsonl",
        config=CFG, post_fn=post)
    assert "Recruiter Direct Message" in out.recruiter_message
    assert "Situation:" in out.answers


def test_resume_ats_text_strips_markdown():
    from command_center.job_search.agent_writer import resume_ats_text
    md = "\n".join([
        "# GEOFFREY HADFIELD",
        "Sanford, FL | ghadfield32@gmail.com",
        "## Professional Summary",
        "Data scientist with **production** `ML` work.",
        "## Experience",
        "- Built a thing; measured a result",
    ])
    text = resume_ats_text(md)
    assert "GEOFFREY HADFIELD" in text
    assert "PROFESSIONAL SUMMARY" in text
    assert "• Built a thing; measured a result" in text
    assert "#" not in text and "**" not in text and "`" not in text


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
