"""Hybrid location/language/employment gate: verdicts, config merge, and the
score_job hard-exclude vs. soft-penalty behavior."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from command_center.job_search.config import merge_profile_settings
from command_center.job_search.geo_language import (
    evaluate_employment,
    evaluate_languages,
    evaluate_location,
    named_us_states,
)
from command_center.job_search.schemas import (
    AchievementBank,
    CanonicalJob,
    JobSearchConfig,
    RemoteType,
)
from command_center.job_search.scoring import score_job

CONFIG = Path("configs/job_search.yaml")


def _cfg(**location_overrides) -> JobSearchConfig:
    base = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if location_overrides:
        base["locations"].update(location_overrides)
    return JobSearchConfig.model_validate(base)


def _job(location="Remote", remote_type="unknown", desc="Data scientist.",
         title="Data Scientist") -> CanonicalJob:
    return CanonicalJob(
        job_key="k", company="C", role_title=title,
        normalized_company="c", normalized_role="r", location=location,
        remote_type=RemoteType(remote_type), apply_url="u",
        description_text=desc, last_seen_at=datetime.now(timezone.utc))


# --- location --------------------------------------------------------------
def test_remote_job_passes_regardless_of_region():
    cfg = _cfg()
    verdict, _ = evaluate_location(_job("Remote", "remote"), cfg)
    assert verdict == "remote_ok"


def test_target_state_and_metro_match():
    cfg = _cfg()
    assert evaluate_location(_job("Denver, CO", "onsite"), cfg)[0] == "match"
    assert evaluate_location(_job("Philadelphia, PA", "onsite"), cfg)[0] == "match"
    assert evaluate_location(_job("Seattle, WA", "hybrid"), cfg)[0] == "match"


def test_non_target_us_state_is_hard_mismatch():
    cfg = _cfg()
    assert evaluate_location(_job("New York, NY", "onsite"), cfg)[0] == "mismatch"
    assert evaluate_location(_job("Austin, TX", "onsite"), cfg)[0] == "mismatch"


def test_foreign_onsite_is_mismatch():
    cfg = _cfg()
    assert evaluate_location(
        _job("London, United Kingdom", "onsite"), cfg)[0] == "mismatch"


def test_national_only_location_is_ambiguous():
    cfg = _cfg()
    assert evaluate_location(_job("United States", "onsite"), cfg)[0] == "ambiguous"
    assert evaluate_location(_job("Unknown", "unknown"), cfg)[0] == "ambiguous"


def test_washington_dc_is_not_treated_as_washington_state():
    # WA is a target state; DC is not. "Washington, DC" must resolve to DC.
    assert named_us_states("Washington, DC") == {"DC"}
    assert named_us_states("Seattle, WA") == {"WA"}
    cfg = _cfg()
    assert evaluate_location(_job("Washington, DC", "onsite"), cfg)[0] == "mismatch"


def test_excluded_work_arrangement_is_hard_mismatch():
    cfg = _cfg(remote_types_allowed=["remote", "hybrid"])
    verdict, _ = evaluate_location(_job("Denver, CO", "onsite"), cfg)
    assert verdict == "arrangement_excluded"
    assert evaluate_location(_job("Denver, CO", "hybrid"), cfg)[0] == "match"


def test_worldwide_mode_accepts_any_onsite_location():
    cfg = _cfg(mode="worldwide")
    assert evaluate_location(_job("New York, NY", "onsite"), cfg)[0] == "match"


# --- language --------------------------------------------------------------
def test_required_language_is_required_gap():
    cfg = _cfg()
    verdict, langs = evaluate_languages(
        _job(desc="Must be fluent in German."), cfg)
    assert verdict == "required_gap" and "german" in langs


def test_preferred_language_is_soft_gap():
    cfg = _cfg()
    verdict, _ = evaluate_languages(_job(desc="German is a plus."), cfg)
    assert verdict == "preferred_gap"


def test_english_requirement_is_ok_for_english_speaker():
    cfg = _cfg()
    assert evaluate_languages(_job(desc="English required."), cfg)[0] == "ok"


# --- employment ------------------------------------------------------------
def test_full_time_filter_flags_contract_and_internship():
    cfg = _cfg()  # employment_types_allowed = [full_time]
    assert evaluate_employment(_job(desc="6-month contract, 1099."), cfg)[0] == "mismatch"
    assert evaluate_employment(_job(desc="Summer internship."), cfg)[0] == "mismatch"
    assert evaluate_employment(_job(desc="Full-time permanent role."), cfg)[0] == "ok"


# --- config merge ----------------------------------------------------------
def test_profile_override_merges_locations_and_languages():
    base = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    override = {
        "locations": {"regions": ["Texas"], "mode": "regions"},
        "languages": {"spoken": ["English", "Spanish"]},
    }
    merged = merge_profile_settings(base, override)
    cfg = JobSearchConfig.model_validate(merged)
    assert cfg.locations.regions == ["Texas"]
    # untouched fields survive the shallow section update
    assert cfg.locations.countries == ["United States"]
    assert cfg.locations.remote_ok is True
    assert cfg.languages.spoken == ["English", "Spanish"]


# --- score_job integration -------------------------------------------------
def _score(job: CanonicalJob) -> tuple[int, str]:
    cfg = _cfg()
    result = score_job(job, AchievementBank(achievements=[]), cfg)
    return result.score, result.action.value


def test_hard_excluded_job_is_skip_and_below_show_bar():
    cfg = _cfg()
    show = cfg.ranking.min_score_to_show
    score, action = _score(_job("New York, NY", "onsite",
                                desc="Python SQL data scientist."))
    assert action == "SKIP"
    assert score < show


def test_ambiguous_location_keeps_soft_penalty():
    cfg = _cfg()
    bank = AchievementBank(achievements=[])
    clean = score_job(_job("Remote", "remote"), bank, cfg).score
    ambiguous = score_job(_job("United States", "onsite"), bank, cfg)
    # the national-only posting loses exactly the ambiguous penalty vs. remote,
    # and it is not hard-excluded (still visible if it clears the show bar)
    assert ambiguous.score == clean - cfg.ranking.location_ambiguous_penalty
