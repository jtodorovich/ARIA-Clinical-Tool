import os
import json
import re
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic()

def parse_clinician_note(raw_input: str) -> dict:
    """
    Sends a clinician's free-text note to Claude and returns
    structured data extracted from it.
    """
    prompt = f"""You are a clinical intake assistant. Extract structured information from the clinician note below.

Return ONLY valid JSON, with exactly these fields:
- "diagnosis": string or null if not mentioned
- "symptoms": list of strings (empty list if none mentioned)
- "treatment_history": string or null if not mentioned
- "query_intent": one of "treatment_recommendation", "literature_lookup", "general_question"

Clinician note:
\"\"\"{raw_input}\"\"\"

Return ONLY the JSON object, no other text."""

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    result_text = response.content[0].text.strip()

    # Strip markdown code fences if Claude added them
    result_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", result_text.strip())

    try:
        return json.loads(result_text)
    except json.JSONDecodeError:
        return {
            "error": "Could not parse Claude's response as JSON",
            "raw_response": result_text
        }


if __name__ == "__main__":
    test_note = "Patient presents with lower back pain and reduced range of motion. History of physical therapy for 6 weeks with minimal improvement. Looking for alternative treatment options."
    result = parse_clinician_note(test_note)
    print(json.dumps(result, indent=2))
