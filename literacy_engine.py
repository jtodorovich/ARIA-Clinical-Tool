import os
import json
import re
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic()

TIER_DESCRIPTIONS = {
    1: "Tier 1 - Confirmation & Context: Confirm the diagnosis is consistent with the evidence, present the most relevant facts from the note, and cite supporting literature. Minimal interpretation. Build trust through accuracy and clarity, not depth. Do not end with a comprehension question, this tier is about fast confirmation.",
    2: "Tier 2 - Exploration & Options: Explain what the current research actually shows, not just that it exists. Lay out treatment options with tradeoffs. Frame this as a decision the clinician is making, with ARIA as an advisor, not a verdict. End your response with one short, specific comprehension-check question that invites the clinician to reason through a key tradeoff, in the spirit of a mentor checking understanding, not testing them.",
    3: "Tier 3 - Deep Teaching: Give the high-level picture plus the underlying reasoning. Explain why the evidence points this way, what is still debated, and how this case fits into broader patterns. The goal is growing the clinician's own judgment, like a mentor teaching a skill, not just delivering an answer. End your response with one thoughtful comprehension-check question that invites the clinician to apply or extend the reasoning you just gave.",
}

MENTOR_PERSONA = (
    "You are ARIA, a clinical decision support mentor. Your tone is calm, "
    "precise, and encouraging, like a trusted senior colleague who wants "
    "the clinician to grow, not just get an answer. You are direct and "
    "evidence-based, never vague or falsely reassuring. When a clinician "
    "responds to one of your questions, acknowledge their reasoning "
    "specifically before adding anything new, a good mentor listens first."
)


def extract_text(response) -> str:
    """
    Safely pulls the text content out of a Claude response, skipping
    any 'thinking' blocks that may come first.
    """
    for block in response.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def infer_tier_from_note(raw_note: str) -> tuple:
    """
    Uses Claude to estimate an appropriate tier based on the clinician's
    own language and apparent comfort level with data/research in their note.
    Returns (tier: int, rationale: str).
    """
    prompt = f"""Read this clinician's note and estimate which of three support tiers best fits how they'd want information presented, based on the clinical/analytical language they used.

Tier 1: prefers quick confirmation and key facts, minimal interpretation
Tier 2: comfortable exploring research findings and weighing treatment options
Tier 3: wants deep explanation, underlying reasoning, and teaching

Clinician note:
\"\"\"{raw_note}\"\"\"

Return ONLY valid JSON with exactly these fields:
- "tier": 1, 2, or 3
- "rationale": one short sentence explaining why"""

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    text = extract_text(response)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)

    try:
        result = json.loads(text)
        return int(result.get("tier", 2)), result.get("rationale", "Default tier applied.")
    except (json.JSONDecodeError, ValueError):
        return 2, "Could not confidently infer tier; defaulted to Tier 2."


def generate_response(parsed_entities: dict, literature: dict, raw_note: str, tier: int = None) -> dict:
    """
    Main entry point for the FIRST response in a conversation.
    If tier is None, infers it from the note.
    """
    rationale = "Selected directly by clinician."
    if tier is None:
        tier, rationale = infer_tier_from_note(raw_note)

    tier = max(1, min(3, tier))
    tier_instructions = TIER_DESCRIPTIONS[tier]

    sources_text = "\n\n".join(
        f"- {s['title']} (PMID {s['pmid']}): {s['abstract']}"
        for s in literature.get("sources", [])
    )

    prompt = f"""{MENTOR_PERSONA}

Calibration for this response:
{tier_instructions}

Structured clinical data:
{json.dumps(parsed_entities, indent=2)}

Supporting literature:
{sources_text if sources_text else "No literature retrieved."}

Write your response to the clinician now, following the tier calibration above."""

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    return {
        "tier_used": tier,
        "tier_rationale": rationale,
        "response_text": extract_text(response),
    }


def continue_conversation(conversation_history: list, tier: int) -> str:
    """
    Handles a follow-up turn. conversation_history is a list of
    {"role": "user"|"assistant", "content": str} dicts representing
    the conversation so far, ending with the clinician's newest message.
    """
    tier_instructions = TIER_DESCRIPTIONS[tier]
    system_prompt = f"{MENTOR_PERSONA}\n\nCalibration for this conversation:\n{tier_instructions}"

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1000,
        system=system_prompt,
        messages=conversation_history,
    )

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
    test_note = "I'd like to explore next steps for this knee OA patient given the research on injection durability."

    result = generate_response(test_entities, test_literature, test_note, tier=None)
    print(json.dumps(result, indent=2))
