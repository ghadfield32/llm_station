"""The content engine: gather evidence-backed candidates, draft breakdown posts
on the best local model, validate them with a multi-viewpoint judge panel
(escalating the advanced parts), and stage the top few as In Queue drafts.

No claim ships that isn't traceable to evidence (the no-overreach rule). The
human approval gate (drag In Queue -> In Progress) is unchanged.
"""
from .sources import Candidate, gather

__all__ = ["Candidate", "gather"]
