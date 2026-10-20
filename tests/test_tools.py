from datetime import datetime

import pytest

from tools import check_eligibility, search_events, travel_time, validate_itinerary


BASE_USER = {
    "interests": ["technology", "music"],
    "budget_inr": 1000,
    "free_from": "2026-10-24T08:00:00+05:30",
    "free_until": "2026-10-24T22:00:00+05:30",
    "is_student": True,
    "college": "IIT Madras",
    "age": 21,
    "home_area": "Guindy",
}


def violation_types(event_ids, user=None):
    return {item["type"] for item in validate_itinerary(event_ids, user or BASE_USER)}


def test_search_events_filters_area_tags_time_and_price():
    results = search_events(
        area="Guindy",
        tags=["technology"],
        start_after="2026-10-24T08:00:00+05:30",
        end_before="2026-10-24T18:00:00+05:30",
        max_price=400,
    )
    assert results
    assert all(event["area"] == "Guindy" for event in results)
    assert all("technology" in event["tags"] for event in results)
    assert all(event["price_inr"] <= 400 for event in results)


def test_travel_time_is_positive_and_symmetric_enough():
    minutes = travel_time("evt-01-01", "evt-06-03")
    assert minutes > 10
    assert abs(minutes - travel_time("evt-06-03", "evt-01-01")) <= 1


def test_check_eligibility_rejects_non_student_and_accepts_matching_student():
    assert check_eligibility("evt-01-01", {"is_student": False, "college": None, "age": 30})["ok"] is False
    assert check_eligibility("evt-01-01", {"is_student": True, "college": "IIT Madras", "age": 21})["ok"] is True


def test_time_clash_violation():
    assert "time clash" in violation_types(["evt-01-01", "evt-01-02"])


def test_insufficient_travel_gap_violation():
    assert "insufficient travel gap" in violation_types(["evt-01-04", "evt-06-06"])


def test_over_budget_violation():
    user = {**BASE_USER, "budget_inr": 100}
    assert "over budget" in violation_types(["evt-01-02"], user)


def test_free_window_violation():
    user = {**BASE_USER, "free_from": "2026-10-24T10:00:00+05:30"}
    assert "outside user's free window" in violation_types(["evt-01-01"], user)


def test_ineligible_violation():
    user = {**BASE_USER, "is_student": False, "college": None}
    assert "ineligible" in violation_types(["evt-01-01"], user)


def test_registration_closed_violation():
    assert "registration closed" in violation_types(["evt-01-01"])


def test_sold_out_violation():
    assert "sold out" in violation_types(["evt-02-02"])


def test_unknown_event_is_rejected():
    with pytest.raises(ValueError, match="Unknown event"):
        travel_time("missing", "evt-01-01")
