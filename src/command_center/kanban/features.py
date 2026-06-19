"""Pre-decision feature names for the tuning learner + the leakage guard.

The tuning learner (tuning.py) may only key off signals known *before* the
resolution outcome — the same no-leakage discipline as the discovery scan's
acceptance learner. The validate gate asserts none of FEATURE_NAMES contains a
leakage token, so an outcome field can never silently become an input.
"""
from __future__ import annotations

# Signals available at resolution time, before we know whether the match was right.
FEATURE_NAMES = ["match_ratio", "title_len", "candidate_count", "is_exact"]

# Tokens that would mean an outcome/label leaked into the feature set.
LEAKAGE_TOKENS = ("correct", "accepted", "outcome", "label", "reversed",
                  "verdict", "status", "decision", "approved")
