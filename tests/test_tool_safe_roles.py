"""The tool-call-format guard in check_cross_refs: a tool-using role (a chat
channel's role, or `planner` which Hermes tool-calls through) must not be backed
by qwen3-coder, whose Ollama native parser drops prose-prefixed tool calls and
leaks raw `<function=..>` XML to the user (MASTER.md §14, 2026-06-13). qwen3-coder
in a NON-tool role (coder/judges = plain completion) is fine and must NOT trip.
"""
from command_center.cli.check_cross_refs import check_tool_safe_roles


def _models(**roles):
    """roles kw: role -> list of model strings."""
    return {"roles": {r: [{"model": m} for m in models]
                      for r, models in roles.items()}}


def _channels(*role_names):
    return {"channels": [{"name": f"c{i}", "model": r}
                         for i, r in enumerate(role_names)]}


def test_all_tool_roles_robust_passes():
    models = _models(chat=["qwen3:30b"], planner=["qwen3:30b", "devstral:24b"],
                     coder=["qwen3-coder:30b"])          # coder is non-tool
    assert check_tool_safe_roles(models, _channels("chat")) == []


def test_channel_role_on_qwen3_coder_is_flagged():
    models = _models(triage=["qwen3-coder:30b"], chat=["qwen3:30b"])
    problems = check_tool_safe_roles(models, _channels("triage"))
    assert len(problems) == 1
    assert "triage" in problems[0]
    assert "qwen3-coder:30b" in problems[0]


def test_planner_on_qwen3_coder_is_flagged_even_without_channels():
    # Hermes tool-calls through planner regardless of chat channels
    models = _models(planner=["qwen3-coder:30b", "qwen3:30b"])
    problems = check_tool_safe_roles(models, _channels())   # no channels at all
    assert any("planner" in p for p in problems)


def test_qwen3_coder_in_nontool_role_is_not_flagged():
    # coder / architect-judge run plain completion (no tools) — qwen3-coder is
    # correct there and must not be reported.
    models = _models(chat=["qwen3:30b"], planner=["qwen3:30b"],
                     coder=["qwen3-coder:30b"],
                     **{"architect-judge": ["qwen3-coder:30b", "qwen3:30b"]})
    assert check_tool_safe_roles(models, _channels("chat")) == []


def test_matches_any_qwen3_coder_variant():
    # the whole qwen3-coder family uses the native parser, so a future tag is
    # caught too (prefix match, not an exact pin)
    models = _models(chat=["qwen3-coder:7b"])
    assert check_tool_safe_roles(models, _channels("chat")) != []
