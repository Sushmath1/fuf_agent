"""Phase 3 Streamlit interface for the FUF Agent Chennai day planner."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

# Prefer Streamlit Cloud/local secrets when configured; otherwise load the
# developer's .env file. agent.py reads the resulting environment variable.
try:
    secret_key = st.secrets.get("GEMINI_API_KEY")
except Exception:
    secret_key = None
if secret_key:
    os.environ["GEMINI_API_KEY"] = str(secret_key)
else:
    load_dotenv(Path(__file__).parent / ".env")

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
        "college": None,
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


def _render_eggy(message: str, *, hopping: bool = False, placeholder: Any = None) -> None:
    """Render Eggy and a responsive speech bubble using inline SVG/CSS."""
    motion_class = " eggy-hop" if hopping else ""
    markup = f"""
    <style>
      .eggy-wrap {{ display:flex; align-items:center; gap:14px; margin:0 0 1.1rem; width:100%; }}
      .eggy {{ width:88px; min-width:88px; animation: eggy-bob 2.4s ease-in-out infinite; filter:drop-shadow(0 8px 8px rgba(0,0,0,.24)); }}
      .eggy-hop {{ animation: eggy-hop .62s cubic-bezier(.25,.8,.35,1) 1; }}
      .eggy-bubble {{ flex:1; background:#3a202c; color:#fff4f6; border:1px solid #85415b; border-radius:18px; padding:13px 16px; line-height:1.35; box-shadow:0 6px 20px rgba(0,0,0,.18); position:relative; }}
      .eggy-bubble:before {{ content:""; position:absolute; left:-9px; top:25px; border-width:8px 9px 8px 0; border-style:solid; border-color:transparent #85415b transparent transparent; }}
      .eggy-bubble:after {{ content:""; position:absolute; left:-7px; top:26px; border-width:7px 8px 7px 0; border-style:solid; border-color:transparent #3a202c transparent transparent; }}
      @keyframes eggy-bob {{ 0%,100% {{ transform:translateY(0); }} 50% {{ transform:translateY(-5px); }} }}
      @keyframes eggy-hop {{ 0% {{ transform:translateY(0) rotate(0); }} 35% {{ transform:translateY(-14px) rotate(-4deg); }} 70% {{ transform:translateY(0) rotate(3deg); }} 100% {{ transform:translateY(0) rotate(0); }} }}
      @media (max-width:520px) {{ .eggy-wrap {{ gap:9px; }} .eggy {{ width:68px; min-width:68px; }} .eggy-bubble {{ font-size:.9rem; padding:10px 12px; }} }}
    </style>
    <div class="eggy-wrap">
      <div class="eggy{motion_class}" aria-label="Eggy mascot">
        <svg viewBox="0 0 120 140" role="img" xmlns="http://www.w3.org/2000/svg">
          <ellipse cx="60" cy="132" rx="33" ry="5" fill="#120d10" opacity=".28"/>
          <path d="M60 9C35 9 18 35 18 70c0 35 17 57 42 57s42-22 42-57C102 35 85 9 60 9Z" fill="#fffaf0" stroke="#d8bfc3" stroke-width="3"/>
          <path d="M32 34c8-13 18-19 29-21" fill="none" stroke="#fff" stroke-linecap="round" stroke-width="7" opacity=".8"/>
          <path d="M38 68c4-5 8-5 12 0M70 68c4-5 8-5 12 0" fill="none" stroke="#542238" stroke-linecap="round" stroke-width="3"/>
          <circle cx="31" cy="82" r="7" fill="#ef9aa7" opacity=".75"/><circle cx="89" cy="82" r="7" fill="#ef9aa7" opacity=".75"/>
          <path d="M51 84c5 7 13 7 18 0" fill="none" stroke="#542238" stroke-linecap="round" stroke-width="3"/>
          <path d="M35 124c-6 5-10 7-14 5M85 124c6 5 10 7 14 5" fill="none" stroke="#8d3653" stroke-linecap="round" stroke-width="4"/>
          <path d="M45 17c5-6 10-8 15-8 5 0 10 2 15 8" fill="none" stroke="#8d3653" stroke-linecap="round" stroke-width="4"/>
        </svg>
      </div>
      <div class="eggy-bubble">{message}</div>
    </div>
    """
    target = placeholder if placeholder is not None else st
    target.markdown(markup, unsafe_allow_html=True)


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
        if next_travel is not None and next_event is not None:
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


def _used_fallback(plan: dict[str, Any]) -> bool:
    return any(step.get("type") in {"model_error", "fallback"} for step in plan.get("trace", []))


st.set_page_config(page_title="FUF Agent", page_icon="🥚", layout="wide")
if "eggy_state" not in st.session_state:
    st.session_state.eggy_state = "start"

EGGY_MESSAGES = {
    "start": "Hi! I'm Eggy 🥚 Tell me what you love and when you're free, and I'll plan your day!",
    "planning": "Cracking your perfect day... 🍳",
    "ready": "Ta-da! Here's your day. No clashes, all within budget!",
    "replan": "Shuffled things around for you! Here's what changed ✨",
    "empty": "Hmm, nothing fits just right. Try a bigger budget or more free time? I believe in you!",
    "fallback": "My AI brain is napping, but I still made you a plan! 💛",
}

st.markdown('<span style="display:inline-block;padding:0.3rem 0.7rem;border-radius:999px;background:#3a202c;color:#f8eef1;font-size:0.85rem;font-weight:600;">● Demo dataset: Chennai, Sat 24 Oct</span>', unsafe_allow_html=True)
eggy_slot = st.empty()
_render_eggy(
    EGGY_MESSAGES[st.session_state.eggy_state],
    hopping=st.session_state.eggy_state == "replan",
    placeholder=eggy_slot,
)
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
    st.number_input("Age", min_value=0, max_value=120, value=21, step=1, key="age")

user = _user_from_sidebar()
if st.button("Plan my day", type="primary", use_container_width=True):
    if user["free_until"] <= user["free_from"]:
        st.error("Free until must be later than free from.")
    else:
        st.session_state.eggy_state = "planning"
        _render_eggy(EGGY_MESSAGES["planning"], placeholder=eggy_slot)
        with st.spinner("Checking events, eligibility, and travel gaps…"):
            st.session_state.plan = agent.plan(user, "Plan my day")
        st.session_state.plan_user = user
        if not st.session_state.plan.get("itinerary"):
            st.session_state.eggy_state = "empty"
        elif _used_fallback(st.session_state.plan):
            st.session_state.eggy_state = "fallback"
        else:
            st.session_state.eggy_state = "ready"
        st.rerun()

plan = st.session_state.get("plan")
if plan:
    if not _render_plan(plan):
        st.session_state.eggy_state = "empty"
    _render_changes(plan)
    st.divider()
    request = st.chat_input("Ask to change the plan… e.g. cancel the comedy event or lower budget to ₹500")
    if request:
        st.session_state.eggy_state = "planning"
        _render_eggy(EGGY_MESSAGES["planning"], placeholder=eggy_slot)
        with st.spinner("Replanning your day…"):
            st.session_state.plan = agent.replan(st.session_state.get("plan_user", user), plan, request)
        st.session_state.plan_user = agent._updated_user(st.session_state.get("plan_user", user), request)
        st.session_state.eggy_state = "replan"
        st.rerun()
    _render_trace(plan.get("trace", []))
else:
    st.info("Set your preferences in the sidebar, then choose **Plan my day**.")
