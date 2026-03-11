import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Protocol, Set

from src.engine.models import RunSummary


@dataclass
class Metrics:
    blocked_count: int = 0
    error_count: int = 0
    success_count: int = 0
    last_successful_run: str = ""
    cooldown_until_utc: str = ""
    last_blocked_notice_utc: str = ""
    run_history: List[RunSummary] = None  # type: ignore[assignment]
    max_run_history: int = 20

    def __post_init__(self) -> None:
        if self.run_history is None:
            self.run_history = []


@dataclass
class State:
    seen_keys: Set[str]
    last_updated_utc: str
    metrics: Metrics


class StateStore(Protocol):
    def load(self) -> State: ...

    def save(self, state: State) -> None: ...


@dataclass
class JsonStateStore:
    path: str

    def load(self) -> State:
        return load_state(self.path)

    def save(self, state: State) -> None:
        save_state(self.path, state)


def load_state(path: str) -> State:
    if not os.path.exists(path):
        return State(seen_keys=set(), last_updated_utc="", metrics=Metrics())
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    metrics_payload = payload.get("metrics") if isinstance(payload, dict) else None
    metrics = _parse_metrics(metrics_payload) if isinstance(metrics_payload, dict) else Metrics()
    return State(
        seen_keys=set(payload.get("seen_keys", [])),
        last_updated_utc=payload.get("last_updated_utc", ""),
        metrics=metrics,
    )


def _parse_run_summary(payload: Dict[str, Any]) -> Optional[RunSummary]:
    try:
        return RunSummary(
            timestamp_utc=str(payload.get("timestamp_utc", "")),
            planned_queries=int(payload.get("planned_queries", 0)),
            completed_queries=int(payload.get("completed_queries", 0)),
            ok_queries=int(payload.get("ok_queries", 0)),
            blocked_queries=int(payload.get("blocked_queries", 0)),
            error_queries=int(payload.get("error_queries", 0)),
            new_flights=int(payload.get("new_flights", 0)),
            all_blocked=bool(payload.get("all_blocked", False)),
            duration_seconds=float(payload.get("duration_seconds", 0.0)),
        )
    except Exception:
        return None


def _parse_metrics(payload: Dict[str, Any]) -> Metrics:
    history_raw = payload.get("run_history", [])
    history: List[RunSummary] = []
    if isinstance(history_raw, list):
        for item in history_raw:
            if isinstance(item, dict):
                parsed = _parse_run_summary(item)
                if parsed:
                    history.append(parsed)
    max_run_history = payload.get("max_run_history", 20)
    try:
        max_run_history = int(max_run_history)
    except Exception:
        max_run_history = 20

    return Metrics(
        blocked_count=int(payload.get("blocked_count", 0) or 0),
        error_count=int(payload.get("error_count", 0) or 0),
        success_count=int(payload.get("success_count", 0) or 0),
        last_successful_run=str(payload.get("last_successful_run", "") or ""),
        cooldown_until_utc=str(payload.get("cooldown_until_utc", "") or ""),
        last_blocked_notice_utc=str(payload.get("last_blocked_notice_utc", "") or ""),
        run_history=history[-max_run_history:] if max_run_history > 0 else [],
        max_run_history=max_run_history if max_run_history > 0 else 20,
    )


def _metrics_to_json(metrics: Metrics) -> Dict[str, Any]:
    return {
        "blocked_count": int(metrics.blocked_count),
        "error_count": int(metrics.error_count),
        "success_count": int(metrics.success_count),
        "last_successful_run": metrics.last_successful_run,
        "cooldown_until_utc": metrics.cooldown_until_utc,
        "last_blocked_notice_utc": metrics.last_blocked_notice_utc,
        "max_run_history": int(metrics.max_run_history),
        "run_history": [
            {
                "timestamp_utc": s.timestamp_utc,
                "planned_queries": s.planned_queries,
                "completed_queries": s.completed_queries,
                "ok_queries": s.ok_queries,
                "blocked_queries": s.blocked_queries,
                "error_queries": s.error_queries,
                "new_flights": s.new_flights,
                "all_blocked": s.all_blocked,
                "duration_seconds": s.duration_seconds,
            }
            for s in metrics.run_history[-metrics.max_run_history :]
        ],
    }


def save_state(path: str, state: State) -> None:
    payload = {
        "seen_keys": sorted(set(state.seen_keys)),
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "metrics": _metrics_to_json(state.metrics),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
