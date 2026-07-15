import os
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()
NCBI_API_KEY = os.getenv("NCBI_API_KEY")

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def build_search_query(parsed_entities: dict) -> str:
    """
    Turns structured intake data into a PubMed search query.
    """
    terms = []
    if parsed_entities.get("diagnosis"):
        terms.append(parsed_entities["diagnosis"])
    for symptom in parsed_entities.get("symptoms", []):
        terms.append(symptom)
    return " AND ".join(terms) if terms else "clinical treatment"


def search_pubmed(query: str, max_results: int = 5) -> list:
    """
    Searches PubMed and returns a list of article IDs (PMIDs).
    """
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
        "api_key": NCBI_API_KEY,
    }
    response = requests.get(ESEARCH_URL, params=params)
    response.raise_for_status()
    data = response.json()
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_article_details(pmids: list) -> list:
    """
    Given a list of PMIDs, fetches titles and abstracts.
    """
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "api_key": NCBI_API_KEY,
    }
    response = requests.get(EFETCH_URL, params=params)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    articles = []

    for article in root.findall(".//PubmedArticle"):
        pmid_elem = article.find(".//PMID")
        title_elem = article.find(".//ArticleTitle")
        abstract_elem = article.find(".//AbstractText")

        pmid = pmid_elem.text if pmid_elem is not None else "unknown"
        title = title_elem.text if title_elem is not None else "No title available"
        abstract = abstract_elem.text if abstract_elem is not None else "No abstract available"

        articles.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
        })

    return articles


def retrieve_literature(parsed_entities: dict, max_results: int = 5) -> dict:
    """
    Main entry point: takes intake output, returns relevant PubMed sources.
    """
    query = build_search_query(parsed_entities)
    pmids = search_pubmed(query, max_results)
    articles = fetch_article_details(pmids)

    return {
        "query_used": query,
        "sources": articles,
    }


if __name__ == "__main__":
    import json
    test_entities = {
        "diagnosis": "osteoarthritis knee",
        "symptoms": ["joint pain", "stiffness"],
    }
    result = retrieve_literature(test_entities, max_results=3)
    print(json.dumps(result, indent=2))
