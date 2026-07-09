"""Suite-wide hermeticity guards.

The agent writer (job_search.agent_writer) calls the live LiteLLM proxy by
default. Tests must never depend on a running model server, so the kill switch
is pinned for the whole suite; tests that exercise the writer itself re-enable
it and inject a fake post_fn / monkeypatched generate_materials.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_agent_writer(monkeypatch):
    monkeypatch.setenv("JOB_SEARCH_AGENT_WRITER", "0")
