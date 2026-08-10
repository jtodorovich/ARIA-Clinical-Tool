import os
import json
import re
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic()

MODEL = "claude-sonnet-5"
VALID_INTENTS = {"treatment_recommendation", "literature_lookup", "general_question"}


def _extract_text(response) -> str:
    """Concatenate all text blocks from a model response."""
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()


def _extract_json(text: str) -> dict:
    """Best-effort recovery of a JSON object from a model reply."""
    if not text or not text.strip():
        raise ValueError("empty response")
    t = text.strip()
    # remove ```json ... ``` fences if present
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t).strip()
    # 1) try the whole thing
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # 2) try the span from the first { to the last }
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(t[start:end + 1])
    raise ValueError("no JSON object found in response")


def _normalize(data: dict) -> dict:
    """Coerce the parsed data into the exact shape the app expects."""
    out = {}

    dx = data.get("diagnosis")
    out["diagnosis"] = dx.strip() if isinstance(dx, str) and dx.strip() else None

    sym = data.get("symptoms")
    if isinstance(sym, list):
        out["symptoms"] = [str(s).strip() for s in sym if str(s).strip()]
    elif isinstance(sym, str) and sym.strip():
        out["symptoms"] = [p.strip() for p in re.split(r"[;,]", sym) if p.strip()]
    else:
        out["symptoms"] = []

    th = data.get("treatment_history")
    out["treatment_history"] = th.strip() if isinstance(th, str) and th.strip() else None

    qi = data.get("query_intent")
    out["query_intent"] = qi if qi in VALID_INTENTS else "general_question"

    return out


def parse_clinician_note(raw_input: str, max_attempts: int = 3) -> dict:
    """
    Send a clinician's free-text note to Claude and return structured data.
    Robust to minor formatting variation in the model's reply; retries a few
    times before giving up, and always returns a dict.
    """
    if not raw_input or not raw_input.strip():
        return {"error": "Please enter a note before I read it.", "raw_response": ""}

    prompt = f"""You are a clinical intake assistant. Extract structured information from the clinician note below.

Return ONLY a single valid JSON object, with exactly these fields:
- "diagnosis": string, or null if not mentioned
- "symptoms": list of strings (use an empty list if none are mentioned)
- "treatment_history": string, or null if not mentioned
- "query_intent": one of "treatment_recommendation", "literature_lookup", "general_question"

Do not include any explanation, markdown, or code fences — only the JSON object.

Clinician note:
<note>
{raw_input}
</note>"""

    last_raw, last_err = "", None
    for _ in range(max_attempts):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system="You extract structured clinical data and reply with a single valid JSON object and nothing else.",
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": "{"},  # prefill biases a JSON-only reply
                ],
            )
        except Exception as e:  # transient API/network error — try again
            last_err = f"API error: {e}"
            continue

        text = _extract_text(response)
        last_raw = text

        # Try the reply as-is first (handles a full object, fences, or stray
        # chatter); then, if needed, restore the prefilled leading brace.
        candidates = [text]
        if text and not text.lstrip().startswith("{"):
            candidates.append("{" + text)

        parsed = None
        for cand in candidates:
            try:
                parsed = _extract_json(cand)
                break
            except Exception as e:
                last_err = f"parse error: {e}"

        if isinstance(parsed, dict):
            return _normalize(parsed)

    return {
        "error": "I had trouble reading that note. Please try again, or simplify the note slightly and resubmit.",
        "raw_response": last_raw or (last_err or ""),
    }


if __name__ == "__main__":
    test_note = ("Patient presents with lower back pain and reduced range of motion. "
                 "History of physical therapy for 6 weeks with minimal improvement. "
                 "Looking for alternative treatment options.")
    print(json.dumps(parse_clinician_note(test_note), indent=2))
