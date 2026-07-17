import os
import json
import re
from dotenv import load_dotenv
from anthropic import Anthropic, APIError, APIConnectionError, APITimeoutError, RateLimitError

load_dotenv()
client = Anthropic()

TIER_DESCRIPTIONS = {
    1: """Tier 1 - Confirmation & Context: Confirm the diagnosis is consistent with the evidence, present the most relevant facts from the note, and cite supporting literature. Minimal interpretation.

Required ending: end with exactly ONE direct, specific question or explicit next-step offer that has a clear answer (for example, a yes/no choice, or a choice between two named options). Do NOT end with a vague, open-ended statement like "let me know if you have questions" or a summary with no actionable prompt.""",

    2: """Tier 2 - Exploration & Options: Explain what the current research actually shows, not just that it exists. Lay out treatment options with tradeoffs. Frame this as a decision the clinician is making, with ARIA as an advisor, not a verdict.

Required ending: end with exactly ONE direct, specific comprehension-check question that asks the clinician to reason through a named tradeoff or make a specific choice. The question must be answerable in one or two sentences, not open-ended musing. Do NOT end with a vague "let me know" statement.""",

    3: """Tier 3 - Deep Teaching: Give the high-level picture plus the underlying reasoning. Explain why the evidence points this way, what is still debated, and how this case fits into broader patterns. The goal is growing the clinician's own judgment.

Required ending: end with exactly ONE direct, specific teaching question that asks the clinician to apply or extend the reasoning just given to a concrete detail of this case. The question must be specific enough that the clinician knows exactly what to answer.""",
}

MENTOR_PERSONA = (
    "You are ARIA, a clinical decision support mentor. Your tone is calm, "
    "precise, and encouraging, like a trusted senior colleague who wants "
    "the clinician to grow, not just get an answer. You are direct and "
    "evidence-based, never vague or falsely reassuring.\n\n"
    "CRITICAL FORMAT RULE: every response you write must end with a line "
    "starting with exactly '**Question for you:**' followed by one specific, "
    "direct question or explicit choice. This is mandatory in every response, "
    "with no exceptions. Never end a response with only a summary, a 'bottom "
    "line', or a vague offer of help with no clear question attached.\n\n"
    "When a clinician responds to one of your questions, acknowledge their "
    "specific answer directly and explicitly before adding anything new, a "
    "good mentor listens first, then always close your reply the same way, "
    "with a new '**Question for you:**' line."
)


def extract_text(response) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def _friendly_api_error(e: Exception) -> str:
    if isinstance(e, RateLimitError):
        return "ARIA is receiving too many requests right now. Please wait a moment and try again."
    if isinstance(e, APITimeoutError):
        return "The request timed out. Please try again."
    if isinstance(e, APIConnectionError):
        return "Could not connect to Claude. Please check your internet connection and try again."
    return f"An unexpected error occurred: {e}"


def infer_tier_from_note(raw_note: str) -> tuple:
    prompt = f"""Read this clinician's note and estimate which of three support tiers best fits how they'd want information presented, based on the clinical/analytical language they used.

Tier 1: prefers quick confirmation and key facts, minimal interpretation
Tier 2: comfortable exploring research findings and weighing treatment options
Tier 3: wants deep explanation, underlying reasoning, and teaching

Clinician note:
\"\"\"{raw_note}\"\"\"

Return ONLY valid JSON with exactly these fields:
- "tier": 1, 2, or 3
- "rationale": one short sentence explaining why"""

    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
    except (RateLimitError, APITimeoutError, APIConnectionError, APIError):
        return 2, "Could not assess tier automatically; defaulted to Tier 2."

    text = extract_text(response)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)

    try:
        result = json.loads(text)
        return int(result.get("tier", 2)), result.get("rationale", "Default tier applied.")
    except (json.JSONDecodeError, ValueError):
        return 2, "Could not confidently infer tier; defaulted to Tier 2."


def generate_response(parsed_entities: dict, literature: dict, raw_note: str, tier: int = None) -> dict:
    if parsed_entities.get("error"):
        return {
            "tier_used": None,
            "tier_rationale": None,
            "response_text": "ARIA couldn't generate a response because the clinical note wasn't understood. Please rephrase the note with more specific clinical detail and try again.",
        }

    rationale = "Selected directly by clinician."
    if tier is None:
        tier, rationale = infer_tier_from_note(raw_note)

    tier = max(1, min(3, tier))
    tier_instructions = TIER_DESCRIPTIONS[tier]

    sources_text = "\n\n".join(
        f"- {s['title']} (PMID {s['pmid']}): {s['abstract']}"
        for s in literature.get("sources", [])
    )
    literature_note = literature.get("note", "")

    prompt = f"""{MENTOR_PERSONA}

Calibration for this response:
{tier_instructions}

Structured clinical data:
{json.dumps(parsed_entities, indent=2)}

Supporting literature:
{sources_text if sources_text else "No literature retrieved. " + literature_note}

Write your response to the clinician now, following the tier calibration above. If no literature was retrieved, rely on sound clinical reasoning and say so plainly rather than fabricating citations. Remember: end with a '**Question for you:**' line as instructed."""

    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
    except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as e:
        return {
            "tier_used": tier,
            "tier_rationale": rationale,
            "response_text": _friendly_api_error(e),
        }

    return {
        "tier_used": tier,
        "tier_rationale": rationale,
        "response_text": extract_text(response),
    }


def continue_conversation(conversation_history: list, tier: int) -> str:
    tier_instructions = TIER_DESCRIPTIONS.get(tier, TIER_DESCRIPTIONS[2])
    system_prompt = f"{MENTOR_PERSONA}\n\nCalibration for this conversation:\n{tier_instructions}"

    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1000,
            system=system_prompt,
            messages=conversation_history,
        )
    except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as e:
        return _friendly_api_error(e)

    return extract_text(response)


if __name__ == "__main__":
    test_entities = {
        "diagnosis": "osteoarthritis knee",
        "symptoms": ["joint pain", "stiffness"],
        "treatment_history": "NSAIDs, physical therapy, one corticosteroid injection",
        "query_intent": "treatment_recommendation",
    }
    test_literature = {
        "sources": [
            {"pmid": "39250809", "title": "Knee Osteoarthritis.",
             "abstract": "Knee osteoarthritis typically presents with joint pain exacerbated by use..."}
        ]
    }
    test_note = "Confirm this is OA and give me the key facts."

    result = generate_response(test_entities, test_literature, test_note, tier=1)
    print(json.dumps(result, indent=2))
