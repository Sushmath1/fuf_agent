"""Phase 3 Streamlit interface for the FUF Agent Chennai day planner."""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import streamlit as st

import agent
from tools import travel_time

DATA_PATH = Path(__file__).parent / "data" / "events.json"
EVENTS = json.loads(DATA_PATH.read_text(encoding="utf-8"))
EVENTS_BY_ID = {event["id"]: event for event in EVENTS}
AREAS = ["All areas", *sorted({event["area"] for event in EVENTS})]
TAGS = sorted({tag for event in EVENTS for tag in event.get("tags", [])})
DAY = date(2026, 10, 24)
TZ_SUFFIX = "+05:30"


def _iso(value: time) -> str:
    return f"{DAY.isoformat()}T{value.strftime('%H:%M')}:00{TZ_SUFFIX}"


def _user_from_sidebar() -> dict[str, Any]:
    return {
        "area": None if st.session_state.area == "All areas" else st.session_state.area,
        "interests": st.session_state.interests,
        "budget_inr": st.session_state.budget,
        "free_from": _iso(st.session_state.free_from),
        "free_until": _iso(st.session_state.free_until),
        "is_student": st.session_state.is_student,
        "college": st.session_state.college.strip() or None,
        "age": st.session_state.age,
    }


def _render_trace(trace: list[dict[str, Any]]) -> None:
    with st.expander("Agent trace", expanded=False):
        if not trace:
            st.caption("No trace steps yet.")
        for index, step in enumerate(trace, 1):
            kind = step.get("type", "step").replace("_", " ").title()
            tool = step.get("tool", step.get("type", "agent"))
            args = step.get("arguments", step.get("event_ids", {}))
            result = step.get("summary", step.get("violations", ""))
            verdict = "CHECK"
            if step.get("type") == "validation":
                verdict = "PASS" if not step.get("violations") else "FAIL"
            st.markdown(f"**{index}. {kind}** · `{tool}` · :orange[{verdict}]")
            st.caption(f"Args: {args}")
            st.caption(f"Result: {result}")


def _render_plan(plan: dict[str, Any]) -> None:
    itinerary = [EVENTS_BY_ID[event_id] for event_id in plan.get("itinerary", []) if event_id in EVENTS_BY_ID]
    budget = st.session_state.budget
    total = sum(event["price_inr"] for event in itinerary)
    st.subheader("Your Chennai day")
    if not itinerary:
        st.info("No events fit all of the current constraints. Try a wider window or a higher budget.")
    for index, event in enumerate(itinerary):
        start = datetime.fromisoformat(event["start"]).strftime("%I:%M %p").lstrip("0")
        end = datetime.fromisoformat(event["end"]).strftime("%I:%M %p").lstrip("0")
        next_event = itinerary[index + 1] if index + 1 < len(itinerary) else None
        next_travel = travel_time(event["id"], next_event["id"]) if next_event else None
        st.markdown(f"### {start} — {event['title']}")
        st.caption(f"{start}–{end}  ·  {event['venue']}  ·  {event['area']}")
        st.write(f"₹{event['price_inr']}  ·  {event['category'].title()}")
        if next_travel is not None:
            st.info(f"↳ {next_travel} min travel to **{next_event['title']}**")
        if index < len(itinerary) - 1:
            st.divider()
    used = (total / budget * 100) if budget else 0
    st.metric("Total cost", f"₹{total} / ₹{budget}", f"{used:.0f}% of budget")
    st.progress(min(used / 100, 1.0))
    st.markdown("**Why this plan**")
    st.write(plan.get("explanation", "Selected events that fit your interests, free window, eligibility, and travel constraints."))
    alternatives = plan.get("alternatives", [])
    with st.expander("Why not these"):
        if alternatives:
            for option in alternatives:
                event = EVENTS_BY_ID.get(option.get("event_id"))
                if event:
                    st.write(f"• **{event['title']}** — {option.get('why_not_chosen', 'Not selected.')}")
        else:
            st.caption("No alternatives were returned.")


def _render_changes(plan: dict[str, Any]) -> None:
    changes = plan.get("changes", {})
    dropped = changes.get("dropped", [])
    added = changes.get("added", [])
    if dropped or added:
        st.subheader("What changed")
        left, right = st.columns(2)
        with left:
            st.markdown("**Dropped**")
            for item in dropped:
                event = EVENTS_BY_ID.get(item.get("event_id"))
                if event:
                    st.warning(event["title"])
        with right:
            st.markdown("**Added**")
            for item in added:
                event = EVENTS_BY_ID.get(item.get("event_id"))
                if event:
                    st.success(event["title"])


st.set_page_config(page_title="FUF Agent", page_icon="🗺️", layout="wide")
st.markdown('<span style="display:inline-block;padding:0.3rem 0.7rem;border-radius:999px;background:#3a202c;color:#f8eef1;font-size:0.85rem;font-weight:600;">● Demo dataset: Chennai, Sat 24 Oct</span>', unsafe_allow_html=True)
st.title("Plan a day that feels like you")
st.caption("FUF Agent finds a practical Chennai itinerary from the demo event dataset.")

with st.sidebar:
    st.header("Your day")
    st.selectbox("Area", AREAS, key="area")
    st.multiselect("Interests", TAGS, key="interests", help="Choose any tags that sound good.")
    st.slider("Budget", 0, 2000, 1000, 50, format="₹%d", key="budget")
    st.time_input("Free from", value=time(8, 0), key="free_from")
    st.time_input("Free until", value=time(22, 0), key="free_until")
    st.toggle("I am a student", value=True, key="is_student")
    st.text_input("College", value="IIT Madras", key="college")
    st.number_input("Age", min_value=0, max_value=120, value=21, step=1, key="age")

user = _user_from_sidebar()
if st.button("Plan my day", type="primary", use_container_width=True):
    if user["free_until"] <= user["free_from"]:
        st.error("Free until must be later than free from.")
    else:
        with st.spinner("Checking events, eligibility, and travel gaps…"):
            st.session_state.plan = agent.plan(user, "Plan my day")
        st.session_state.plan_user = user

plan = st.session_state.get("plan")
if plan:
    _render_plan(plan)
    _render_changes(plan)
    st.divider()
    request = st.chat_input("Ask to change the plan… e.g. cancel the comedy event or lower budget to ₹500")
    if request:
        with st.spinner("Replanning your day…"):
            st.session_state.plan = agent.replan(st.session_state.get("plan_user", user), plan, request)
        st.session_state.plan_user = agent._updated_user(st.session_state.get("plan_user", user), request)
        st.rerun()
    _render_trace(plan.get("trace", []))
else:
    st.info("Set your preferences in the sidebar, then choose **Plan my day**.")
