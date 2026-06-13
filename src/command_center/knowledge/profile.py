"""
The Growth OS OKF profile (`growth-os-0.1`) — a strict, contract-validated tightening of the
intentionally-permissive Open Knowledge Format v0.1.

OKF v0.1 requires only `type`; everything else is optional and unknown fields are allowed. That
is too loose for this system, where every artifact is a strict contract. This profile adds the
fields an agent needs to NOT mistake a generated explanation for the source of truth: where the
concept came from (`source_system`/`source_path`/`source_revision`/`source_hash`), how much to
trust it (`authority`/`confidence`/`status`), who owns it, and when it goes stale (`review_after`).

`authority` is the load-bearing field: our producers emit `derived` concepts that POINT AT the
authoritative source (a config, the Ledger, code). The OKF bundle is never the source of truth —
it is a portable, agent-readable projection. This mirrors the discovery scan's ObserverCharter:
source systems produce OKF; OKF never modifies source systems.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from ..schemas.base import Strict

OKF_VERSION = "0.1"
PROFILE = "growth-os-0.1"
GENERATOR = "growthos-okf-producer"
GENERATOR_VERSION = "0.1.0"


class SourceSystem(StrEnum):
    REPOSITORY = "repository"
    CONFIG = "config"
    DOCS = "docs"
    LEDGER = "ledger"
    GROWTH_OS = "growth_os"
    AIRFLOW = "airflow"


class Authority(StrEnum):
    AUTHORITATIVE = "authoritative"   # the source of truth itself (rare in a derived bundle)
    DERIVED = "derived"               # produced FROM an authoritative source — the default
    CURATED = "curated"               # human-authored knowledge
    OBSERVED = "observed"             # a measured observation/snapshot
    EXPERIMENTAL = "experimental"     # from an in-flight experiment
    HISTORICAL = "historical"         # a point-in-time record, may be outdated by design


class Status(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    DEPRECATED = "deprecated"
    DRAFT = "draft"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SECRET = "secret"                 # a secret must never be emitted into the bundle


class Confidence(StrEnum):
    VERIFIED = "verified"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNVERIFIED = "unverified"


class OkfConcept(Strict):
    """One OKF concept's frontmatter under the growth-os-0.1 profile. Strict: unknown fields are
    rejected (unlike base OKF) so a malformed concept fails the validation gate, not a consumer."""
    okf_version: str = OKF_VERSION
    profile: str = PROFILE

    type: str                          # "Data Pipeline" | "System" | "Standard" | "Experiment" | …
    title: str
    description: str
    resource: str                      # the authoritative target, e.g. repo://… or config://…
    tags: list[str] = Field(default_factory=list)

    timestamp: str                     # when this concept doc was produced (ISO-8601)
    last_verified_at: str              # when its facts were last checked against source (ISO-8601)

    source_system: SourceSystem
    source_path: str                   # the file/table/endpoint the facts came from
    source_revision: str | None = None  # git sha / row version when known (else honest null)
    source_hash: str | None = None      # sha256:… of the source content when known

    authority: Authority = Authority.DERIVED
    owner: str
    status: Status = Status.CURRENT
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    confidence: Confidence = Confidence.MEDIUM

    generated_by: str = GENERATOR
    generator_version: str = GENERATOR_VERSION
    mission_id: str | None = None
    experiment_id: str | None = None
    supersedes: str | None = None
    review_after: str | None = None     # ISO-8601; past this, a consumer should re-verify

    @model_validator(mode="after")
    def _checks(self):
        if self.profile != PROFILE:
            raise ValueError(f"profile must be {PROFILE!r}, got {self.profile!r}")
        if not self.type or not self.title:
            raise ValueError("type and title are required")
        if not self.resource:
            raise ValueError("resource is required — a concept must point at its authoritative source")
        if self.sensitivity is Sensitivity.SECRET:
            raise ValueError("a SECRET concept must never be written to the bundle")
        if self.source_hash is not None and not self.source_hash.startswith("sha256:"):
            raise ValueError("source_hash must be a 'sha256:…' digest or null")
        return self

    def to_frontmatter(self) -> dict:
        """A plain dict for YAML frontmatter (enums as their string values, nulls kept explicit)."""
        return self.model_dump(mode="json")
