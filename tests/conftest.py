"""Suite-wide hermeticity guards.

The agent writer (job_search.agent_writer) calls the live LiteLLM proxy by
default. Tests must never depend on a running model server, so the kill switch
is pinned for the whole suite; tests that exercise the writer itself re-enable
it and inject a fake post_fn / monkeypatched generate_materials.

SMTP vars are pinned EMPTY (not deleted): writer_env() merges the repo .env
under os.environ, so an operator's real DISCOVERY_SMTP_* credentials in .env
would otherwise let finalize paths send real email mid-suite. Empty process
values win the merge and read as unconfigured.

GATEWAY_TRANSCRIPT_DIR is pinned to the test's tmp dir: the flight recorder
fires on EVERY GatewayCore turn, so any test that runs a turn would otherwise
append real transcript files under the repo's generated/chat-transcripts/.

classify_automation loads Geoff's REAL profile/standing_answers.yml through
config.data_root (tests pass tmp roots to functions, but the config still
points at data/job_search) — pinned to [] so classification outcomes never
depend on the operator's personal answers; tests for the coverage behavior
monkeypatch their own answers in.
"""
import pytest

_SMTP_VARS = (
    "DISCOVERY_SMTP_HOST", "DISCOVERY_SMTP_USER", "DISCOVERY_SMTP_PASSWORD",
    "DISCOVERY_SMTP_FROM", "DISCOVERY_SMTP_TO", "JOB_SEARCH_EMAIL_TO",
)


@pytest.fixture(autouse=True)
def _hermetic_job_search(monkeypatch, tmp_path):
    monkeypatch.setenv("JOB_SEARCH_AGENT_WRITER", "0")
    for var in _SMTP_VARS:
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("GATEWAY_TRANSCRIPT_DIR",
                       str(tmp_path / "chat-transcripts"))
    from command_center.job_search import automation_policy
    monkeypatch.setattr(automation_policy, "load_standing_answers",
                        lambda base: [])
