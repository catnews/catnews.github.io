#!/usr/bin/env python3
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import os
import hashlib
import re

ARXIV_API = "http://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"

SEARCH_KEYWORDS = [
    "Linux TCP IP stack",
    "Linux network stack implementation",
    "Linux socket implementation kernel",
    "Linux netfilter nftables",
    "Linux kernel packet processing",
    "Linux routing subsystem",
    "Linux bridge networking",
    "Linux eBPF XDP networking",
    "Linux network driver development",
    "Linux kernel bypass DPDK",
    "Linux virtio network",
    "Linux network performance optimization",
]

MIN_YEAR = 2020
MAX_RESULTS = 20

REQUIRED_KEYWORDS = [
    "linux", "kernel", "eBPF", "XDP", "bpf", "netfilter", 
    "iptables", "nftables", "tcp", "udp", "socket", "networking",
    "network stack", "dpdk", "bypass", "driver", "ethernet",
    "vlan", "bonding", "bridge", "routing", "packet",
]

TAG_MAP = {
    "eBPF": ["ebpf", "bpf", "extended bpf", "berkeley packet filter"],
    "XDP": ["xdp", "express data path"],
    "旁路": ["bypass", "kernel bypass", "dpdk", "user-space networking", "userspace"],
    "TCP/IP": ["tcp/ip", "tcp", "ip stack", "protocol stack", "tcp congestion"],
    "Socket": ["socket", "unix socket", "network socket", "socket api"],
    "Netfilter": ["netfilter", "iptables", "nftables", "nf_tables"],
    "路由": ["routing", "route", "forwarding", "routing table"],
    "网桥": ["bridge", "bridging", "linux bridge"],
    "驱动": ["driver", "nic driver", "ethernet driver", "network device driver"],
    "包处理": ["packet processing", "packet", "skb", "sk_buff"],
    "虚拟化": ["virtio", "vhost", "sriov", "virtual networking", "vm networking"],
    "性能": ["performance", "optimization", "latency", "throughput", "scaling"],
}


def translate_text(text):
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {"q": text[:500], "langpair": "en|zh"}
        req = urllib.request.Request(
            f"{url}?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": "CatNews/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("responseData", {}).get("translatedText", text)
    except Exception as e:
        print(f"Translation error: {e}")
        return text


def extract_tags(title, summary):
    text = (title + " " + summary).lower()
    tags = []
    for tag, keywords in TAG_MAP.items():
        for kw in keywords:
            if kw.lower() in text:
                if tag not in tags:
                    tags.append(tag)
                break
    return tags[:3]


def is_relevant_paper(title, summary):
    text = (title + " " + summary).lower()
    
    linux_keywords = ["linux", "kernel"]
    linux_found = any(kw in text for kw in linux_keywords)
    
    networking_core = [
        "network stack", "tcp/ip", "tcp", "udp", "ip stack", 
        "socket", "netfilter", "iptables", "nftables",
        "packet processing", "skb", "routing", "bridge",
        "ebpf", "xdp", "bpf", "network driver",
        "ethernet", "virtio", "vhost", "dpdk",
        "network subsystem", "networking"
    ]
    network_found = any(kw in text for kw in networking_core)
    
    return linux_found and network_found


def fetch_arxiv_papers(query, max_results=5):
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
            title_elem = entry.find("atom:title", ns)
            summary_elem = entry.find("atom:summary", ns)
            id_elem = entry.find("atom:id", ns)
            published_elem = entry.find("atom:published", ns)
            
            if not all([title_elem, summary_elem, id_elem, published_elem]):
                continue
                
            title = title_elem.text.strip().replace("\n", " ")
            summary_orig = summary_elem.text.strip().replace("\n", " ")
            url_val = id_elem.text
            year = int(published_elem.text[:4])
            
            if year < MIN_YEAR:
                continue
            
            if not is_relevant_paper(title, summary_orig):
                continue
            
            summary_cn = translate_text(summary_orig[:200])
            if summary_cn == summary_orig[:200]:
                summary_cn = summary_orig[:200]
            
            tags = extract_tags(title, summary_orig)
            
            papers.append({
                "title": title,
                "url": url_val,
                "summary": summary_cn + "...",
                "summary_en": summary_orig[:200] + "...",
                "source": "arxiv",
                "tags": tags,
            })
    except Exception as e:
        print(f"arXiv fetch error: {e}")
    
    return papers


def fetch_semantic_scholar_papers(query, max_results=5):
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
            abstract = item.get("abstract", "") or ""
            url_val = item.get("url", "")
            year = item.get("year", 0)
            
            if not title or not url_val or year < MIN_YEAR:
                continue
            
            if not is_relevant_paper(title, abstract):
                continue
            
            summary_cn = translate_text(abstract[:200])
            if summary_cn == abstract[:200]:
                summary_cn = abstract[:200] if abstract else "暂无摘要"
            
            tags = extract_tags(title, abstract)
            
            papers.append({
                "title": title,
                "url": url_val,
                "summary": summary_cn + "..." if len(summary_cn) > 50 else summary_cn,
                "summary_en": abstract[:200] + "..." if abstract else "",
                "source": "Semantic Scholar",
                "tags": tags,
            })
    except Exception as e:
        print(f"Semantic Scholar fetch error: {e}")
    
    return papers


def get_paper_hash(title):
    normalized = re.sub(r'[^\w]', '', title.lower())
    return hashlib.md5(normalized.encode()).hexdigest()


def load_existing_hashes(docs_dir):
    hashes = set()
    for filename in os.listdir(docs_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(docs_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for paper in data.get('categories', {}).get('papers', []):
                        hashes.add(get_paper_hash(paper['title']))
            except:
                pass
    return hashes


def deduplicate_papers(papers, existing_hashes):
    seen = set()
    unique = []
    for p in papers:
        hash_val = get_paper_hash(p["title"])
        if hash_val not in seen and hash_val not in existing_hashes:
            seen.add(hash_val)
            unique.append(p)
    return unique


def count_tags(papers):
    tag_counts = {}
    for paper in papers:
        for tag in paper.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return tag_counts


def main():
    print("Starting Linux kernel networking paper fetch...")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    docs_dir = os.path.join(script_dir, "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    existing_hashes = load_existing_hashes(docs_dir)
    print(f"Loaded {len(existing_hashes)} existing paper hashes")
    
    all_papers = []
    
    for keyword in SEARCH_KEYWORDS:
        print(f"Searching: {keyword}")
        all_papers.extend(fetch_arxiv_papers(keyword, 5))
        all_papers.extend(fetch_semantic_scholar_papers(keyword, 5))
    
    all_papers = deduplicate_papers(all_papers, existing_hashes)
    all_papers = all_papers[:MAX_RESULTS]
    
    tag_counts = count_tags(all_papers)
    
    print(f"Found {len(all_papers)} new papers")
    
    beijing_now = datetime.now(timezone.utc) + timedelta(hours=8)
    today = beijing_now.strftime("%Y-%m-%d")
    
    output = {
        "date": today,
        "categories": {
            "papers": all_papers
        },
        "tagStats": tag_counts
    }
    
    output_path = os.path.join(docs_dir, f"{today}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()