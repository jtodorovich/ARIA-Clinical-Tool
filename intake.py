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


def _clean_reason(err: str) -> str:
    """Short, non-sensitive hint for the UI so failures are diagnosable."""
    if not err:
        return "no response"
    err = str(err)
    # never surface anything that could be a secret
    err = re.sub(r"(?i)(api[-_ ]?key|authorization|bearer|sk-[A-Za-z0-9\-_]+)", "[redacted]", err)
    return err[:200]


def parse_clinician_note(raw_input: str, max_attempts: int = 3) -> dict:
    """
    Send a clinician's free-text note to Claude and return structured data.
    Uses the proven call shape, with a higher token budget, automatic retries,
    flexible JSON recovery, and field normalization. Always returns a dict.
    """
    if not raw_input or not raw_input.strip():
        return {"error": "Please enter a note before I read it.", "raw_response": ""}

    prompt = f"""You are a clinical intake assistant. Extract structured information from the clinician note below.

Return ONLY a single valid JSON object, with exactly these fields:
- "diagnosis": string, or null if not mentioned
- "symptoms": list of strings (use an empty list if none are mentioned)
- "treatment_history": string, or null if not mentioned
- "query_intent": one of "treatment_recommendation", "literature_lookup", "general_question"

Do not include any explanation or extra text. Return only the JSON object.

Clinician note:
\"\"\"{raw_input}\"\"\""""

    last_raw, last_err = "", None
    for _ in range(max_attempts):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:  # transient/API error — try again
            last_err = f"API error: {type(e).__name__}: {e}"
            continue

        text = _extract_text(response)
        last_raw = text
        try:
            data = _extract_json(text)
            if isinstance(data, dict):
                return _normalize(data)
            last_err = "the response was not a JSON object"
        except Exception as e:
            last_err = f"parse error: {e}"

    return {
        "error": ("I had trouble reading that note. Please try again, or simplify it "
                  "slightly and resubmit.  (Details: " + _clean_reason(last_err) + ")"),
        "raw_response": last_raw,
    }


if __name__ == "__main__":
    test_note = ("Patient presents with lower back pain and reduced range of motion. "
                 "History of physical therapy for 6 weeks with minimal improvement. "
                 "Looking for alternative treatment options.")
    print(json.dumps(parse_clinician_note(test_note), indent=2))
