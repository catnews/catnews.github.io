#!/usr/bin/env python3
import json
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import os
import hashlib
import re
import time
import random

ARXIV_API = "http://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
MINIMAX_API = "https://api.minimaxi.com/v1/chat/completions"

REQUEST_DELAY_MIN = 3
REQUEST_DELAY_MAX = 5
LLM_DELAY_MIN = 3
LLM_DELAY_MAX = 5
ARXIV_DELAY = 3

SEARCH_KEYWORDS = [
    "Linux kernel network",
    "Linux eBPF networking",
    "Linux XDP data path",
    "Linux TCP IP kernel",
    "Linux socket performance",
    "Linux netfilter iptables",
    "Linux network driver",
    "Linux kernel bypass",
    "Linux packet processing",
    "Linux virtio network",
    "Linux network optimization",
    "Linux skb networking",
    "Linux netdev kernel",
    "Linux vhost networking",
    "Linux network namespace kernel",
    "Linux qdisc traffic control",
    "Linux container networking",
    "Linux CNI networking",
    "Linux Kubernetes networking",
    "Linux conntrack netfilter",
    "Linux network performance tuning",
    "Linux TCP performance optimization",
    "Linux AF_XDP performance",
    "Linux io_uring networking",
]

HOT_TOPIC_KEYWORDS = [
    "container",
    "containers",
    "kubernetes",
    "k8s",
    "cni",
    "pod",
    "network namespace",
    "netns",
    "veth",
    "ovs",
    "open v switch",
    "cilium",
    "service mesh",
    "conntrack",
    "netfilter",
    "iptables",
    "nftables",
    "performance",
    "latency",
    "throughput",
    "benchmark",
    "optimization",
    "qdisc",
    "xps",
    "rps",
    "rfs",
    "af_xdp",
    "io_uring",
    "busy poll",
]

DOMAIN_KEYWORDS = {
    "ebpf": "eBPF",
    "bpf": "eBPF",
    "xdp": "XDP",
    "tcp": "TCP/IP",
    "ip": "TCP/IP",
    "socket": "Socket",
    "netfilter": "Netfilter",
    "iptables": "Netfilter",
    "nftables": "Netfilter",
    "routing": "路由",
    "forwarding": "路由",
    "bridge": "网桥",
    "bridging": "网桥",
    "driver": "驱动",
    "nic": "驱动",
    "packet": "包处理",
    "skb": "包处理",
    "virtio": "虚拟化",
    "vhost": "虚拟化",
    "sriov": "虚拟化",
    "kernel bypass": "旁路",
    "dpdk": "旁路",
    "linux kernel": "Linux内核网络",
    "network": "网络优化",
    "container": "容器网络",
    "kubernetes": "容器网络",
    "k8s": "容器网络",
    "cni": "容器网络",
    "namespace": "容器网络",
    "netns": "容器网络",
    "veth": "容器网络",
    "ovs": "容器网络",
    "cilium": "容器网络",
    "service mesh": "容器网络",
    "conntrack": "Netfilter",
    "qdisc": "网络优化",
    "benchmark": "性能",
    "optimization": "性能",
    "af_xdp": "XDP",
    "io_uring": "性能",
    "latency": "性能",
    "throughput": "性能",
    "performance": "性能",
}

NEGATIVE_KEYWORDS = [
    "wireless sensor",
    "social network",
    "image network",
    "neural network",
    "blockchain",
    "5g application",
    "iot application",
]

HARD_EXCLUDE_KEYWORDS = [
    "malware",
    "ctf",
    "offensive cyber",
    "firmware vulnerability",
    "busybox",
    "supply chain security",
    "neural network",
    "llm benchmark",
    "image classification",
]

MIN_YEAR = 2020
MAX_PAPERS = 16
MAX_NEWS = 12
MAX_CANDIDATES = 80
MIN_PAPERS_TARGET = 12
MIN_NEWS_TARGET = 8

PAPER_PROMPT = """你是一个专业的论文筛选助手。分析论文是否与 Linux 内核网络子系统直接相关。

Linux 内核网络相关主题：TCP/IP协议栈、Socket API、eBPF/XDP、Netfilter/nftables、Kernel Bypass、Virtio/vHost、网络驱动、路由/网桥/包处理。
重点关注热点：容器网络（Kubernetes/CNI/netns/veth/OVS/Cilium）与 Linux 内核网络性能优化（延迟/吞吐/调度/benchmark）。

返回JSON格式：
{"relevance": "high/medium/low/none", "summary": "中文总结150-300字", "tags": ["3-4个最主要标签"], "readingTime": 分钟数}

注意：tags数组最多包含3-4个最重要的标签，不要过多。"""

NEWS_PROMPT = """你是一个技术资讯筛选助手。分析文章是否与 Linux 内核网络相关。

相关主题：网络性能测试、内核网络更新、驱动发布、网络子系统讨论等。
重点关注热点：容器网络（Kubernetes/CNI）和 Linux 网络性能提升。

返回JSON格式：
{"relevance": "high/medium/low/none", "summary": "中文总结100-200字", "tags": ["3-4个最主要标签"], "readingTime": 分钟数}

注意：tags数组最多包含3-4个最重要的标签，不要过多。"""

LWN_SUMMARY_PROMPT = """你是一个技术文章总结助手。请阅读LWN.net的文章内容，提取与Linux内核网络相关的重要信息。

返回JSON格式：
{"summary": "中文总结150-250字，突出关键技术和影响", "tags": ["3-4个最主要标签"], "readingTime": 分钟数}

注意：tags数组最多包含3-4个最重要的标签。"""

def random_delay(min_sec, max_sec):
    delay = random.uniform(min_sec, max_sec)
    print(f"  Waiting {delay:.1f}s...")
    time.sleep(delay)

def call_minimax(prompt, system_prompt, max_retries=3):
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        print("Warning: MINIMAX_API_KEY not set")
        return None
    
    for attempt in range(max_retries):
        try:
            payload = {
                "model": "MiniMax-M2.7",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
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
        
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait_time = 30 + attempt * 20
                print(f"  Rate limited (429), waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"MiniMax API HTTP error: {e.code} {e.reason}")
                return None
        except Exception as e:
            print(f"MiniMax API error: {e}")
            if attempt < max_retries - 1:
                time.sleep(10)
    
    return None

QUICK_FILTER_PROMPT = """你是论文筛选助手。快速判断文章是否与Linux内核网络子系统直接相关。

Linux内核网络：TCP/IP协议栈、Socket API、eBPF/XDP、Netfilter、Kernel Bypass、Virtio、网络驱动、路由/网桥。
优先关注：容器网络（Kubernetes/CNI/netns/veth）和网络性能优化（latency/throughput/qdisc/tc）。

严格标准：必须直接涉及Linux内核网络代码/实现，而非通用网络研究。

返回JSON：{"relevance": "high/medium/low/none"}"""

def quick_filter_relevance(title, abstract):
    prompt = f"""标题：{title}
摘要：{abstract[:600]}

判断相关性，返回JSON。"""
    
    response = call_minimax(prompt, QUICK_FILTER_PROMPT)
    if not response:
        return heuristic_relevance(title, abstract)
    
    try:
        json_match = re.search(r'\{[^{}]+\}', response)
        if json_match:
            result = json.loads(json_match.group())
            return result.get('relevance', 'none')
    except:
        pass

    return heuristic_relevance(title, abstract)

def keyword_hit_count(text):
    text_lower = (text or "").lower()
    hits = 0
    for keyword in DOMAIN_KEYWORDS.keys():
        if keyword in text_lower:
            hits += 1
    return hits

def heuristic_relevance(title, abstract):
    merged_text = f"{title} {abstract}".lower()
    if is_hard_excluded(merged_text):
        return "none"
    hit_count = keyword_hit_count(merged_text)
    penalty = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in merged_text)
    hot_score = hot_topic_score(merged_text)
    score = hit_count - penalty + hot_score

    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    if score >= 1:
        return "low"
    return "none"

def hot_topic_score(text):
    text_lower = (text or "").lower()
    hits = 0
    for keyword in HOT_TOPIC_KEYWORDS:
        if keyword in text_lower:
            hits += 1
    if hits >= 4:
        return 2
    if hits >= 2:
        return 1
    return 0

def is_hard_excluded(text):
    text_lower = (text or "").lower()
    return any(keyword in text_lower for keyword in HARD_EXCLUDE_KEYWORDS)

def prioritize_items(items, content_field="abstract"):
    def score(item):
        text = f"{item.get('title', '')} {item.get(content_field, '')}"
        return (
            hot_topic_score(text),
            keyword_hit_count(text),
            int(item.get("year", 0)),
        )

    return sorted(items, key=score, reverse=True)

def infer_tags(text, max_tags=4):
    text_lower = (text or "").lower()
    tags = []
    for keyword, tag in DOMAIN_KEYWORDS.items():
        if keyword in text_lower and tag not in tags:
            tags.append(tag)
        if len(tags) >= max_tags:
            break
    return tags

def fallback_summary(content, min_len=90):
    normalized = re.sub(r"\s+", " ", content or "").strip()
    if not normalized:
        return "暂无摘要，可打开原文查看与 Linux 内核网络相关的细节。"
    clipped = normalized[:220]
    if len(clipped) < min_len:
        return clipped
    return f"{clipped}..."

def analyze_item_with_llm(title, content, is_news=False):
    prompt = f"""标题：{title}
内容：{content[:400]}

请分析并返回JSON，tags最多3-4个。"""
    
    system_prompt = NEWS_PROMPT if is_news else PAPER_PROMPT
    response = call_minimax(prompt, system_prompt)
    
    if not response:
        inferred_relevance = heuristic_relevance(title, content)
        return {
            "relevance": inferred_relevance if inferred_relevance != "none" else "low",
            "summary": fallback_summary(content, min_len=80 if is_news else 120),
            "tags": infer_tags(f"{title} {content}"),
            "readingTime": 3 if is_news else 5,
        }
    
    try:
        json_match = re.search(r'\{[^{}]+\}', response)
        if json_match:
            result = json.loads(json_match.group())
            if 'tags' in result and len(result['tags']) > 4:
                result['tags'] = result['tags'][:4]
            return result
    except:
        pass

    inferred_relevance = heuristic_relevance(title, content)
    return {
        "relevance": inferred_relevance if inferred_relevance != "none" else "low",
        "summary": fallback_summary(content, min_len=80 if is_news else 120),
        "tags": infer_tags(f"{title} {content}"),
        "readingTime": 3 if is_news else 5,
    }

def fetch_arxiv_papers(query, max_results=8):
    papers = []
    for attempt in range(3):
        try:
            print(f"  Waiting {ARXIV_DELAY}s for arXiv...")
            time.sleep(ARXIV_DELAY)
            
            params = {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
            url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
            
            req = urllib.request.Request(url, headers={"User-Agent": "CatNews/2.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read().decode("utf-8")
            
            root = ET.fromstring(data)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            
            for entry in root.findall("atom:entry", ns):
                title_elem = entry.find("atom:title", ns)
                summary_elem = entry.find("atom:summary", ns)
                id_elem = entry.find("atom:id", ns)
                published_elem = entry.find("atom:published", ns)
                
                if (
                    title_elem is None
                    or summary_elem is None
                    or id_elem is None
                    or published_elem is None
                ):
                    continue
                
                title_text = title_elem.text or ""
                summary_text = summary_elem.text or ""
                id_text = id_elem.text or ""
                published_text = published_elem.text or ""

                title = title_text.strip().replace("\n", " ")
                summary = summary_text.strip().replace("\n", " ")
                url_val = id_text
                year = int(published_text[:4]) if len(published_text) >= 4 else 0
                
                if year >= MIN_YEAR and title and summary:
                    papers.append({
                        "title": title,
                        "url": url_val,
                        "abstract": summary,
                        "source": "arXiv",
                        "year": year
                    })
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 30 + attempt * 20
                print(f"  arXiv rate limited, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"arXiv HTTP error: {e.code}")
                break
        except Exception as e:
            print(f"arXiv fetch error: {e}")
            if attempt < 2:
                time.sleep(10)
            else:
                break
    
    return papers

def fetch_semantic_scholar_papers(query, max_results=8):
    papers = []
    try:
        random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        
        params = {
            "query": query,
            "limit": max_results,
            "year": f"{MIN_YEAR}-",
            "fields": "title,url,abstract,year",
        }
        url = f"{SEMANTIC_SCHOLAR_API}?{urllib.parse.urlencode(params)}"
        
        req = urllib.request.Request(url, headers={"User-Agent": "CatNews/2.0"})
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

def fetch_lwn_article_content(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CatNews/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8")
        
        text_content = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text_content = re.sub(r'<style[^>]*>.*?</style>', '', text_content, flags=re.DOTALL)
        text_content = re.sub(r'<[^>]+>', ' ', text_content)
        text_content = re.sub(r'\s+', ' ', text_content)
        
        return text_content[:2000]
    except Exception as e:
        print(f"    Error fetching article content: {e}")
        return None

def summarize_lwn_article(title, content):
    prompt = f"""标题：{title}
内容：{content}

请提取重要信息并返回JSON。"""
    
    response = call_minimax(prompt, LWN_SUMMARY_PROMPT)
    if not response:
        return None
    
    try:
        json_match = re.search(r'\{[^{}]+\}', response)
        if json_match:
            result = json.loads(json_match.group())
            result["relevance"] = "high"
            return result
    except:
        pass
    return None

def fetch_lwn_news():
    news = []
    try:
        print("  Fetching LWN.net...")
        time.sleep(3)
        
        req = urllib.request.Request(
            "https://lwn.net/Archives/",
            headers={"User-Agent": "CatNews/2.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8")
        
        network_keywords = ["network", "net", "TCP", "socket", "eBPF", "XDP", "driver", "packet", "networking"]
        
        links = re.findall(r'<a href="/Articles/(\d+)/"[^>]*>([^<]+)</a>', html)
        candidates = []
        
        for link_id, title in links[:50]:
            title_lower = title.lower()
            if any(kw.lower() in title_lower for kw in network_keywords):
                candidates.append({
                    "title": title.strip(),
                    "url": f"https://lwn.net/Articles/{link_id}/",
                    "source": "LWN.net"
                })
        
        print(f"    Found {len(candidates)} candidates, processing top 5...")
        
        for i, article in enumerate(candidates[:5]):
            print(f"    [{i+1}] {article['title'][:40]}...")
            time.sleep(2)
            
            content = fetch_lwn_article_content(article['url'])
            if content:
                summary_data = summarize_lwn_article(article['title'], content)
                if summary_data:
                    news.append({
                        "title": article['title'],
                        "url": article['url'],
                        "abstract": content[:300],
                        "summary": summary_data.get('summary', ''),
                        "source": "LWN.net",
                        "tags": summary_data.get('tags', [])[:4],
                        "readingTime": summary_data.get('readingTime', 8),
                        "relevance": "high"
                    })
                    print(f"      ✓ Summarized")
        
        print(f"    Final: {len(news)} LWN articles")
    except Exception as e:
        print(f"LWN fetch error: {e}")
    
    return news

def fetch_phoronix_news():
    news = []
    try:
        print("  Fetching Phoronix...")
        time.sleep(3)
        
        req = urllib.request.Request(
            "https://www.phoronix.com/news/Linux-Networking",
            headers={"User-Agent": "CatNews/2.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8")
        
        articles = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>([^<]{20,}?)</a>', html)
        for url, title in articles[:10]:
            if title.strip() and not url.startswith("#"):
                news.append({
                    "title": title.strip(),
                    "url": url if url.startswith("http") else f"https://www.phoronix.com{url}",
                    "abstract": title.strip(),
                    "source": "Phoronix"
                })
        
        print(f"    Found {len(news)} Phoronix articles")
    except Exception as e:
        print(f"Phoronix fetch error: {e}")
    
    return news[:5]

def fetch_kernel_newbies():
    news = []
    try:
        print("  Fetching Kernel Newbies...")
        time.sleep(3)
        
        req = urllib.request.Request(
            "https://kernelnewbies.org/KernelMap",
            headers={"User-Agent": "CatNews/2.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8")
        
        network_sections = re.findall(r'(Network[^<]*|TCP[^<]*|Socket[^<]*|Driver[^<]*)', html)
        for section in network_sections[:5]:
            news.append({
                "title": section.strip(),
                "url": "https://kernelnewbies.org/KernelMap",
                "abstract": section.strip(),
                "source": "Kernel Newbies"
            })
        
        print(f"    Found {len(news)} Kernel Newbies items")
    except Exception as e:
        print(f"Kernel Newbies fetch error: {e}")
    
    return news[:3]

HASH_FILE = ".hashes.json"

def get_hash(title):
    normalized = re.sub(r'[^\w]', '', title.lower())
    return hashlib.md5(normalized.encode()).hexdigest()

def load_existing_hashes(docs_dir):
    hashes = {"papers": set(), "news": set()}
    hash_file = os.path.join(docs_dir, HASH_FILE)
    
    if os.path.exists(hash_file):
        try:
            with open(hash_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                hashes["papers"] = set(data.get("papers", []))
                hashes["news"] = set(data.get("news", []))
        except:
            pass
    
    return hashes

def save_hashes(docs_dir, hashes):
    hash_file = os.path.join(docs_dir, HASH_FILE)
    data = {
        "papers": list(hashes["papers"]),
        "news": list(hashes["news"]),
        "lastUpdate": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(hash_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def deduplicate(items, existing_hashes, hash_key="papers"):
    seen = set()
    unique = []
    for item in items:
        h = get_hash(item["title"])
        if h not in seen and h not in existing_hashes[hash_key]:
            seen.add(h)
            unique.append(item)
    return unique

def count_tags(items):
    counts = {}
    for item in items:
        for tag in item.get("tags", []):
            counts[tag] = counts.get(tag, 0) + 1
    return counts

def safe_ratio(part, total):
    if total <= 0:
        return "0.0%"
    return f"{(part * 100.0 / total):.1f}%"

def main():
    print("Starting Linux kernel networking content fetch...")
    print("=" * 50)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    docs_dir = os.path.join(script_dir, "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    existing_hashes = load_existing_hashes(docs_dir)
    print(f"Loaded {len(existing_hashes['papers'])} paper hashes, {len(existing_hashes['news'])} news hashes")

    stats = {
        "paper_candidates_raw": 0,
        "paper_candidates_dedup": 0,
        "paper_quick_high_medium": 0,
        "paper_fill_medium_high": 0,
        "paper_fill_low": 0,
        "news_candidates_raw": 0,
        "news_candidates_dedup": 0,
        "news_quick_high_medium": 0,
        "news_preprocessed": 0,
        "news_fill_medium_high": 0,
        "news_fill_low": 0,
        "paper_hotspot_in_final": 0,
        "news_hotspot_in_final": 0,
    }
    
    paper_candidates = []
    
    print("\n[Phase 1] Fetching papers from arXiv...")
    split_idx = len(SEARCH_KEYWORDS) // 2
    for keyword in SEARCH_KEYWORDS[:split_idx]:
        print(f"  Keyword: {keyword}")
        paper_candidates.extend(fetch_arxiv_papers(keyword, 8))
    
    print("\n[Phase 2] Fetching papers from Semantic Scholar...")
    for keyword in SEARCH_KEYWORDS[split_idx:]:
        print(f"  Keyword: {keyword}")
        paper_candidates.extend(fetch_semantic_scholar_papers(keyword, 8))

    stats["paper_candidates_raw"] = len(paper_candidates)
    
    paper_candidates = deduplicate(paper_candidates, existing_hashes, "papers")
    paper_candidates = prioritize_items(paper_candidates, "abstract")
    stats["paper_candidates_dedup"] = len(paper_candidates)
    
    print(f"\n[Phase 3] Quick filtering {len(paper_candidates)} paper candidates...")
    filtered_candidates = []
    for i, paper in enumerate(paper_candidates[:MAX_CANDIDATES]):
        print(f"  [{i+1}] {paper['title'][:40]}...")
        random_delay(2, 3)

        if is_hard_excluded(f"{paper['title']} {paper['abstract']}"):
            print("    -> excluded by hard rules")
            continue
        
        relevance = quick_filter_relevance(paper['title'], paper['abstract'])
        print(f"    -> {relevance}")
        
        if relevance in ['high', 'medium']:
            filtered_candidates.append(paper)
            stats["paper_quick_high_medium"] += 1
        
        if len(filtered_candidates) >= MAX_PAPERS * 2:
            break
    
    if len(filtered_candidates) < MIN_PAPERS_TARGET:
        print("  Relevant papers below target, adding heuristic low-relevance candidates...")
        low_pool = []
        for paper in paper_candidates[:MAX_CANDIDATES]:
            if paper in filtered_candidates:
                continue
            fallback_relevance = heuristic_relevance(paper['title'], paper['abstract'])
            if fallback_relevance in ['medium', 'high']:
                filtered_candidates.append(paper)
                stats["paper_fill_medium_high"] += 1
            elif fallback_relevance == 'low':
                low_pool.append(paper)
            if len(filtered_candidates) >= MAX_PAPERS * 2:
                break

        if len(filtered_candidates) < MIN_PAPERS_TARGET:
            for paper in low_pool:
                filtered_candidates.append(paper)
                stats["paper_fill_low"] += 1
                if len(filtered_candidates) >= MAX_PAPERS * 2:
                    break

    print(f"  Filtered: {len(filtered_candidates)} relevant/near-relevant papers")
    
    print("\n[Phase 4] Fetching news from LWN/Phoronix...")
    news_candidates = []
    news_candidates.extend(fetch_lwn_news())
    news_candidates.extend(fetch_phoronix_news())
    news_candidates.extend(fetch_kernel_newbies())

    stats["news_candidates_raw"] = len(news_candidates)
    
    news_candidates = deduplicate(news_candidates, existing_hashes, "news")
    news_candidates = prioritize_items(news_candidates, "abstract")
    stats["news_candidates_dedup"] = len(news_candidates)
    
    print(f"\n[Phase 5] Quick filtering {len(news_candidates)} news candidates...")
    filtered_news = []
    for i, item in enumerate(news_candidates[:15]):
        if item.get('source') == 'LWN.net' and item.get('summary'):
            filtered_news.append(item)
            stats["news_preprocessed"] += 1
            print(f"  [{i+1}] {item['title'][:40]}... -> pre-processed")
        else:
            print(f"  [{i+1}] {item['title'][:40]}...")
            random_delay(2, 3)

            if is_hard_excluded(f"{item['title']} {item.get('abstract', item['title'])}"):
                print("    -> excluded by hard rules")
                continue
            
            relevance = quick_filter_relevance(item['title'], item.get('abstract', item['title']))
            print(f"    -> {relevance}")
            
            if relevance in ['high', 'medium']:
                filtered_news.append(item)
                stats["news_quick_high_medium"] += 1
        
        if len(filtered_news) >= MAX_NEWS * 2:
            break
    
    if len(filtered_news) < MIN_NEWS_TARGET:
        print("  Relevant news below target, adding heuristic low-relevance candidates...")
        low_pool = []
        for item in news_candidates[:20]:
            if item in filtered_news:
                continue
            fallback_relevance = heuristic_relevance(item['title'], item.get('abstract', item['title']))
            if fallback_relevance in ['medium', 'high']:
                filtered_news.append(item)
                stats["news_fill_medium_high"] += 1
            elif fallback_relevance == 'low':
                low_pool.append(item)
            if len(filtered_news) >= MAX_NEWS * 2:
                break

        if len(filtered_news) < MIN_NEWS_TARGET:
            for item in low_pool:
                filtered_news.append(item)
                stats["news_fill_low"] += 1
                if len(filtered_news) >= MAX_NEWS * 2:
                    break

    print(f"  Filtered: {len(filtered_news)} relevant/near-relevant news")
    
    selected_papers = []
    selected_news = []
    
    print(f"\n[Phase 6] Detailed analysis of {len(filtered_candidates)} filtered papers...")
    for i, paper in enumerate(filtered_candidates):
        print(f"\n[{i+1}/{len(filtered_candidates)}] {paper['title'][:50]}...")
        random_delay(LLM_DELAY_MIN, LLM_DELAY_MAX)
        
        analysis = analyze_item_with_llm(paper['title'], paper['abstract'], is_news=False)
        
        paper_hot_score = hot_topic_score(f"{paper['title']} {paper['abstract']}")
        if (
            analysis
            and analysis.get('relevance') in ['high', 'medium']
            and not is_hard_excluded(f"{paper['title']} {paper['abstract']}")
        ):
            if paper_hot_score > 0:
                stats["paper_hotspot_in_final"] += 1
            selected_papers.append({
                "title": paper['title'],
                "url": paper['url'],
                "summary": analysis.get('summary', ''),
                "summary_en": paper['abstract'][:150] + "...",
                "source": paper['source'],
                "tags": analysis.get('tags', [])[:4],
                "readingTime": analysis.get('readingTime', 5),
                "relevance": analysis.get('relevance', 'high')
            })
            print(f"  ✓ Processed")
        elif (
            analysis
            and analysis.get('relevance') == 'low'
            and paper_hot_score >= 2
            and not is_hard_excluded(f"{paper['title']} {paper['abstract']}")
        ):
            stats["paper_hotspot_in_final"] += 1
            selected_papers.append({
                "title": paper['title'],
                "url": paper['url'],
                "summary": analysis.get('summary', ''),
                "summary_en": paper['abstract'][:150] + "...",
                "source": paper['source'],
                "tags": analysis.get('tags', [])[:4],
                "readingTime": analysis.get('readingTime', 5),
                "relevance": "low"
            })
            print(f"  ✓ Processed (hotspot low)")
        
        if len(selected_papers) >= MAX_PAPERS:
            break
    
    print(f"\n[Phase 7] Detailed analysis of {len(filtered_news)} filtered news...")
    for i, item in enumerate(filtered_news):
        if len(selected_news) >= MAX_NEWS:
            break
        
        if item.get('source') == 'LWN.net' and item.get('summary'):
            selected_news.append(item)
            print(f"  [{i+1}] {item['title'][:40]}... -> ✓ pre-processed")
        else:
            print(f"\n  [{i+1}/{len(filtered_news)}] {item['title'][:50]}...")
            random_delay(LLM_DELAY_MIN, LLM_DELAY_MAX)
            
            analysis = analyze_item_with_llm(item['title'], item.get('abstract', item['title']), is_news=True)
            
            news_hot_score = hot_topic_score(f"{item['title']} {item.get('abstract', item['title'])}")
            if (
                analysis
                and analysis.get('relevance') in ['high', 'medium']
                and not is_hard_excluded(f"{item['title']} {item.get('abstract', item['title'])}")
            ):
                if news_hot_score > 0:
                    stats["news_hotspot_in_final"] += 1
                selected_news.append({
                    "title": item['title'],
                    "url": item['url'],
                    "summary": analysis.get('summary', ''),
                    "source": item['source'],
                    "tags": analysis.get('tags', [])[:4],
                    "readingTime": analysis.get('readingTime', 3),
                    "relevance": analysis.get('relevance', 'high')
                })
                print(f"    ✓ Processed")
            elif (
                analysis
                and analysis.get('relevance') == 'low'
                and news_hot_score >= 2
                and not is_hard_excluded(f"{item['title']} {item.get('abstract', item['title'])}")
            ):
                stats["news_hotspot_in_final"] += 1
                selected_news.append({
                    "title": item['title'],
                    "url": item['url'],
                    "summary": analysis.get('summary', ''),
                    "source": item['source'],
                    "tags": analysis.get('tags', [])[:4],
                    "readingTime": analysis.get('readingTime', 3),
                    "relevance": "low"
                })
                print(f"    ✓ Processed (hotspot low)")
    
    paper_tags = count_tags(selected_papers)
    news_tags = count_tags(selected_news)
    all_tags = {**paper_tags, **news_tags}
    
    print("\n" + "=" * 50)
    print(f"Summary: {len(selected_papers)} papers, {len(selected_news)} news")
    print(
        "Paper pipeline: "
        f"raw={stats['paper_candidates_raw']}, "
        f"dedup={stats['paper_candidates_dedup']}, "
        f"quick_hm={stats['paper_quick_high_medium']}, "
        f"fill_hm={stats['paper_fill_medium_high']}, "
        f"fill_low={stats['paper_fill_low']}, "
        f"hotspot_final={stats['paper_hotspot_in_final']}, "
        f"final={len(selected_papers)}, "
        f"dedup_rate={safe_ratio(stats['paper_candidates_dedup'], stats['paper_candidates_raw'])}, "
        f"final_rate={safe_ratio(len(selected_papers), stats['paper_candidates_dedup'])}"
    )
    print(
        "News pipeline: "
        f"raw={stats['news_candidates_raw']}, "
        f"dedup={stats['news_candidates_dedup']}, "
        f"preprocessed={stats['news_preprocessed']}, "
        f"quick_hm={stats['news_quick_high_medium']}, "
        f"fill_hm={stats['news_fill_medium_high']}, "
        f"fill_low={stats['news_fill_low']}, "
        f"hotspot_final={stats['news_hotspot_in_final']}, "
        f"final={len(selected_news)}, "
        f"dedup_rate={safe_ratio(stats['news_candidates_dedup'], stats['news_candidates_raw'])}, "
        f"final_rate={safe_ratio(len(selected_news), stats['news_candidates_dedup'])}"
    )
    
    beijing_now = datetime.now(timezone.utc) + timedelta(hours=8)
    today = beijing_now.strftime("%Y-%m-%d")
    
    output = {
        "date": today,
        "categories": {
            "papers": selected_papers,
            "news": selected_news
        },
        "tagStats": all_tags
    }
    
    output_path = os.path.join(docs_dir, f"{today}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    for paper in selected_papers:
        existing_hashes["papers"].add(get_hash(paper['title']))
    for item in selected_news:
        existing_hashes["news"].add(get_hash(item['title']))
    
    save_hashes(docs_dir, existing_hashes)
    print(f"Updated hash file: {len(existing_hashes['papers'])} papers, {len(existing_hashes['news'])} news")
    
    print(f"Output: {output_path}")

if __name__ == "__main__":
    main()
