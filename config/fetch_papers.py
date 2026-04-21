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
MINIMAX_API = "https://api.minimax.chat/v1/text/chatcompletion_v2"

SEARCH_KEYWORDS = [
    "Linux kernel network stack",
    "eBPF XDP packet processing",
    "Linux TCP IP implementation",
    "Linux netfilter nftables",
    "Linux network driver",
    "Linux kernel bypass networking",
    "Linux virtio vhost network",
    "Linux socket performance",
]

MIN_YEAR = 2020
MAX_RESULTS = 10
MAX_CANDIDATES = 30

SYSTEM_PROMPT = """你是一个专业的论文筛选助手。你的任务是：
1. 判断论文是否与 Linux 内核网络子系统直接相关
2. 为相关论文生成高质量中文总结（150-300字）
3. 提取合适的特性标签
4. 估算阅读时长

Linux 内核网络相关主题包括：
- Linux TCP/IP 协议栈实现与优化
- Linux Socket API 与性能
- eBPF/XDP 数据包处理
- Netfilter/nftables 防火墙
- Kernel Bypass (DPDK)
- Virtio/vHost 虚拟化网络
- Linux 网络驱动开发
- Linux 路由、网桥、包处理

排除以下内容：
- 通用网络协议研究（不涉及 Linux 内核）
- 纯应用层网络编程
- 其他操作系统的网络实现
- 与 Linux 内核网络无关的 eBPF 应用"""

def call_minimax(prompt):
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        print("Warning: MINIMAX_API_KEY not set, using fallback")
        return None
    
    try:
        payload = {
            "model": "abab6.5s-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 500
        }
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            MINIMAX_API,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )
        
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        print(f"MiniMax API error: {e}")
        return None

def analyze_paper_with_llm(title, abstract):
    prompt = f"""请分析以下论文：

标题：{title}
摘要：{abstract[:500]}

请回答以下问题（JSON格式）：
1. relevance: 这篇论文是否与 Linux 内核网络子系统直接相关？返回 "high", "medium", "low" 或 "none"
2. summary: 如果相关，生成150-300字的中文总结，说明论文的核心内容、技术方案、对Linux内核的贡献
3. tags: 提取2-4个特性标签，可选：eBPF, XDP, 旁路, TCP/IP, Socket, Netfilter, 路由, 网桥, 驱动, 包处理, 虚拟化, 性能
4. readingTime: 估算阅读时长（分钟，基于内容深度）

返回格式：
{{"relevance": "...", "summary": "...", "tags": [...], "readingTime": ...}}"""
    
    response = call_minimax(prompt)
    if not response:
        return None
    
    try:
        json_match = re.search(r'\{[^{}]+\}', response)
        if json_match:
            return json.loads(json_match.group())
    except:
        pass
    return None

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
            title_elem = entry.find("atom:title", ns)
            summary_elem = entry.find("atom:summary", ns)
            id_elem = entry.find("atom:id", ns)
            published_elem = entry.find("atom:published", ns)
            
            if not all([title_elem is not None, summary_elem is not None, 
                        id_elem is not None, published_elem is not None]):
                continue
            
            title = title_elem.text.strip().replace("\n", " ") if title_elem.text else ""
            summary = summary_elem.text.strip().replace("\n", " ") if summary_elem.text else ""
            url_val = id_elem.text if id_elem.text else ""
            year = int(published_elem.text[:4]) if published_elem.text else 0
            
            if year >= MIN_YEAR and title and summary:
                papers.append({
                    "title": title,
                    "url": url_val,
                    "abstract": summary,
                    "source": "arxiv",
                    "year": year
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
            abstract = item.get("abstract", "") or ""
            url_val = item.get("url", "")
            year = item.get("year", 0)
            
            if title and url_val and year >= MIN_YEAR:
                papers.append({
                    "title": title,
                    "url": url_val,
                    "abstract": abstract,
                    "source": "Semantic Scholar",
                    "year": year
                })
    except Exception as e:
        print(f"Semantic Scholar fetch error: {e}")
    
    return papers

def get_paper_hash(title):
    normalized = re.sub(r'[^\w]', '', title.lower())
    return hashlib.md5(normalized.encode()).hexdigest()

def load_existing_hashes(docs_dir):
    hashes = set()
    if not os.path.exists(docs_dir):
        return hashes
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
    print("Starting Linux kernel networking paper fetch with LLM analysis...")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    docs_dir = os.path.join(script_dir, "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    existing_hashes = load_existing_hashes(docs_dir)
    print(f"Loaded {len(existing_hashes)} existing paper hashes")
    
    candidates = []
    for keyword in SEARCH_KEYWORDS:
        print(f"Searching: {keyword}")
        candidates.extend(fetch_arxiv_papers(keyword, 8))
        candidates.extend(fetch_semantic_scholar_papers(keyword, 8))
    
    candidates = deduplicate_papers(candidates, existing_hashes)
    candidates = candidates[:MAX_CANDIDATES]
    
    print(f"Found {len(candidates)} candidates, analyzing with LLM...")
    
    selected_papers = []
    for i, paper in enumerate(candidates):
        print(f"Analyzing [{i+1}/{len(candidates)}]: {paper['title'][:50]}...")
        
        analysis = analyze_paper_with_llm(paper['title'], paper['abstract'])
        
        if analysis and analysis.get('relevance') in ['high', 'medium']:
            selected_papers.append({
                "title": paper['title'],
                "url": paper['url'],
                "summary": analysis.get('summary', ''),
                "summary_en": paper['abstract'][:200] + "...",
                "source": paper['source'],
                "tags": analysis.get('tags', []),
                "readingTime": analysis.get('readingTime', 5),
                "relevance": analysis.get('relevance')
            })
            print(f"  -> Selected (relevance: {analysis.get('relevance')})")
        
        if len(selected_papers) >= MAX_RESULTS:
            break
    
    tag_counts = count_tags(selected_papers)
    
    print(f"Selected {len(selected_papers)} relevant papers")
    
    beijing_now = datetime.now(timezone.utc) + timedelta(hours=8)
    today = beijing_now.strftime("%Y-%m-%d")
    
    output = {
        "date": today,
        "categories": {
            "papers": selected_papers
        },
        "tagStats": tag_counts
    }
    
    output_path = os.path.join(docs_dir, f"{today}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"Saved to {output_path}")

if __name__ == "__main__":
    main()