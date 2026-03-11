import logging
import sys

# Suppress noisy hashlib environment errors on some macOS Python builds
logging.basicConfig(level=logging.CRITICAL)
logging.getLogger().setLevel(logging.CRITICAL)

import argparse
import html
import json
import os
import platform
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from src.frontier_client import FrontierClient, FrontierClientConfig
from src.state_store import load_state, save_state
from src.engine.engine import run_engine
from src.engine.events import FlightFound, QueryFinished, RunCompleted
from src.engine.fetchers import RequestsFrontierFetcher
from src.engine.models import QuerySpec, QueryStatus
from src.engine.notifiers import build_telegram_notifier
from src.engine.planner import plan_queries, resolve_timezone




class ConfigError(Exception):
    pass





def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _require(cfg: Dict[str, Any], key: str, expected_type: type) -> Any:
    if key not in cfg:
        raise ConfigError(f"Missing required config key: {key}")
    value = cfg[key]
    if not isinstance(value, expected_type):
        raise ConfigError(f"Config key '{key}' must be {expected_type.__name__}")
    return value


def validate_config(cfg: Dict[str, Any]) -> None:
    origins = _require(cfg, "origins", list)
    destinations = _require(cfg, "destinations", list)
    if not origins:
        raise ConfigError("origins cannot be empty")
    if not destinations:
        raise ConfigError("destinations cannot be empty")
    for code in origins + destinations:
        if not isinstance(code, str) or len(code) != 3 or not code.isalpha():
            raise ConfigError(f"Invalid IATA code: {code}")
    if cfg.get("days_ahead_domestic", 0) < 0:
        raise ConfigError("days_ahead_domestic must be >= 0")
    if cfg.get("days_ahead_international", 0) < 0:
        raise ConfigError("days_ahead_international must be >= 0")
    if cfg.get("search_days", 1) <= 0:
        raise ConfigError("search_days must be >= 1")


# Local-window guard removed: scheduling is controlled by cron and manual runs should always execute.

def build_client(cfg: Dict[str, Any]) -> FrontierClient:
    api_cfg = cfg.get("api", {})
    flights_path = api_cfg.get("flights_path")
    field_map = api_cfg.get("field_map", {})
    default_map = {
        "depart_time": ["departTime"],
        "arrive_time": ["arriveTime"],
        "stops": ["stops"],
        "price": ["price"],
    }
    for key, path in default_map.items():
        field_map.setdefault(key, path)
    config = FrontierClientConfig(
        base_url=api_cfg.get("base_url", "https://booking.flyfrontier.com/Flight/Availability"),
        method=api_cfg.get("method", "GET"),
        params_template=api_cfg.get("params_template", {"origin": "{origin}", "destination": "{destination}", "date": "{date}"}),
        headers=api_cfg.get("headers", {}),
        timeout_seconds=int(api_cfg.get("timeout_seconds", 20)),
        retries=int(api_cfg.get("retries", 3)),
        backoff_seconds=float(api_cfg.get("backoff_seconds", 2.0)),
        min_delay_seconds=float(api_cfg.get("min_delay_seconds", 1.0)),
        max_delay_seconds=float(api_cfg.get("max_delay_seconds", 3.0)),
        user_agents=api_cfg.get("user_agents"),
        date_format=api_cfg.get("date_format", "%Y-%m-%d"),
        flights_path=flights_path if isinstance(flights_path, list) else None,
        field_map={key: path for key, path in field_map.items() if isinstance(path, list)},
        mock_response_path=api_cfg.get("mock_response_path"),
        json_template=api_cfg.get("json_template"),
        use_mobile_signing=api_cfg.get("use_mobile_signing", False),
    )
    return FrontierClient(config)





def format_message(flight: Dict[str, Any], booking_url: str) -> str:
    route = f"{flight.get('origin')} -> {flight.get('destination')}"
    date = flight.get("date") or ""
    depart = flight.get("depart_time") or "?"
    arrive = flight.get("arrive_time") or "?"
    stops = flight.get("stops")
    price = flight.get("price")
    lines = [
        "GoWild availability detected",
        f"Route: {html.escape(str(route))}",
        f"Date: {html.escape(str(date))}",
        f"Time: {html.escape(str(depart))} - {html.escape(str(arrive))}",
        f"Stops: {html.escape(str(stops if stops is not None else '?'))}",
        f"Price: {html.escape(str(price if price is not None else '?'))}",
        f"<a href=\"{html.escape(booking_url)}\">Book now</a>",
    ]
    return "\n".join(lines)


def build_frontier_ui_url(origin: str, destination: str, date_str: str, ftype: str = "GW") -> str:
    # Browser-oriented booking flow (from observed UI navigation).
    # This is used only for humans to open when the automated client is blocked.
    # date format is typically "YYYY-MM-DD 00:00:00" in the UI querystring.
    dd1 = f"{date_str} 00:00:00".replace(" ", "%20")
    return (
        "https://booking.flyfrontier.com/Flight/InternalSelect"
        f"?o1={origin}&d1={destination}&dd1={dd1}"
        "&adt=1&umnr=false&loy=false&mon=true"
        f"&ftype={ftype}"
    )


def _parse_utc_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def run_scan(cfg: Dict[str, Any], dry_run: bool, dump_json: bool) -> int:
    validate_config(cfg)
    client = build_client(cfg)
    fetcher = RequestsFrontierFetcher(client=client)
    origins = [code.upper() for code in cfg["origins"]]
    destinations = [code.upper() for code in cfg["destinations"]]
    search_days = int(cfg.get("search_days", 1))
    state_path = cfg.get("output", {}).get("state_file", "state.json")
    report_path = cfg.get("output", {}).get("report_file", "run-report.json")

    planned = plan_queries(cfg, date_format=client.cfg.date_format)

    if dry_run:
        print(json.dumps({
            "planned_queries": [(q.origin, q.destination, q.date, q.origin_tz) for q in planned],
        }, indent=2))
        return 0

    state = load_state(state_path)
    cooldown_until = _parse_utc_iso(state.metrics.cooldown_until_utc)
    now_utc = datetime.now(UTC)
    if cooldown_until and now_utc < cooldown_until:
        remaining = (cooldown_until - now_utc).total_seconds()
        mins = int(max(0, remaining) // 60)
        print(f"Cooldown active until {state.metrics.cooldown_until_utc} (about {mins} minutes remaining). Skipping scan.")
        return 0

    # Local-window guard intentionally disabled: cron controls timing, and manual runs should always execute.

    notifier = None
    if cfg.get("telegram", {}).get("enabled", True):
        notifier = build_telegram_notifier(
            cfg.get("telegram", {}).get("bot_token_env", "TELEGRAM_BOT_TOKEN"),
            cfg.get("telegram", {}).get("chat_id_env", "TELEGRAM_CHAT_ID"),
        )

    new_keys = set(state.seen_keys)
    new_flights: List[Dict[str, Any]] = []
    all_found_flights: List[Dict[str, Any]] = []
    scan_errors: List[str] = []
    blocked_notice_sent = False
    blocked_count = 0

    completed_summary = None
    query_details: List[Dict[str, Any]] = []
    try:
        for event in run_engine(cfg=cfg, fetcher=fetcher, planned_queries=planned, seen_keys=new_keys):
            if isinstance(event, QueryFinished):
                outcome = event.outcome
                # ... (keep existing query_details logic)
                ui_url = build_frontier_ui_url(event.query.origin, event.query.destination, event.query.date, ftype="GW")
                query_details.append(
                    {
                        "origin": event.query.origin,
                        "destination": event.query.destination,
                        "date": event.query.date,
                        "origin_tz": event.query.origin_tz,
                        "status": outcome.status.value,
                        "duration_seconds": event.duration_seconds,
                        "flights": len(outcome.flights),
                        "error": outcome.error,
                        "ui_url": ui_url,
                        "diagnostics": {
                            "url": outcome.diagnostics.url,
                            "status_code": outcome.diagnostics.status_code,
                            "reason": outcome.diagnostics.reason,
                            "content_type": outcome.diagnostics.content_type,
                            "response_headers": outcome.diagnostics.response_headers,
                            "body_snippet": outcome.diagnostics.body_snippet,
                        },
                    }
                )
                
                # Capture all flights for the summary, regardless of if they are 'new'
                for f in outcome.flights:
                    all_found_flights.append({
                        "origin": f.origin,
                        "destination": f.destination,
                        "date": f.date,
                        "depart_time": f.depart_time,
                        "arrive_time": f.arrive_time,
                        "stops": f.stops,
                        "price": f.price,
                        "raw": f.raw,
                    })

                if outcome.status == QueryStatus.BLOCKED:
                    # ... (keep existing blocked logic)
                    blocked_count += 1
                    msg = (
                        f"Blocked by Frontier anti-bot for {event.query.origin}->{event.query.destination} {event.query.date}: "
                        f"{outcome.diagnostics.reason or 'blocked'}"
                    )
                    scan_errors.append(msg)
                    if not blocked_notice_sent:
                        print(msg)
                        if notifier and cfg.get("telegram", {}).get("notify_on_blocked", True):
                            notifier.send(f"<b>Frontier Access Blocked</b>\n{html.escape(msg)}\n<a href=\"{html.escape(ui_url)}\">Check UI</a>")
                        blocked_notice_sent = True
                elif outcome.status != QueryStatus.OK:
                    msg = (
                        f"Error querying {event.query.origin}->{event.query.destination} {event.query.date}: "
                        f"{outcome.status.value}: {outcome.error or outcome.diagnostics.reason}"
                    )
                    scan_errors.append(msg)
                    print(msg)
            elif isinstance(event, FlightFound):
                flight = event.flight
                flight_dict = {
                    "origin": flight.origin,
                    "destination": flight.destination,
                    "date": flight.date,
                    "depart_time": flight.depart_time,
                    "arrive_time": flight.arrive_time,
                    "stops": flight.stops,
                    "price": flight.price,
                    "booking_url": flight.booking_url,
                    "raw": flight.raw,
                }
                new_flights.append(flight_dict)
            elif isinstance(event, RunCompleted):
                completed_summary = event.summary
    finally:
        close = getattr(fetcher, "close", None)
        if callable(close):
            close()

    if dump_json:
        print(json.dumps({"new_flights": new_flights}, indent=2, default=str))

    state.seen_keys = list(new_keys)
    if completed_summary:
        if notifier and (all_found_flights or cfg.get("telegram", {}).get("notify_always", False)):
            summary_msg = [
                "<b>Frontier Scan Summary</b>",
                f"Planned: {completed_summary.planned_queries}",
                f"Successful: {completed_summary.ok_queries}",
                f"Blocked: {completed_summary.blocked_queries}",
                f"New Flights: {len(new_flights)}",
                f"Total Available: {len(all_found_flights)}",
                "",
            ]
            
            if all_found_flights:
                summary_msg.append("<b>Available GoWild Fares:</b>")
                # Sort by date, then origin, then time
                sorted_flights = sorted(all_found_flights, key=lambda x: (x['date'], x['origin'], x['depart_time']))
                for f in sorted_flights:
                    price_str = f"${f['price']}" if f['price'] is not None else "???"
                    
                    # Formatting helper for times (2026-02-27T17:49:00 -> 17:49)
                    def _fmt_t(t_str):
                        if not t_str or 'T' not in str(t_str): return str(t_str)
                        return t_str.split('T')[-1][:5]
                    
                    depart_fmt = _fmt_t(f['depart_time'])
                    arrive_fmt = _fmt_t(f['arrive_time'])
                    
                    layover_text = ""
                    raw = f.get('raw')
                    if raw and f.get('stops', 0) > 0:
                        l_time = raw.get('layoverTime')
                        segments = raw.get('segments', [])
                        if len(segments) > 1:
                            l_apt = segments[0].get('designator', {}).get('destination', "???")
                            if l_time:
                                try:
                                    h, m, _ = l_time.split(':')
                                    l_time_fmt = f"{int(h)}h {int(m)}m" if int(h) > 0 else f"{int(m)}m"
                                    layover_text = f" [Layover: {l_apt} {l_time_fmt}]"
                                except Exception:
                                    layover_text = f" [Layover: {l_apt}]"
                            else:
                                layover_text = f" [Layover: {l_apt}]"

                    # Escape fields just in case
                    safe_date = html.escape(str(f['date']))
                    safe_origin = html.escape(str(f['origin']))
                    safe_dest = html.escape(str(f['destination']))
                    safe_price = html.escape(str(price_str))
                    safe_depart = html.escape(str(depart_fmt))
                    safe_arrive = html.escape(str(arrive_fmt))
                    safe_layover = html.escape(str(layover_text))
                    
                    summary_msg.append(
                        f"• {safe_date} {safe_origin}→{safe_dest}: <b>{safe_price}</b> ({safe_depart} - {safe_arrive}){safe_layover}"
                    )
            else:
                summary_msg.append("No GoWild fares available currently.")

            notifier.send("\n".join(summary_msg))


        metrics_cfg = cfg.get("metrics", {}) if isinstance(cfg.get("metrics", {}), dict) else {}
        max_history = metrics_cfg.get("max_run_history")
        if max_history is not None:
            try:
                state.metrics.max_run_history = max(1, int(max_history))
            except Exception:
                pass
        cooldown_minutes = metrics_cfg.get("blocked_cooldown_minutes", 45)
        try:
            cooldown_minutes_int = max(0, int(cooldown_minutes))
        except Exception:
            cooldown_minutes_int = 45

        state.metrics.blocked_count += int(completed_summary.blocked_queries)
        state.metrics.error_count += int(completed_summary.error_queries)
        state.metrics.success_count += int(completed_summary.ok_queries)
        if completed_summary.ok_queries > 0:
            state.metrics.last_successful_run = completed_summary.timestamp_utc
        state.metrics.run_history.append(completed_summary)
        state.metrics.run_history = state.metrics.run_history[-state.metrics.max_run_history :]
        if completed_summary.all_blocked and cooldown_minutes_int > 0:
            state.metrics.cooldown_until_utc = (datetime.now(UTC) + timedelta(minutes=cooldown_minutes_int)).isoformat()

    save_state(state_path, state)
    if report_path:
        results = {
            "planned_queries": len(planned),
            "blocked_queries": blocked_count,
            "errors": len(scan_errors),
            "new_flights": len(new_flights),
            "state_size": len(new_keys),
        }
        if completed_summary:
            results.update(
                {
                    "completed_queries": completed_summary.completed_queries,
                    "ok_queries": completed_summary.ok_queries,
                    "blocked_queries": completed_summary.blocked_queries,
                    "error_queries": completed_summary.error_queries,
                    "all_blocked": completed_summary.all_blocked,
                    "duration_seconds": completed_summary.duration_seconds,
                }
            )
        report = {
            "kind": "frontierwildwatch-run-report",
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "environment": {
                "github_actions": bool(os.getenv("GITHUB_ACTIONS")),
                "platform": platform.platform(),
                "python": platform.python_version(),
            },
            "config": {
                "origins": origins,
                "destinations": destinations,
                "search_days": search_days,
                "days_ahead_domestic": cfg.get("days_ahead_domestic"),
                "days_ahead_international": cfg.get("days_ahead_international"),
            },
            "results": results,
            "queries": query_details,
            "error_messages": scan_errors[:200],
        }
        try:
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2)
        except Exception as exc:
            print(f"Warning: failed to write report {report_path}: {exc}")
    if scan_errors:
        print(f"Scan complete (with {len(scan_errors)} errors). Found {len(new_flights)} new flights. State size: {len(new_keys)}")
    else:
        print(f"Scan complete. Found {len(new_flights)} new flights. State size: {len(new_keys)}")

    if completed_summary:
        print(
            "Summary: "
            f"planned={completed_summary.planned_queries} "
            f"ok={completed_summary.ok_queries} "
            f"blocked={completed_summary.blocked_queries} "
            f"error={completed_summary.error_queries} "
            f"new_flights={completed_summary.new_flights} "
            f"duration={completed_summary.duration_seconds:.1f}s"
        )
    return 0


def probe_route(cfg: Dict[str, Any], origin: str, destination: str, date_str: str, output_path: str) -> int:
    validate_config(cfg)
    client = build_client(cfg)
    fetcher = RequestsFrontierFetcher(client=client)
    origin = origin.upper()
    destination = destination.upper()
    try:
        origin_tz = resolve_timezone(origin, cfg)
    except Exception:
        origin_tz = ""

    report = {
        "kind": "frontierwildwatch-probe",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "environment": {
            "github_actions": bool(os.getenv("GITHUB_ACTIONS")),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "query": {"origin": origin, "destination": destination, "date": date_str},
    }

    spec = QuerySpec(origin=origin, destination=destination, date=date_str, origin_tz=origin_tz)
    start = time.perf_counter()
    try:
        outcome = fetcher.fetch(spec)
    finally:
        close = getattr(fetcher, "close", None)
        if callable(close):
            close()
    duration = time.perf_counter() - start

    report["result"] = {
        "status": outcome.status.value,
        "duration_seconds": duration,
        "flights": len(outcome.flights),
        "error": outcome.error,
        "diagnostics": {
            "url": outcome.diagnostics.url,
            "status_code": outcome.diagnostics.status_code,
            "reason": outcome.diagnostics.reason,
            "content_type": outcome.diagnostics.content_type,
            "response_headers": outcome.diagnostics.response_headers,
            "body_snippet": outcome.diagnostics.body_snippet,
        },
    }
    report["sample"] = [f.__dict__ for f in outcome.flights[:3]]

    if outcome.status == QueryStatus.OK:
        print(f"Probe ok: {origin}->{destination} {date_str}. Flights: {len(outcome.flights)}")
        return_code = 0
    elif outcome.status == QueryStatus.BLOCKED:
        print(f"Probe blocked: {origin}->{destination} {date_str}: {outcome.diagnostics.reason}")
        return_code = 1
    else:
        print(f"Probe {outcome.status.value}: {origin}->{destination} {date_str}: {outcome.error or outcome.diagnostics.reason}")
        return_code = 1

    try:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, default=str)
    except Exception as exc:
        print(f"Warning: failed to write probe output {output_path}: {exc}")

    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Frontier GoWild availability scanner")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--dry-run", action="store_true", help="Print planned queries and exit")
    parser.add_argument("--dump-json", action="store_true", help="Print new flights as JSON")
    # No local-window guard flag: runs are always allowed; scheduling is handled by cron.
    parser.add_argument(
        "--probe",
        nargs=3,
        metavar=("ORIGIN", "DEST", "DATE"),
        help="Probe one route/date and write probe.json (e.g. --probe SNA SFO 2026-02-07)",
    )
    parser.add_argument("--probe-output", default="probe.json", help="Path for --probe JSON output")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.probe:
        origin, destination, date_str = args.probe
        return probe_route(cfg, origin, destination, date_str, args.probe_output)
    return run_scan(cfg, args.dry_run, args.dump_json)


if __name__ == "__main__":
    raise SystemExit(main())
