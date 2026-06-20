"""Breakdown-post templates. Each post follows the structure the user asked for
(what it is / why it's helpful / how I've used or would use it / how it helps),
and EVERY draft must ground its claims in the candidate's evidence - no invented
numbers or results (the no-overreach rule, enforced again by the judge panel)."""
from __future__ import annotations

# candidate.kind -> a template name + a one-line angle for the drafter
TEMPLATES = {
    "own-repo": ("build-in-public",
                 "a build-in-public update on the author's OWN work: what they built, "
                 "what it solves, and the lesson - grounded in the listed commits"),
    "paper": ("technical-lesson",
              "a plain-language breakdown of a paper/idea: what it is, why it matters, "
              "and how the author would use it in their work"),
    "repo": ("tool-breakdown",
             "a breakdown of a tool/library: what it does, when to reach for it, and "
             "how it fits real ML/sports-analytics work"),
    "signal": ("signal-take",
               "a short, substantive take on a development in the field: what happened "
               "and why it actually matters to practitioners"),
}

_SYSTEM = (
    "/no_think\n"
    "You write LinkedIn posts for a named author. You are rigorous and never invent "
    "facts, numbers, results, or benchmarks. Use ONLY the evidence provided. If the "
    "evidence doesn't support a claim, leave it out. No hype, no emoji filler.\n\n"
    "Output EXACTLY this format and nothing else:\n"
    "HOOK: <one punchy first line - the most important line on LinkedIn>\n"
    "BODY:\n"
    "<2-4 short paragraphs: what it is / why it's helpful / how the author has used "
    "or would use it / why it matters. End with one genuine question.>\n\n"
    "Keep the whole post under 180 words. Plain text, no markdown headers."
)


def draft_prompts(candidate, voice: str) -> tuple[str, str]:
    """(system, user) prompts to draft one candidate. The user prompt carries the
    evidence the draft must stay within."""
    tmpl_name, angle = TEMPLATES.get(candidate.kind, TEMPLATES["repo"])
    evidence_lines = "\n".join(
        f"- [{e['type']}] {e['ref']}: {e['detail']}" for e in candidate.evidence)
    user = (
        f"AUTHOR VOICE:\n{voice.strip()}\n\n"
        f"TEMPLATE: {tmpl_name} - {angle}\n\n"
        f"TOPIC: {candidate.title}\n"
        f"SUMMARY: {candidate.summary}\n"
        f"WHY-IT-MATTERS HINT: {candidate.suggested or '(none)'}\n"
        f"TOPICS: {candidate.topics}\n\n"
        f"EVIDENCE (stay within this; cite nothing else):\n{evidence_lines}\n\n"
        "Write the post now as strict JSON {\"hook\":..., \"body\":...}."
    )
    return _SYSTEM, user
