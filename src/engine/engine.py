from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from src.engine.events import FlightFound, PlanBuilt, QueryFinished, QueryStarted, RunCompleted
from src.engine.fetchers import Fetcher
from src.engine.models import Flight, QuerySpec, QueryStatus, RunSummary


def flight_key(flight: Flight) -> str:
    key_payload = {
        "origin": flight.origin,
        "destination": flight.destination,
        "date": flight.date,
        "depart_time": flight.depart_time,
        "arrive_time": flight.arrive_time,
        "stops": flight.stops,
        "price": flight.price,
    }
    raw = json.dumps(key_payload, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_booking_url(template: str, flight: Flight) -> str:
    return (
        template.replace("{origin}", str(flight.origin))
        .replace("{destination}", str(flight.destination))
        .replace("{date}", str(flight.date))
    )


def _passes_filters(flight: Flight, nonstop_only: bool, max_stops: Optional[int]) -> bool:
    stops = flight.stops
    if nonstop_only and stops not in (0, "0", None):
        return False
    if max_stops is not None and stops is not None:
        try:
            if int(stops) > int(max_stops):
                return False
        except (TypeError, ValueError):
            pass
    return True


def run_engine(
    *,
    cfg: Dict[str, Any],
    fetcher: Fetcher,
    planned_queries: List[QuerySpec],
    seen_keys: Set[str],
) -> Iterator[object]:
    start = time.perf_counter()

    filters_cfg = cfg.get("filters", {})
    max_stops = filters_cfg.get("max_stops")
    nonstop_only = bool(filters_cfg.get("nonstop_only", False))

    template = cfg.get("booking_url_template", "https://www.flyfrontier.com/")

    planned = list(planned_queries)
    yield PlanBuilt(queries=planned)

    completed = 0
    ok = 0
    blocked = 0
    errors = 0
    new_flights = 0

    for spec in planned:
        yield QueryStarted(query=spec)
        q_start = time.perf_counter()
        outcome = fetcher.fetch(spec)
        q_dur = time.perf_counter() - q_start
        completed += 1

        if outcome.status == QueryStatus.OK:
            ok += 1
        elif outcome.status == QueryStatus.BLOCKED:
            blocked += 1
        else:
            errors += 1

        yield QueryFinished(query=spec, outcome=outcome, duration_seconds=q_dur)

        if outcome.status != QueryStatus.OK:
            continue

        for flight in outcome.flights:
            if not _passes_filters(flight, nonstop_only=nonstop_only, max_stops=max_stops):
                continue

            flight.booking_url = build_booking_url(template, flight)
            key = flight_key(flight)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            new_flights += 1
            yield FlightFound(flight=flight)

    all_blocked = bool(planned) and blocked == completed and ok == 0 and errors == 0
    summary = RunSummary(
        timestamp_utc=datetime.now(UTC).isoformat(),
        planned_queries=len(planned),
        completed_queries=completed,
        ok_queries=ok,
        blocked_queries=blocked,
        error_queries=errors,
        new_flights=new_flights,
        all_blocked=all_blocked,
        duration_seconds=time.perf_counter() - start,
    )
    yield RunCompleted(summary=summary)
