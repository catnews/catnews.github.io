#!/usr/bin/env python3
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
import os

ARXIV_API = "http://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"

SEARCH_KEYWORDS = [
    "Linux kernel networking",
    "Linux network stack",
    "eBPF networking",
    "XDP eXpress Data Path",
    "Linux TCP/IP stack optimization",
]

MIN_YEAR = 2020
MAX_RESULTS_PER_SOURCE = 20


def fetch_arxiv_papers(query, max_results=10):
    papers = []
    try:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
        
        req = urllib.request.Request(url, headers={"User-Agent": "CatNews/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read().decode("utf-8")
        
        root = ET.fromstring(data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
            summary = entry.find("atom:summary", ns).text.strip().replace("\n", " ")[:300]
            url = entry.find("atom:id", ns).text
            published = entry.find("atom:published", ns).text
            year = int(published[:4])
            
            if year >= MIN_YEAR:
                papers.append({
                    "title": title,
                    "url": url,
                    "summary": summary + "...",
                    "source": "arxiv",
                    "year": year,
                })
    except Exception as e:
        print(f"arXiv fetch error: {e}")
    
    return papers


def fetch_semantic_scholar_papers(query, max_results=10):
    papers = []
    try:
        params = {
            "query": query,
            "limit": max_results,
            "year": f"{MIN_YEAR}-",
            "fields": "title,url,abstract,year",
        }
        url = f"{SEMANTIC_SCHOLAR_API}?{urllib.parse.urlencode(params)}"
        
        req = urllib.request.Request(url, headers={"User-Agent": "CatNews/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        for item in data.get("data", []):
            title = item.get("title", "")
            abstract = item.get("abstract", "") or "无摘要"
            url = item.get("url", "")
            year = item.get("year", 0)
            
            if title and url and year >= MIN_YEAR:
                summary = abstract[:300] + "..." if len(abstract) > 300 else abstract
                papers.append({
                    "title": title,
                    "url": url,
                    "summary": summary,
                    "source": "Semantic Scholar",
                    "year": year,
                })
    except Exception as e:
        print(f"Semantic Scholar fetch error: {e}")
    
    return papers


def deduplicate_papers(papers):
    seen = set()
    unique = []
    for p in papers:
        key = p["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def main():
    print("Starting paper fetch...")
    all_papers = []
    
    for keyword in SEARCH_KEYWORDS:
        print(f"Fetching: {keyword}")
        all_papers.extend(fetch_arxiv_papers(keyword, MAX_RESULTS_PER_SOURCE // 2))
        all_papers.extend(fetch_semantic_scholar_papers(keyword, MAX_RESULTS_PER_SOURCE // 2))
    
    all_papers = deduplicate_papers(all_papers)
    all_papers.sort(key=lambda x: x.get("year", 0), reverse=True)
    all_papers = all_papers[:MAX_RESULTS_PER_SOURCE]
    
    for p in all_papers:
        del p["year"]
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    output = {
        "date": today,
        "categories": {
            "papers": all_papers
        }
    }
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    docs_dir = os.path.join(script_dir, "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    output_path = os.path.join(docs_dir, f"{today}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"Saved {len(all_papers)} papers to {output_path}")


if __name__ == "__main__":
    main()