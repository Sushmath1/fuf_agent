"""Phase 2 itinerary agent with optional Gemini planning and safe fallback."""
from __future__ import annotations
import json, os, re
from typing import Any, Callable
from dotenv import load_dotenv
from tools import check_eligibility, search_events, travel_time, validate_itinerary
load_dotenv()
try:
    from google import genai
except ImportError:
    genai = None
MAX_MODEL_STEPS = 8
SYSTEM_PROMPT = """Plan Chennai itineraries. Never invent events: use only search_events results. You may call search_events, check_eligibility, and travel_time. Prefer fewer, better events. Python validates every itinerary; revise after violations. Return JSON with itinerary event ids, explanation, and alternatives [{event_id, why_not_chosen}]."""

def _summary(value: Any) -> Any:
    if isinstance(value, list): return {"count": len(value), "ids": [x.get("id") for x in value if isinstance(x, dict) and "id" in x]}
    if isinstance(value, dict): return {k: value[k] for k in ("ok", "reason", "type", "message") if k in value}
    return value

def _tool(trace: list[dict[str, Any]], name: str, fn: Callable[..., Any], **kwargs: Any) -> Any:
    trace.append({"type": "tool_call", "tool": name, "arguments": kwargs})
    try:
        result = fn(**kwargs); trace.append({"type": "tool_result", "tool": name, "summary": _summary(result)}); return result
    except Exception as exc:
        trace.append({"type": "tool_result", "tool": name, "summary": {"error": str(exc)}}); return None

def _events() -> dict[str, dict[str, Any]]: return {e["id"]: e for e in search_events()}

def _updated_user(user: dict[str, Any], text: str) -> dict[str, Any]:
    result = dict(user or {}); m = re.search(r"budget\s+(?:is\s+)?(?:now\s+)?(?:₹|rs\.?\s*)?(\d+(?:\.\d+)?)", text, re.I)
    if m: result["budget_inr"] = float(m.group(1))
    return result

def _cancelled(text: str, events: dict[str, dict[str, Any]]) -> set[str]:
    if not re.search(r"cancel(?:led|ed)?", text, re.I): return set()
    ids = set(re.findall(r"evt-\d{2}-\d{2}", text, re.I)); low = text.lower()
    ids.update(i for i, e in events.items() if e["title"].lower() in low); return ids

def _greedy(user: dict[str, Any], trace: list[dict[str, Any]], excluded: set[str] | None = None) -> tuple[list[str], list[dict[str, str]]]:
    excluded = excluded or set(); candidates = _tool(trace, "search_events", search_events, area=user.get("area"), tags=user.get("interests"), start_after=user.get("free_from"), end_before=user.get("free_until"), max_price=user.get("budget_inr")) or []
    chosen, total = [], 0.0
    for event in candidates:
        if event["id"] in excluded: continue
        eligible = _tool(trace, "check_eligibility", check_eligibility, event_id=event["id"], user=user)
        if not eligible or not eligible.get("ok") or not event["registration_open"] or event["capacity_left"] <= 0: continue
        if total + event["price_inr"] > float(user.get("budget_inr", float("inf"))): continue
        trial = chosen + [event["id"]]; violations = validate_itinerary(trial, user); trace.append({"type": "validation", "event_ids": trial, "violations": violations})
        if not violations: chosen.append(event["id"]); total += event["price_inr"]
    alternatives = [{"event_id": e["id"], "why_not_chosen": "Lower priority or conflicts with the selected itinerary."} for e in candidates if e["id"] not in chosen]
    return chosen, alternatives[:12]

def _model_plan(user: dict[str, Any], request_text: str, trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not os.getenv("GEMINI_API_KEY") or genai is None: return None
    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"]); contents: Any = f"User: {json.dumps(user)}\\nRequest: {request_text}"
        declarations = [{"name": "search_events", "description": "Search known events", "parameters": {"type": "OBJECT", "properties": {"area": {"type": "STRING"}, "tags": {"type": "ARRAY", "items": {"type": "STRING"}}, "max_price": {"type": "NUMBER"}}}}, {"name": "check_eligibility", "description": "Check eligibility", "parameters": {"type": "OBJECT", "properties": {"event_id": {"type": "STRING"}, "user": {"type": "OBJECT"}}, "required": ["event_id", "user"]}}, {"name": "travel_time", "description": "Estimate travel minutes", "parameters": {"type": "OBJECT", "properties": {"event_a_id": {"type": "STRING"}, "event_b_id": {"type": "STRING"}}, "required": ["event_a_id", "event_b_id"]}}]
        for step in range(MAX_MODEL_STEPS):
            response = client.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"), contents=contents, config={"system_instruction": SYSTEM_PROMPT, "tools": [{"function_declarations": declarations}]})
            trace.append({"type": "model_step", "step": step + 1, "summary": "model response received"}); calls = getattr(response, "function_calls", None) or []
            if calls:
                results = []
                for call in calls:
                    name, args = call.name, dict(call.args or {}); fn = {"search_events": search_events, "check_eligibility": check_eligibility, "travel_time": travel_time}.get(name)
                    if fn: results.append({"name": name, "result": _tool(trace, name, fn, **args)})
                contents = contents + "\nTool results (use only these known events): " + json.dumps(results, default=str); continue
            text = (getattr(response, "text", "") or "").strip()
            if text.startswith("```"):
                text = text.strip("`")
                text = text.removeprefix("json").strip()
            parsed = json.loads(text)
            if not isinstance(parsed, dict) or not isinstance(parsed.get("itinerary"), list):
                return None
            ids = [x if isinstance(x, str) else x.get("id") for x in parsed["itinerary"]]
            ids = [x for x in ids if x]
            violations = validate_itinerary(ids, user)
            trace.append({"type": "validation", "event_ids": ids, "violations": violations})
            if not violations:
                return parsed
            contents = contents + "\nPython validation violations: " + json.dumps(violations) + "\nRevise the itinerary using tools; stop only when violations are empty."
    except Exception as exc: trace.append({"type": "model_error", "summary": str(exc)})
    return None

def _finish(user: dict[str, Any], candidate: dict[str, Any], trace: list[dict[str, Any]], alternatives: list[dict[str, str]] | None = None) -> dict[str, Any]:
    ids = [x if isinstance(x, str) else x.get("id") for x in candidate.get("itinerary", [])]; ids = [x for x in ids if x]; violations = validate_itinerary(ids, user); trace.append({"type": "validation", "event_ids": ids, "violations": violations})
    if violations:
        ids, fallback = _greedy(user, trace); alternatives = (alternatives or []) + fallback; violations = validate_itinerary(ids, user); trace.append({"type": "validation", "event_ids": ids, "violations": violations})
    return {"itinerary": [i for i in ids if i in _events()], "explanation": candidate.get("explanation", "Selected eligible, available events that fit the constraints."), "alternatives": alternatives or candidate.get("alternatives", []), "trace": trace}

def plan(user: dict[str, Any], request_text: str) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []; user = _updated_user(user or {}, request_text or ""); model = _model_plan(user, request_text, trace)
    if model: return _finish(user, model, trace)
    ids, alternatives = _greedy(user, trace); return _finish(user, {"itinerary": ids}, trace, alternatives)

def replan(user: dict[str, Any], current_plan: dict[str, Any], change_text: str) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    updated = _updated_user(user or {}, change_text or "")
    known = _events()
    old = [x if isinstance(x, str) else x.get("id") for x in current_plan.get("itinerary", [])]
    cancelled = _cancelled(change_text, known)
    retained = [event_id for event_id in old if event_id in known and event_id not in cancelled]
    retained = [event_id for event_id in retained if not validate_itinerary([event_id], updated)]
    trace.append({"type": "replan", "summary": "Retained existing events that still satisfy the updated request.", "event_ids": retained})
    additions, alternatives = _greedy(updated, trace, excluded=cancelled | set(retained))
    ids = retained + additions
    violations = validate_itinerary(ids, updated)
    if violations:
        trace.append({"type": "validation", "event_ids": ids, "violations": violations})
        ids, alternatives = _greedy(updated, trace, excluded=cancelled)
    dropped = [i for i in old if i not in ids]
    added = [i for i in ids if i not in old]
    result = _finish(updated, {"itinerary": ids, "explanation": "Updated the existing itinerary for the requested change.", "alternatives": alternatives}, trace, alternatives)
    result["changes"] = {"dropped": [{"event_id": i, "why": "Cancelled or no longer fits the updated constraints."} for i in dropped], "added": [{"event_id": i, "why": "Eligible replacement that fits the updated constraints."} for i in added]}
    return result
