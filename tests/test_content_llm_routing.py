"""The content routing seam: the ContentLLMClient adapters, the budget + redaction
gates, the dry-run estimator that refuses live paid calls, the policy factory, and
that the SHIPPED routing config stays local-first (paid policies carry budget +
redaction; the default never allows paid). Pins docs/MASTER.md content-routing."""
from __future__ import annotations

import yaml

from command_center.schemas import (
    ContentPipelineConfig, ContentLLMPolicy, ContentModelPrice, ContentLLMRouting,
)
from command_center.content.llm_client import (
    ContentLLMRequest, ContentLLMResponse, TestContentClient, LiteLLMContentClient,
    DryRunRouterClient, estimate_tokens, estimate_cost_usd, redact, within_budget,
    select_policy, make_client,
)
from command_center.content.draft import draft_one
from command_center.content.sources import Candidate


PRICES = [
    ContentModelPrice(model="openrouter/z-ai/glm-5.2",
                      input_usd_per_mtok=1.0, output_usd_per_mtok=4.0),
]


# ── gates ───────────────────────────────────────────────────────────────────
def test_estimate_cost_uses_per_mtok_prices():
    # 1M input @ $1 + 1M output @ $4 = $5
    assert estimate_cost_usd("openrouter/z-ai/glm-5.2", 1_000_000, 1_000_000,
                             PRICES) == 5.0
    # unknown model -> no price -> 0 (estimator, not a guess)
    assert estimate_cost_usd("mystery", 1000, 1000, PRICES) == 0.0


def test_estimate_tokens_is_positive():
    assert estimate_tokens("") == 1
    assert estimate_tokens("x" * 400) == 100


def test_redact_scrubs_secrets_and_reports_kinds():
    text = "mail me ghadfield32@gmail.com, key sk-abcdEFGH1234, urn:li:person:99"
    out, found = redact(text)
    assert "ghadfield32@gmail.com" not in out
    assert "sk-abcdEFGH1234" not in out
    assert "urn:li:person:99" not in out
    assert set(found) >= {"email", "api_key", "urn"}


def test_within_budget():
    assert within_budget(0.04, 0.05) and not within_budget(0.06, 0.05)
    assert within_budget(999, 0.0)            # 0 cap = unbounded (local)


# ── adapters ────────────────────────────────────────────────────────────────
def test_test_client_records_and_returns():
    c = TestContentClient(reply="HOOK: h\nBODY: b?")
    resp = c.complete(ContentLLMRequest(system="s", user="u", model="chat"))
    assert isinstance(resp, ContentLLMResponse)
    assert resp.text == "HOOK: h\nBODY: b?" and c.calls[0].model == "chat"


def test_dry_run_router_estimates_and_never_calls(monkeypatch):
    # if it touched the network this would explode; it must not.
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k:
                        (_ for _ in ()).throw(AssertionError("no egress allowed")))
    policy = ContentLLMPolicy(name="frontier_external",
                              primary="openrouter/z-ai/glm-5.2", allow_paid=True,
                              max_request_usd=0.25, require_redaction=True,
                              human_approval=True)
    client = DryRunRouterClient(policy, PRICES)
    resp = client.complete(ContentLLMRequest(system="s", user="write a post",
                                             model="openrouter/z-ai/glm-5.2"))
    assert resp.dry_run and resp.text == ""
    assert resp.cost_usd > 0
    assert any("DRY RUN" in n for n in resp.notes)
    assert any("human approval" in n for n in resp.notes)


def test_dry_run_flags_over_budget():
    policy = ContentLLMPolicy(name="p", primary="openrouter/z-ai/glm-5.2",
                              allow_paid=True, max_request_usd=0.000001,
                              require_redaction=True)
    resp = DryRunRouterClient(policy, PRICES).complete(
        ContentLLMRequest(system="s" * 4000, user="u" * 4000,
                          model="openrouter/z-ai/glm-5.2", max_tokens=2000))
    assert any("OVER BUDGET" in n for n in resp.notes)


# ── factory ─────────────────────────────────────────────────────────────────
def _routing():
    return ContentLLMRouting(
        default_policy="local_first",
        policies=[
            ContentLLMPolicy(name="local_first", primary="chat"),
            ContentLLMPolicy(name="cheap_external",
                             primary="openrouter/z-ai/glm-4.7-flash",
                             allow_paid=True, max_request_usd=0.05,
                             require_redaction=True),
        ],
        prices=PRICES)


def test_select_policy_default_and_named():
    r = _routing()
    assert select_policy(r).name == "local_first"
    assert select_policy(r, "cheap_external").name == "cheap_external"


def test_make_client_local_is_litellm_paid_is_dryrun():
    r = _routing()
    local = make_client(select_policy(r, "local_first"),
                        base_url="http://x", key="k", prices=r.prices)
    paid = make_client(select_policy(r, "cheap_external"),
                       base_url="http://x", key="k", prices=r.prices)
    assert isinstance(local, LiteLLMContentClient)
    assert isinstance(paid, DryRunRouterClient)     # paid never gets a live client


# ── draft uses the seam ───────────────────────────────────────────────────────
def test_draft_one_uses_injected_client():
    cand = Candidate(key="c1", stream="personal", kind="repo", title="T",
                     summary="S", url="", score=1.0, topics="t", suggested="")
    client = TestContentClient(reply="HOOK: Tight hook.\nBODY: A body. Worth it?")
    draft = draft_one(cand, "voice", "http://x", "k", "chat", client=client)
    assert draft.hook == "Tight hook." and draft.body == "A body. Worth it?"
    assert client.calls and client.calls[0].model == "chat"


# ── the shipped config stays local-first ──────────────────────────────────────
def test_shipped_routing_is_local_first_and_paid_is_gated():
    data = yaml.safe_load(open("configs/content_pipeline.yaml"))
    cfg = ContentPipelineConfig.model_validate(data)
    routing = cfg.content_llm
    default = next(p for p in routing.policies if p.name == routing.default_policy)
    assert not default.allow_paid                    # local-first invariant
    for p in routing.policies:
        if p.allow_paid:
            assert p.max_request_usd > 0 and p.require_redaction   # gated
    # GLM-5.2 is only ever the explicit frontier escalation, never the default
    assert "glm-5.2" not in default.primary
