"""Command-line demonstration of initial planning and two replans."""
from agent import plan, replan
USER = {"interests": ["music", "technology", "culture"], "budget_inr": 500, "free_from": "2026-10-24T08:00:00+05:30", "free_until": "2026-10-24T22:00:00+05:30", "is_student": True, "college": "IIT Madras", "age": 21, "area": "Guindy"}
def show(label, value):
    print(f"\n=== {label} ===\nItinerary: {value['itinerary']}"); print("Changes:", value["changes"]) if "changes" in value else None; print("Trace:"); [print(x) for x in value["trace"]]
if __name__ == "__main__":
    initial = plan(USER, "Plan a balanced day in Guindy."); show("initial plan", initial)
    cheaper = replan(USER, initial, "my budget is now 300"); show("budget replan", cheaper)
    cancelled = cheaper["itinerary"][0] if cheaper["itinerary"] else "evt-01-02"; show("cancellation replan", replan(USER, cheaper, f"event {cancelled} got cancelled"))
