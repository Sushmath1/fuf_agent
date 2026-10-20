"""Streamlit UI for exploring and validating a Chennai day itinerary."""

import streamlit as st

from tools import search_events, validate_itinerary


st.set_page_config(page_title="FUF Agent", page_icon="🗺️", layout="wide")
st.title("FUF Agent")
st.caption("Phase 1: deterministic event search and itinerary validation for Chennai")

areas = ["All areas", "Guindy", "T Nagar", "Mylapore", "Adyar", "Anna Nagar", "OMR", "Besant Nagar"]
area = st.sidebar.selectbox("Area", areas)
max_price = st.sidebar.number_input("Maximum price per event (₹)", min_value=0, value=1000, step=50)
selected_tags = st.sidebar.multiselect(
    "Interests",
    ["technology", "coding", "music", "culture", "design", "food", "dance", "comedy", "networking", "students"],
)

results = search_events(area=None if area == "All areas" else area, tags=selected_tags, max_price=max_price)
st.subheader(f"Events ({len(results)})")

if not results:
    st.info("No events match those filters.")
else:
    labels = {
        event["id"]: f"{event['start'][11:16]} · {event['title']} · ₹{event['price_inr']}"
        for event in results
    }
    chosen_ids = st.multiselect("Choose events for your itinerary", list(labels), format_func=labels.get)
    for event in results:
        with st.expander(f"{event['title']} · {event['start'][11:16]}–{event['end'][11:16]}"):
            st.write(f"**{event['category'].title()}** at {event['venue']} ({event['area']})")
            st.write(f"Tags: {', '.join(event['tags'])} · ₹{event['price_inr']} · {event['capacity_left']} spots left")

st.divider()
st.subheader("Validate itinerary")
col1, col2, col3 = st.columns(3)
with col1:
    is_student = st.checkbox("I am a student", value=True)
with col2:
    college = st.text_input("College", value="IIT Madras")
with col3:
    age = st.number_input("Age", min_value=0, value=21)

if st.button("Validate selected itinerary"):
    user = {
        "interests": selected_tags,
        "budget_inr": max_price,
        "free_from": "2026-10-24T08:00:00+05:30",
        "free_until": "2026-10-24T22:00:00+05:30",
        "is_student": is_student,
        "college": college or None,
        "age": age,
        "home_area": area if area != "All areas" else None,
    }
    violations = validate_itinerary(chosen_ids, user)
    if violations:
        st.error(f"Found {len(violations)} violation(s)")
        for violation in violations:
            st.warning(f"**{violation['type']}** — {violation['message']}")
    else:
        st.success("This itinerary satisfies the Phase 1 deterministic checks.")
