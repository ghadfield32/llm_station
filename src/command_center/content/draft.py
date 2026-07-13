"""Draft stage: turn each gathered candidate into a breakdown post on the best
local model. Carries the candidate's evidence forward so the judge panel can
verify claims against it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .llm_client import ContentLLMRequest, LiteLLMContentClient
from .templates import TEMPLATES, draft_prompts

_HOOK = re.compile(r"HOOK:\s*(.+?)\s*BODY:\s*(.+)", re.S | re.I)


def parse_post(raw: str) -> tuple[str, str]:
    """Parse the delimited HOOK:/BODY: format. Truncation-safe: a cut-off body
    still yields a usable hook+body."""
    m = _HOOK.search(raw)
    if not m:
        raise ValueError(f"draft missing HOOK:/BODY: markers: {raw[:120]!r}")
    return m.group(1).strip(), m.group(2).strip()


@dataclass
class Draft:
    key: str                 # = candidate.key (stable)
    stream: str
    candidate_key: str
    kind: str
    template: str
    title: str
    hook: str
    body: str
    evidence: list[dict] = field(default_factory=list)

    def text(self) -> str:
        return f"{self.hook}\n\n{self.body}"


def draft_one(candidate, voice: str, base_url: str, key: str, role: str,
              client=None) -> Draft:
    """Draft one candidate. Goes through the ContentLLMClient seam: the default
    is the local LiteLLM client, but any client (e.g. a test or a routed policy)
    can be injected without changing the call sites."""
    system, user = draft_prompts(candidate, voice)
    client = client or LiteLLMContentClient(base_url, key)
    resp = client.complete(ContentLLMRequest(system=system, user=user, model=role,
                                             temperature=0.5, max_tokens=1200))
    hook, body = parse_post(resp.text)
    if not hook or not body:
        raise ValueError(f"draft for {candidate.key} empty hook/body")
    tmpl = TEMPLATES.get(candidate.kind, TEMPLATES["repo"])[0]
    return Draft(key=candidate.key, stream=candidate.stream,
                 candidate_key=candidate.key, kind=candidate.kind, template=tmpl,
                 title=candidate.title, hook=hook, body=body,
                 evidence=list(candidate.evidence))
