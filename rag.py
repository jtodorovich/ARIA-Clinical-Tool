import os
import re
import json
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from anthropic import Anthropic, APIError, APIConnectionError, APITimeoutError, RateLimitError

load_dotenv()
client = Anthropic()
NCBI_API_KEY = os.getenv("NCBI_API_KEY")

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def extract_text(response) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def build_search_query(parsed_entities: dict) -> str:
    terms = []
    if parsed_entities.get("diagnosis"):
        terms.append(parsed_entities["diagnosis"])
    for symptom in parsed_entities.get("symptoms", []):
        terms.append(symptom)
    return " AND ".join(terms) if terms else "clinical treatment"


def build_smart_query(raw_note: str, parsed_entities: dict, clarifications: list = None) -> dict:
    """
    Uses Claude to construct a properly-formed PubMed search query.
    Returns {"query": str, "rationale": str}. If it falls back to the
    simple query, the rationale will say exactly why.
    """
    clarifications_text = ""
    if clarifications:
        clarifications_text = "\n\nAdditional context from the clinician:\n" + "\n".join(
            f"Q: {c['question']}\nA: {c['answer']}" for c in clarifications
        )

    prompt = f"""You are helping construct an effective PubMed search query for a clinical question.

Clinical note:
\"\"\"{raw_note}\"\"\"

Extracted data:
{json.dumps(parsed_entities, indent=2)}
{clarifications_text}

Build a PubMed search query using proper syntax: use OR to group synonyms or related terms within one concept, and AND between distinct concepts. Use standard medical terminology as it would appear in PubMed, not necessarily the clinician's exact wording.

Return ONLY valid JSON with exactly these fields:
- "query": the PubMed search query string, ready to use
- "rationale": one or two short sentences explaining what concepts you searched for and why"""

    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
    except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as e:
        return {
            "query": build_search_query(parsed_entities),
            "rationale": f"Used a simpler search because ARIA could not reach Claude to build an optimized query ({type(e).__name__}).",
        }

    text = extract_text(response)
    if not text:
        return {
            "query": build_search_query(parsed_entities),
            "rationale": "Used a simpler search because Claude's response did not include usable text (possibly cut off).",
        }

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return {
            "query": build_search_query(parsed_entities),
            "rationale": f"Used a simpler search because the optimized query could not be parsed ({e}).",
        }

    query = result.get("query")
    if not query:
        return {
            "query": build_search_query(parsed_entities),
            "rationale": "Used a simpler search because no query was returned.",
        }

    return {
        "query": query,
        "rationale": result.get("rationale", "No rationale provided."),
    }


def generate_clarifying_question(raw_note: str, parsed_entities: dict, clarifications: list) -> str:
    clarifications_text = ""
    if clarifications:
        clarifications_text = "\n\nAlready asked:\n" + "\n".join(
            f"Q: {c['question']}\nA: {c['answer']}" for c in clarifications
        )

    prompt = f"""A PubMed literature search for this clinical case has not returned useful results.

Clinical note:
\"\"\"{raw_note}\"\"\"

Extracted data:
{json.dumps(parsed_entities, indent=2)}
{clarifications_text}

Ask the clinician ONE short, specific question that would help narrow down or clarify the clinical question, so a better literature search can be built. For example, ask about a specific mechanism, patient population, comparison of interest, or more precise terminology. Do not repeat a question already asked.

Return ONLY the question text, nothing else."""

    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        return extract_text(response) or "Could you provide more specific clinical detail so I can search more precisely?"
    except (RateLimitError, APITimeoutError, APIConnectionError, APIError):
        return "Could you provide a bit more clinical detail (for example, a specific treatment you're considering, or the patient population) so I can search more precisely?"


def search_pubmed(query: str, max_results: int = 5) -> list:
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
        "api_key": NCBI_API_KEY,
    }
    try:
        response = requests.get(ESEARCH_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("esearchresult", {}).get("idlist", [])
    except (requests.RequestException, ValueError):
        return []


def fetch_article_details(pmids: list) -> list:
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "api_key": NCBI_API_KEY,
    }
    try:
        response = requests.get(EFETCH_URL, params=params, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError):
        return []

    articles = []
    for article in root.findall(".//PubmedArticle"):
        pmid_elem = article.find(".//PMID")
        title_elem = article.find(".//ArticleTitle")
        abstract_elem = article.find(".//AbstractText")

        articles.append({
            "pmid": pmid_elem.text if pmid_elem is not None else "unknown",
            "title": title_elem.text if title_elem is not None else "No title available",
            "abstract": abstract_elem.text if abstract_elem is not None else "No abstract available",
        })

    return articles


def retrieve_literature_smart(raw_note: str, parsed_entities: dict, clarifications: list = None, max_results: int = 5) -> dict:
    if parsed_entities.get("error"):
        return {
            "query_used": None,
            "rationale": None,
            "sources": [],
            "note": "Skipped literature search because the clinical note could not be parsed.",
        }

    query_info = build_smart_query(raw_note, parsed_entities, clarifications)
    query = query_info["query"]
    pmids = search_pubmed(query, max_results)
    articles = fetch_article_details(pmids)

    result = {
        "query_used": query,
        "rationale": query_info["rationale"],
        "sources": articles,
    }
    if not articles:
        result["note"] = "No matching literature was found for this query."

    return result


if __name__ == "__main__":
    test_note = "Patient with knee OA, failed conservative therapy. Considering next steps given research on injection durability."
    test_entities = {
        "diagnosis": "osteoarthritis knee",
        "symptoms": ["joint pain", "stiffness"],
    }
    result = retrieve_literature_smart(test_note, test_entities, max_results=5)
    print(json.dumps(result, indent=2))
