from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import airportsdata

from src.engine.models import QuerySpec

_AIRPORTS = None


class PlanError(Exception):
    pass


def load_airports() -> Dict[str, Any]:
    global _AIRPORTS
    if _AIRPORTS is None:
        _AIRPORTS = airportsdata.load("IATA")
    return _AIRPORTS


def resolve_timezone(origin: str, cfg: Dict[str, Any]) -> str:
    tz_cfg = cfg.get("timezone", {})
    override = tz_cfg.get("override")
    if override:
        return override
    airports = load_airports()
    airport = airports.get(origin)
    if not airport or not airport.get("tz"):
        raise PlanError(f"Timezone not found for origin {origin}")
    return airport["tz"]


def is_domestic(origin: str, destination: str) -> bool:
    airports = load_airports()
    origin_data = airports.get(origin)
    dest_data = airports.get(destination)
    if not origin_data or not dest_data:
        return True
    return origin_data.get("country") == dest_data.get("country")


def compute_dates(origin_tz: str, days_ahead: int, search_days: int, date_format: str) -> List[str]:
    now_local = datetime.now(ZoneInfo(origin_tz))
    start_date = (now_local + timedelta(days=days_ahead)).date()
    dates = []
    for offset in range(search_days):
        dates.append((start_date + timedelta(days=offset)).strftime(date_format))
    return dates


def plan_queries(cfg: Dict[str, Any], *, date_format: str) -> List[QuerySpec]:
    origins = [str(code).upper() for code in cfg.get("origins", [])]
    destinations = [str(code).upper() for code in cfg.get("destinations", [])]
    search_days = int(cfg.get("search_days", 1))

    planned: List[QuerySpec] = []
    for origin in origins:
        origin_tz = resolve_timezone(origin, cfg)
        for destination in destinations:
            if origin == destination:
                continue
            days_ahead = (
                cfg.get("days_ahead_domestic", 1)
                if is_domestic(origin, destination)
                else cfg.get("days_ahead_international", 10)
            )
            for date_str in compute_dates(origin_tz, int(days_ahead), search_days, date_format):
                planned.append(QuerySpec(origin=origin, destination=destination, date=date_str, origin_tz=origin_tz))
    return planned

