"""Deterministic event-planning tools for FUF Agent Phase 1."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).parent / "data" / "events.json"
AVERAGE_CITY_SPEED_KMH = 18
TRAVEL_BUFFER_MINUTES = 10


def _load_events() -> list[dict[str, Any]]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _as_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _event_map() -> dict[str, dict[str, Any]]:
    return {event["id"]: event for event in _load_events()}


def search_events(
    area: str | None = None,
    tags: list[str] | None = None,
    start_after: str | datetime | None = None,
    end_before: str | datetime | None = None,
    max_price: int | float | None = None,
) -> list[dict[str, Any]]:
    """Return events matching all supplied filters, ordered by start time."""
    wanted_tags = {tag.lower() for tag in (tags or [])}
    start_limit = _as_datetime(start_after) if start_after else None
    end_limit = _as_datetime(end_before) if end_before else None
    matches = []
    for event in _load_events():
        if area and event["area"].lower() != area.lower():
            continue
        if wanted_tags and not wanted_tags.intersection({tag.lower() for tag in event["tags"]}):
            continue
        if start_limit and _as_datetime(event["start"]) < start_limit:
            continue
        if end_limit and _as_datetime(event["end"]) > end_limit:
            continue
        if max_price is not None and event["price_inr"] > max_price:
            continue
        matches.append(event)
    return sorted(matches, key=lambda event: event["start"])


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_km = 6371.0
    lat1, lat2 = math.radians(lat1), math.radians(lat2)
    dlat = lat2 - lat1
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def travel_time(event_a_id: str, event_b_id: str) -> int:
    """Estimate one-way travel minutes between two events."""
    events = _event_map()
    try:
        event_a, event_b = events[event_a_id], events[event_b_id]
    except KeyError as exc:
        raise ValueError(f"Unknown event id: {exc.args[0]}") from exc
    distance_km = _haversine_km(event_a["lat"], event_a["lng"], event_b["lat"], event_b["lng"])
    return math.ceil(distance_km / AVERAGE_CITY_SPEED_KMH * 60 + TRAVEL_BUFFER_MINUTES)


def check_eligibility(event_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Check student, college, and minimum-age requirements for an event."""
    event = _event_map().get(event_id)
    if not event:
        raise ValueError(f"Unknown event id: {event_id}")
    rules = event["eligibility"]
    if rules["students_only"] and not user.get("is_student", False):
        return {"ok": False, "reason": "This event is limited to students."}
    required_college = rules.get("college_only")
    if required_college and user.get("college") != required_college:
        return {"ok": False, "reason": f"This event is restricted to {required_college} students."}
    if user.get("age", 0) < rules.get("min_age", 0):
        return {"ok": False, "reason": f"This event requires attendees to be at least {rules['min_age']}."}
    return {"ok": True, "reason": "Eligible for this event."}


def validate_itinerary(event_ids: list[str], user: dict[str, Any]) -> list[dict[str, Any]]:
    """Return human-readable violations for a proposed itinerary."""
    events = _event_map()
    missing = [event_id for event_id in event_ids if event_id not in events]
    if missing:
        raise ValueError(f"Unknown event id(s): {', '.join(missing)}")
    selected = [events[event_id] for event_id in event_ids]
    violations: list[dict[str, Any]] = []
    for event in selected:
        event_id = event["id"]
        if event["price_inr"] > user.get("budget_inr", float("inf")):
            violations.append({"type": "over budget", "event_ids": [event_id], "message": f"{event['title']} costs ₹{event['price_inr']}, above the ₹{user['budget_inr']} budget."})
        if not event["registration_open"]:
            violations.append({"type": "registration closed", "event_ids": [event_id], "message": f"Registration is closed for {event['title']}."})
        if event["capacity_left"] <= 0:
            violations.append({"type": "sold out", "event_ids": [event_id], "message": f"{event['title']} is sold out."})
        eligibility = check_eligibility(event_id, user)
        if not eligibility["ok"]:
            violations.append({"type": "ineligible", "event_ids": [event_id], "message": f"{event['title']}: {eligibility['reason']}"})
        free_from = _as_datetime(user["free_from"]) if user.get("free_from") else None
        free_until = _as_datetime(user["free_until"]) if user.get("free_until") else None
        if (free_from and _as_datetime(event["start"]) < free_from) or (free_until and _as_datetime(event["end"]) > free_until):
            violations.append({"type": "outside user's free window", "event_ids": [event_id], "message": f"{event['title']} is outside the user's free window."})
    total_price = sum(event["price_inr"] for event in selected)
    if total_price > user.get("budget_inr", float("inf")):
        violations.append({"type": "over budget", "event_ids": list(event_ids), "message": f"The itinerary totals ₹{total_price}, above the ₹{user['budget_inr']} budget."})
    ordered = sorted(selected, key=lambda event: event["start"])
    for previous, current in zip(ordered, ordered[1:]):
        previous_end = _as_datetime(previous["end"])
        current_start = _as_datetime(current["start"])
        if current_start < previous_end:
            violations.append({"type": "time clash", "event_ids": [previous["id"], current["id"]], "message": f"{previous['title']} overlaps with {current['title']}."})
        else:
            required_gap = travel_time(previous["id"], current["id"])
            actual_gap = int((current_start - previous_end).total_seconds() // 60)
            if actual_gap < required_gap:
                violations.append({"type": "insufficient travel gap", "event_ids": [previous["id"], current["id"]], "message": f"Only {actual_gap} minutes between events; travel needs {required_gap} minutes."})
    return violations
