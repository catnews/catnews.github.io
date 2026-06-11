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
OPENALEX_API = "https://api.openalex.org/works"
CROSSREF_API = "https://api.crossref.org/works"
DBLP_API = "https://dblp.org/search/publ/api"
OPENREVIEW_API = "https://api2.openreview.net/notes"
MINIMAX_API = "https://api.minimaxi.com/v1/chat/completions"
MINIMAX_MODEL = "MiniMax-M3"

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

CANONICAL_TAGS = {
    "ebpf": "eBPF",
    "bpf": "eBPF",
    "xdp": "XDP",
    "af_xdp": "XDP",
    "tcp/ip": "TCP/IP",
    "tcp": "TCP/IP",
    "tcp协议": "TCP/IP",
    "tcp/ip协议栈": "TCP/IP",
    "socket": "Socket",
    "netfilter": "Netfilter",
    "iptables": "Netfilter",
    "nftables": "Netfilter",
    "routing": "路由",
    "forwarding": "路由",
    "路由": "路由",
    "bridge": "网桥",
    "bridging": "网桥",
    "网桥": "网桥",
    "driver": "驱动",
    "nic": "驱动",
    "驱动": "驱动",
    "packet": "包处理",
    "skb": "包处理",
    "包处理": "包处理",
    "virtio": "虚拟化",
    "vhost": "虚拟化",
    "sriov": "虚拟化",
    "虚拟化": "虚拟化",
    "kernel bypass": "旁路",
    "dpdk": "旁路",
    "旁路": "旁路",
    "performance": "性能",
    "optimization": "性能",
    "latency": "性能",
    "throughput": "性能",
    "benchmark": "性能",
    "性能优化": "性能",
    "性能调优": "性能",
    "network optimization": "性能",
    "linux内核": "Linux内核网络",
    "linux内核网络": "Linux内核网络",
    "内核网络": "Linux内核网络",
    "kubernetes": "容器网络",
    "k8s": "容器网络",
    "cni": "容器网络",
    "容器网络/cni": "容器网络",
    "容器网络": "容器网络",
    "namespace": "容器网络",
    "netns": "容器网络",
    "veth": "容器网络",
    "ovs": "容器网络",
    "cilium": "容器网络",
    "service mesh": "容器网络",
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

LWN_PAYWALL_KEYWORDS = [
    "subscriber-only",
    "subscribers only",
    "available to subscribers only",
    "this article is available to subscribers only",
    "purchase a subscription",
    "log in to read",
    "subscribe to lwn",
]

KERNEL_ANCHOR_KEYWORDS = [
    "linux kernel",
    "kernel",
    "netdev",
    "skb",
    "sock",
    "netfilter",
    "nftables",
    "iptables",
    "xdp",
    "ebpf",
    "bpf",
    "tcp",
    "socket",
    "qdisc",
    "conntrack",
    "virtio",
    "vhost",
]

NETWORK_ANCHOR_KEYWORDS = [
    "network",
    "networking",
    "packet",
    "tcp",
    "ip",
    "socket",
    "routing",
    "forwarding",
    "bridge",
    "latency",
    "throughput",
    "cni",
    "kubernetes",
]

NON_KERNEL_CONTEXT_KEYWORDS = [
    "social network",
    "neural network",
    "wireless sensor",
    "blockchain",
    "5g application",
    "iot application",
    "video streaming",
    "recommendation system",
]

MIN_YEAR = 2020
MAX_PAPERS = 16
MAX_NEWS = 12
MAX_CANDIDATES = 80
MIN_PAPERS_TARGET = 12
MIN_NEWS_TARGET = 8
ENABLE_NEWS = True

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
{"summary": "中文总结280-600字，覆盖背景、核心变化、实现机制、影响，不要过度压缩", "keyPoints": ["按原文重要信息输出完整条目列表，数量不要人为限制，尽可能覆盖完整内容"], "tags": ["3-4个最主要标签"], "readingTime": 分钟数}

注意：
1. 不要只写结论，必须保留文章里的关键技术细节。
2. keyPoints 必须返回完整条目；每条都要能单独阅读，禁止只写名词短语、禁止过短。
3. keyPoints 的数量不要人为限制；如果原文有 8 条、10 条重要信息，就返回 8 条、10 条，不要压缩丢内容。
4. 每条 keyPoints 优先描述一个独立信息点，例如问题背景、补丁行为、实现机制、性能影响、争议点或后续计划。
5. tags数组最多包含3-4个最重要的标签。"""

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
                "model": MINIMAX_MODEL,
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
    if not passes_domain_gate(title, abstract):
        return "none"

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

def passes_domain_gate(title, abstract, source=""):
    merged = f"{title} {abstract}".lower()
    if is_hard_excluded(merged):
        return False

    if any(keyword in merged for keyword in NON_KERNEL_CONTEXT_KEYWORDS):
        if "linux" not in merged and "kernel" not in merged:
            return False

    kernel_hit = any(keyword in merged for keyword in KERNEL_ANCHOR_KEYWORDS)
    network_hit = any(keyword in merged for keyword in NETWORK_ANCHOR_KEYWORDS)

    if not kernel_hit or not network_hit:
        return False

    if source == "LWN.net":
        return True

    hot_score = hot_topic_score(merged)
    keyword_hits = keyword_hit_count(merged)
    if hot_score <= 0 and keyword_hits < 2:
        return False

    return True

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

def contains_chinese(text):
    if not isinstance(text, str):
        return False
    return re.search(r"[\u4e00-\u9fff]", text) is not None

def chinese_fallback_summary(title, content, tags, is_news=False):
    topic = "技术资讯" if is_news else "研究工作"
    tag_text = "、".join(tags[:3]) if tags else "Linux内核网络"
    brief = re.sub(r"\s+", " ", (content or "").strip())
    if len(brief) > 80:
        brief = brief[:80] + "..."
    if not brief:
        brief = "原文摘要信息有限，建议结合论文或文章原文进一步确认实现细节。"
    return (
        f"这篇{topic}《{title}》与{tag_text}相关，内容聚焦 Linux 内核网络场景下的"
        f"实现与优化。可重点关注其问题定义、方法设计与性能影响。参考信息：{brief}"
    )

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

def fetch_openalex_papers(query, max_results=8):
    papers = []
    try:
        random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        params = {
            "search": query,
            "filter": f"from_publication_date:{MIN_YEAR}-01-01,language:en",
            "per-page": max_results,
            "sort": "publication_date:desc",
        }
        url = f"{OPENALEX_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "CatNews/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        for item in data.get("results", []):
            title = item.get("title", "")
            abstract_inverted = item.get("abstract_inverted_index") or {}
            abstract = ""
            if abstract_inverted:
                pairs = []
                for word, positions in abstract_inverted.items():
                    for pos in positions:
                        pairs.append((pos, word))
                pairs.sort(key=lambda x: x[0])
                abstract = " ".join([w for _, w in pairs])
            year = item.get("publication_year", 0) or 0
            url_val = item.get("primary_location", {}).get("landing_page_url") or item.get("id", "")

            if title and url_val and year >= MIN_YEAR:
                papers.append({
                    "title": title,
                    "url": url_val,
                    "abstract": abstract,
                    "source": "OpenAlex",
                    "year": year,
                })
    except Exception as e:
        print(f"OpenAlex fetch error: {e}")
    return papers

def fetch_crossref_papers(query, max_results=8):
    papers = []
    try:
        random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        params = {
            "query": query,
            "filter": f"from-pub-date:{MIN_YEAR}-01-01,type:journal-article",
            "rows": max_results,
            "sort": "published",
            "order": "desc",
        }
        url = f"{CROSSREF_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "CatNews/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        for item in data.get("message", {}).get("items", []):
            titles = item.get("title", [])
            title = titles[0] if titles else ""
            abstract = re.sub(r"<[^>]+>", " ", item.get("abstract", "") or "")
            year = 0
            date_parts = item.get("published-print", {}).get("date-parts") or item.get("published-online", {}).get("date-parts") or []
            if date_parts and date_parts[0]:
                year = int(date_parts[0][0])
            doi = item.get("DOI", "")
            url_val = f"https://doi.org/{doi}" if doi else item.get("URL", "")

            if title and url_val and year >= MIN_YEAR:
                papers.append({
                    "title": title,
                    "url": url_val,
                    "abstract": abstract,
                    "source": "Crossref",
                    "year": year,
                })
    except Exception as e:
        print(f"Crossref fetch error: {e}")
    return papers

def fetch_dblp_papers(query, max_results=8):
    papers = []
    try:
        random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        params = {
            "q": query,
            "h": max_results,
            "format": "json",
        }
        url = f"{DBLP_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "CatNews/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        hits = data.get("result", {}).get("hits", {}).get("hit", [])
        if isinstance(hits, dict):
            hits = [hits]

        for hit in hits:
            info = hit.get("info", {})
            title = info.get("title", "")
            year = int(info.get("year", 0) or 0)
            url_val = info.get("ee", "") or info.get("url", "")
            venue = info.get("venue", "")
            abstract = f"Venue: {venue}" if venue else ""
            if title and url_val and year >= MIN_YEAR:
                papers.append({
                    "title": re.sub(r"<[^>]+>", " ", title),
                    "url": url_val,
                    "abstract": abstract,
                    "source": "DBLP",
                    "year": year,
                })
    except Exception as e:
        print(f"DBLP fetch error: {e}")
    return papers

def fetch_openreview_papers(query, max_results=8):
    papers = []
    try:
        random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        params = {
            "query": query,
            "limit": max_results,
        }
        url = f"{OPENREVIEW_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "CatNews/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        notes = data.get("notes", [])
        for note in notes:
            content = note.get("content", {})
            title = content.get("title", {}).get("value", "") if isinstance(content.get("title"), dict) else content.get("title", "")
            abstract = content.get("abstract", {}).get("value", "") if isinstance(content.get("abstract"), dict) else content.get("abstract", "")
            cdate = note.get("cdate", 0)
            year = datetime.fromtimestamp(cdate / 1000, tz=timezone.utc).year if cdate else 0
            forum = note.get("forum", "")
            url_val = f"https://openreview.net/forum?id={forum}" if forum else ""
            if title and url_val and year >= MIN_YEAR:
                papers.append({
                    "title": title,
                    "url": url_val,
                    "abstract": abstract,
                    "source": "OpenReview",
                    "year": year,
                })
    except Exception as e:
        print(f"OpenReview fetch error: {e}")
    return papers

def innovation_score(title, abstract, tags):
    text = f"{title} {abstract} {' '.join(tags or [])}".lower()
    score = 0
    novelty_terms = ["novel", "new", "first", "innovative", "improve", "optimization", "accelerat"]
    kernel_terms = ["linux kernel", "tcp", "xdp", "ebpf", "netfilter", "qdisc", "driver", "skb", "socket"]
    eval_terms = ["benchmark", "latency", "throughput", "evaluation", "experiment", "trace"]

    score += sum(1 for t in novelty_terms if t in text)
    score += sum(2 for t in kernel_terms if t in text)
    score += sum(1 for t in eval_terms if t in text)

    return min(score, 10)

def is_lwn_free_article(html):
    page = (html or "").lower()
    return not any(keyword in page for keyword in LWN_PAYWALL_KEYWORDS)


def fetch_lwn_article_content(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CatNews/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8")

        is_free = is_lwn_free_article(html)
        
        text_content = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text_content = re.sub(r'<style[^>]*>.*?</style>', '', text_content, flags=re.DOTALL)
        text_content = re.sub(r'<[^>]+>', ' ', text_content)
        text_content = re.sub(r'\s+', ' ', text_content)
        
        return {
            "content": text_content[:6000],
            "is_free": is_free,
        }
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
            key_points = result.get("keyPoints", [])
            if isinstance(key_points, list):
                result["keyPoints"] = [str(point).strip() for point in key_points if str(point).strip()]
            else:
                result["keyPoints"] = []
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
        
        print(f"    Found {len(candidates)} candidates, scanning all free articles in current archive...")
        
        for i, article in enumerate(candidates[:20]):
            print(f"    [{i+1}] {article['title'][:40]}...")
            time.sleep(2)
            
            article_data = fetch_lwn_article_content(article['url'])
            if not article_data:
                continue

            if not article_data.get("is_free"):
                print("      -> subscriber-only, skipped")
                continue

            content = article_data.get("content", "")
            summary_data = summarize_lwn_article(article['title'], content)
            if not summary_data:
                summary_data = analyze_item_with_llm(article['title'], content, is_news=True)

            if summary_data:
                news.append({
                    "title": article['title'],
                    "url": article['url'],
                    "abstract": content[:500],
                    "summary": summary_data.get('summary', ''),
                    "keyPoints": summary_data.get('keyPoints', []),
                    "source": "LWN.net",
                    "tags": summary_data.get('tags', [])[:4],
                    "readingTime": summary_data.get('readingTime', 8),
                    "relevance": "high",
                    "access": "free",
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

def normalize_tag(tag):
    if not isinstance(tag, str):
        return None
    cleaned = re.sub(r"\s+", " ", tag.strip())
    if not cleaned:
        return None
    canonical = CANONICAL_TAGS.get(cleaned.lower())
    return canonical if canonical else cleaned

def normalize_tags(tags, max_tags=4):
    if not isinstance(tags, list):
        return []
    normalized = []
    for tag in tags:
        converted = normalize_tag(tag)
        if converted and converted not in normalized:
            normalized.append(converted)
        if len(normalized) >= max_tags:
            break
    return normalized

def to_int(value, default_value):
    try:
        converted = int(value)
        if converted <= 0:
            return default_value
        return converted
    except Exception:
        return default_value

def ensure_non_empty_summary(text, fallback_text):
    if isinstance(text, str) and text.strip():
        return text.strip()
    return fallback_text

def sanitize_item(item, is_news=False):
    default_minutes = 3 if is_news else 5
    merged_for_fallback = f"{item.get('title', '')} {item.get('summary', '')}"
    item["tags"] = normalize_tags(item.get("tags", []), max_tags=4)
    item["summary"] = ensure_non_empty_summary(
        item.get("summary", ""),
        fallback_summary(merged_for_fallback, min_len=80 if is_news else 120),
    )
    if not contains_chinese(item["summary"]):
        item["summary"] = chinese_fallback_summary(
            item.get("title", ""),
            merged_for_fallback,
            item["tags"],
            is_news=is_news,
        )
    item["readingTime"] = to_int(item.get("readingTime", default_minutes), default_minutes)
    if item.get("relevance") not in ["high", "medium", "low", "none"]:
        item["relevance"] = "low"
    return item

def validate_output_item(item, category):
    if not isinstance(item, dict):
        return False, f"{category}: item is not object"

    required = ["title", "url", "summary", "source"]
    for field in required:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            return False, f"{category}: invalid field '{field}'"

    tags = item.get("tags", [])
    if not isinstance(tags, list):
        return False, f"{category}: invalid tags type"

    if "readingTime" in item and not isinstance(item.get("readingTime"), int):
        return False, f"{category}: readingTime must be int"

    if "keyPoints" in item:
        key_points = item.get("keyPoints")
        if not isinstance(key_points, list):
            return False, f"{category}: keyPoints must be list"
        for point in key_points:
            if not isinstance(point, str):
                return False, f"{category}: keyPoints entries must be string"

    if "relevance" in item and item.get("relevance") not in ["high", "medium", "low", "none"]:
        return False, f"{category}: invalid relevance"

    return True, ""

def validate_output_payload(payload):
    if not isinstance(payload, dict):
        return False, "payload is not object"
    if not isinstance(payload.get("date"), str) or not payload.get("date"):
        return False, "invalid date"

    categories = payload.get("categories")
    if not isinstance(categories, dict):
        return False, "invalid categories"

    papers = categories.get("papers", [])
    news = categories.get("news", [])
    if not isinstance(papers, list) or not isinstance(news, list):
        return False, "papers/news must be list"

    for paper in papers:
        ok, msg = validate_output_item(paper, "paper")
        if not ok:
            return False, msg

    for item in news:
        ok, msg = validate_output_item(item, "news")
        if not ok:
            return False, msg

    if not isinstance(payload.get("tagStats", {}), dict):
        return False, "invalid tagStats"

    return True, ""

def safe_ratio(part, total):
    if total <= 0:
        return "0.0%"
    return f"{(part * 100.0 / total):.1f}%"

def build_metrics(today, stats, selected_papers, selected_news):
    return {
        "date": today,
        "papers": {
            "raw": stats["paper_candidates_raw"],
            "dedup": stats["paper_candidates_dedup"],
            "quick_high_medium": stats["paper_quick_high_medium"],
            "fill_medium_high": stats["paper_fill_medium_high"],
            "fill_low": stats["paper_fill_low"],
            "hotspot_final": stats["paper_hotspot_in_final"],
            "final": len(selected_papers),
            "dedup_rate": safe_ratio(stats["paper_candidates_dedup"], stats["paper_candidates_raw"]),
            "final_rate": safe_ratio(len(selected_papers), stats["paper_candidates_dedup"]),
        },
        "news": {
            "raw": stats["news_candidates_raw"],
            "dedup": stats["news_candidates_dedup"],
            "preprocessed": stats["news_preprocessed"],
            "quick_high_medium": stats["news_quick_high_medium"],
            "fill_medium_high": stats["news_fill_medium_high"],
            "fill_low": stats["news_fill_low"],
            "hotspot_final": stats["news_hotspot_in_final"],
            "final": len(selected_news),
            "dedup_rate": safe_ratio(stats["news_candidates_dedup"], stats["news_candidates_raw"]),
            "final_rate": safe_ratio(len(selected_news), stats["news_candidates_dedup"]),
        },
    }

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
    
    print("\n[Phase 2] Fetching papers from Semantic Scholar/OpenAlex/Crossref/DBLP/OpenReview...")
    for keyword in SEARCH_KEYWORDS[split_idx:]:
        print(f"  Keyword: {keyword}")
        paper_candidates.extend(fetch_semantic_scholar_papers(keyword, 8))
        paper_candidates.extend(fetch_openalex_papers(keyword, 6))
        paper_candidates.extend(fetch_crossref_papers(keyword, 4))
        paper_candidates.extend(fetch_dblp_papers(keyword, 4))
        paper_candidates.extend(fetch_openreview_papers(keyword, 4))

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

        if not passes_domain_gate(paper['title'], paper['abstract'], paper.get('source', '')):
            print("    -> excluded by domain gate")
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
            if not passes_domain_gate(paper['title'], paper['abstract'], paper.get('source', '')):
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
    
    news_candidates = []
    if ENABLE_NEWS:
        print("\n[Phase 4] Fetching news from LWN/Phoronix...")
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

            if not passes_domain_gate(item['title'], item.get('abstract', item['title']), item.get('source', '')):
                print("    -> excluded by domain gate")
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
            if not passes_domain_gate(item['title'], item.get('abstract', item['title']), item.get('source', '')):
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
            and passes_domain_gate(paper['title'], paper['abstract'], paper.get('source', ''))
        ):
            if paper_hot_score > 0:
                stats["paper_hotspot_in_final"] += 1
            selected_papers.append({
                "title": paper['title'],
                "url": paper['url'],
                "summary": analysis.get('summary', ''),
                "summary_en": paper['abstract'][:150] + "...",
                "source": paper['source'],
                "tags": normalize_tags(analysis.get('tags', []), max_tags=4),
                "readingTime": analysis.get('readingTime', 5),
                "relevance": analysis.get('relevance', 'high'),
                "innovationScore": innovation_score(paper['title'], paper['abstract'], analysis.get('tags', [])),
            })
            selected_papers[-1] = sanitize_item(selected_papers[-1], is_news=False)
            print(f"  ✓ Processed")
        elif (
            analysis
            and analysis.get('relevance') == 'low'
            and paper_hot_score >= 2
            and not is_hard_excluded(f"{paper['title']} {paper['abstract']}")
            and passes_domain_gate(paper['title'], paper['abstract'], paper.get('source', ''))
        ):
            stats["paper_hotspot_in_final"] += 1
            selected_papers.append({
                "title": paper['title'],
                "url": paper['url'],
                "summary": analysis.get('summary', ''),
                "summary_en": paper['abstract'][:150] + "...",
                "source": paper['source'],
                "tags": normalize_tags(analysis.get('tags', []), max_tags=4),
                "readingTime": analysis.get('readingTime', 5),
                "relevance": "low",
                "innovationScore": innovation_score(paper['title'], paper['abstract'], analysis.get('tags', [])),
            })
            selected_papers[-1] = sanitize_item(selected_papers[-1], is_news=False)
            print(f"  ✓ Processed (hotspot low)")
        
        if len(selected_papers) >= MAX_PAPERS:
            break
    
    print(f"\n[Phase 7] Detailed analysis of {len(filtered_news)} filtered news...")
    for i, item in enumerate(filtered_news):
        if len(selected_news) >= MAX_NEWS:
            break
        
        if item.get('source') == 'LWN.net' and item.get('summary'):
            item['tags'] = normalize_tags(item.get('tags', []), max_tags=4)
            item = sanitize_item(item, is_news=True)
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
                and passes_domain_gate(item['title'], item.get('abstract', item['title']), item.get('source', ''))
            ):
                if news_hot_score > 0:
                    stats["news_hotspot_in_final"] += 1
                selected_news.append({
                    "title": item['title'],
                    "url": item['url'],
                    "summary": analysis.get('summary', ''),
                    "source": item['source'],
                    "tags": normalize_tags(analysis.get('tags', []), max_tags=4),
                    "readingTime": analysis.get('readingTime', 3),
                    "relevance": analysis.get('relevance', 'high')
                })
                selected_news[-1] = sanitize_item(selected_news[-1], is_news=True)
                print(f"    ✓ Processed")
            elif (
                analysis
                and analysis.get('relevance') == 'low'
                and news_hot_score >= 2
                and not is_hard_excluded(f"{item['title']} {item.get('abstract', item['title'])}")
                and passes_domain_gate(item['title'], item.get('abstract', item['title']), item.get('source', ''))
            ):
                stats["news_hotspot_in_final"] += 1
                selected_news.append({
                    "title": item['title'],
                    "url": item['url'],
                    "summary": analysis.get('summary', ''),
                    "source": item['source'],
                    "tags": normalize_tags(analysis.get('tags', []), max_tags=4),
                    "readingTime": analysis.get('readingTime', 3),
                    "relevance": "low"
                })
                selected_news[-1] = sanitize_item(selected_news[-1], is_news=True)
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

    ok, err = validate_output_payload(output)
    if not ok:
        raise ValueError(f"Output validation failed: {err}")
    
    output_path = os.path.join(docs_dir, f"{today}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    metrics = build_metrics(today, stats, selected_papers, selected_news)
    metrics_path = os.path.join(docs_dir, f"{today}.metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    
    for paper in selected_papers:
        existing_hashes["papers"].add(get_hash(paper['title']))
    for item in selected_news:
        existing_hashes["news"].add(get_hash(item['title']))
    
    save_hashes(docs_dir, existing_hashes)
    print(f"Updated hash file: {len(existing_hashes['papers'])} papers, {len(existing_hashes['news'])} news")
    
    print(f"Output: {output_path}")
    print(f"Metrics: {metrics_path}")

if __name__ == "__main__":
    main()
