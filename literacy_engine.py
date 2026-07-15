import os
import json
import re
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic()

TIER_DESCRIPTIONS = {
    1: "Tier 1 - Confirmation & Context: Confirm the diagnosis is consistent with the evidence, present the most relevant facts from the note, and cite supporting literature. Minimal interpretation. Build trust through accuracy and clarity, not depth.",
    2: "Tier 2 - Exploration & Options: Explain what the current research actually shows, not just that it exists. Lay out treatment options with tradeoffs. Frame this as a decision the clinician is making, with ARIA as an advisor, not a verdict.",
    3: "Tier 3 - Deep Teaching: Give the high-level picture plus the underlying reasoning. Explain why the evidence points this way, what is still debated, and how this case fits into broader patterns. The goal is growing the clinician's own judgment, like a mentor teaching a skill, not just delivering an answer.",
}

MENTOR_PERSONA = (
    "You are ARIA, a clinical decision support mentor. Your tone is calm, "
    "precise, and encouraging, like a trusted senior colleague who wants "
    "the clinician to grow, not just get an answer. You are direct and "
    "evidence-based, never vague or falsely reassuring."
)


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
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)

    try:
        result = json.loads(text)
        return int(result.get("tier", 2)), result.get("rationale", "Default tier applied.")
    except (json.JSONDecodeError, ValueError):
        return 2, "Could not confidently infer tier; defaulted to Tier 2."


def generate_response(parsed_entities: dict, literature: dict, raw_note: str, tier: int = None) -> dict:
    """
    Main entry point. If tier is None, infers it from the note.
    Returns the final mentor-style response calibrated to that tier.
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
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    return {
        "tier_used": tier,
        "tier_rationale": rationale,
        "response_text": response.content[0].text.strip(),
    }


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
    test_note = "Patient with worsening knee OA, failed conservative management. What next?"

    result = generate_response(test_entities, test_literature, test_note, tier=None)
    print(json.dumps(result, indent=2))
