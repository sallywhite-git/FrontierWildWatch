from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.engine.models import Flight, QueryOutcome, QuerySpec, RunSummary


@dataclass(frozen=True)
class PlanBuilt:
    queries: List[QuerySpec]


@dataclass(frozen=True)
class QueryStarted:
    query: QuerySpec


@dataclass(frozen=True)
class QueryFinished:
    query: QuerySpec
    outcome: QueryOutcome
    duration_seconds: float


@dataclass(frozen=True)
class FlightFound:
    flight: Flight


@dataclass(frozen=True)
class RunCompleted:
    summary: RunSummary

