from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class QuerySpec:
    origin: str
    destination: str
    date: str
    origin_tz: str


@dataclass
class Flight:
    origin: str
    destination: str
    date: str
    depart_time: Optional[str] = None
    arrive_time: Optional[str] = None
    stops: Optional[Any] = None
    price: Optional[Any] = None
    booking_url: str = ""
    raw: Any = None


class QueryStatus(str, Enum):
    OK = "ok"
    BLOCKED = "blocked"
    NETWORK_ERROR = "network_error"
    PARSE_ERROR = "parse_error"
    SCHEMA_CHANGE = "schema_change"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class QueryDiagnostics:
    url: str = ""
    status_code: Optional[int] = None
    reason: str = ""
    response_headers: Dict[str, str] = field(default_factory=dict)
    body_snippet: str = ""
    content_type: str = ""


@dataclass
class QueryOutcome:
    status: QueryStatus
    flights: List[Flight] = field(default_factory=list)
    error: str = ""
    diagnostics: QueryDiagnostics = field(default_factory=QueryDiagnostics)


@dataclass
class RunSummary:
    timestamp_utc: str
    planned_queries: int
    completed_queries: int
    ok_queries: int
    blocked_queries: int
    error_queries: int
    new_flights: int
    all_blocked: bool
    duration_seconds: float
