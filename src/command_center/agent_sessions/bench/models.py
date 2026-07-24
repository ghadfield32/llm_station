"""Typed contracts for the adapter capability bench."""
from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import model_validator

from ...schemas.base import Strict


class Dimension(StrEnum):
    STREAMING = "streaming"
    RESUME = "resume"
    WRITE_MODE_WALL = "write_mode_wall"
    ATTACHMENTS = "attachments"
    MODEL_SWITCH = "model_switch"
    INTERRUPT = "interrupt"
    STEERING = "steering"


CORE_DIMENSIONS: tuple[Dimension, ...] = tuple(Dimension)


class Verdict(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    DRIFT = "DRIFT"


_DECLARED_VERDICTS = frozenset({Verdict.PASS, Verdict.PARTIAL, Verdict.FAIL})


class BenchProfile(Strict):
    """One harness's claims. Capability facts belong on the harness class."""

    adapter: str
    streaming: Verdict
    resume: Verdict
    write_mode_wall: Verdict
    attachments: Verdict
    model_switch: Verdict
    interrupt: Verdict
    steering: Verdict

    @model_validator(mode="after")
    def _claims_are_capabilities(self) -> "BenchProfile":
        for dimension in CORE_DIMENSIONS:
            verdict = self.verdict_for(dimension)
            if verdict not in _DECLARED_VERDICTS:
                raise ValueError(
                    f"{dimension.value} declaration must be PASS, PARTIAL, or FAIL")
        return self

    def verdict_for(self, dimension: Dimension) -> Verdict:
        return Verdict(getattr(self, dimension.value))


class ProbeResult(Strict):
    dimension: Dimension
    observed_verdict: Verdict
    detail: str

    @model_validator(mode="after")
    def _probe_cannot_declare_drift(self) -> "ProbeResult":
        if self.observed_verdict is Verdict.DRIFT:
            raise ValueError("DRIFT is a reconciliation verdict, not a probe observation")
        if not self.detail:
            raise ValueError("probe detail must explain its evidence or skip reason")
        return self


class Cell(Strict):
    adapter: str
    dimension: Dimension
    declared: Verdict
    observed: Verdict
    verdict: Verdict
    detail: str


class MatrixReport(Strict):
    schema_version: ClassVar[int] = 1
    mode: str
    dimensions: list[Dimension]
    cells: list[Cell]
    summary: dict[Verdict, int]

    def json_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **self.model_dump(mode="json"),
        }
