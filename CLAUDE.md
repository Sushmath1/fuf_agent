# FUF Agent

FUF Agent is a Phase 1 Python agentic AI application for planning a personal event itinerary in a chosen Chennai area.

## Stack and data

- Python 3.11
- Streamlit UI
- Gemini function calling via the `google-genai` SDK
- Gemini model selected from `GEMINI_MODEL` in `.env`
- Event data is stored in `data/events.json`

## Phase 1 scope

Phase 1 uses deterministic tools and data only; the LLM integration is intentionally not implemented yet. The deterministic tools provide event search, travel-time estimates, eligibility checks, and itinerary validation.

## Core principle

**The LLM chooses and explains; Python code validates.**

Future Gemini function-calling orchestration should let the model select useful tools and explain itinerary choices, while Python remains the source of truth for constraints such as schedules, travel gaps, budget, eligibility, registration status, capacity, and the user's free window.
