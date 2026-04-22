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
]

MIN_YEAR = 2020
MAX_PAPERS = 10
MAX_NEWS = 8
MAX_CANDIDATES = 40

PAPER_PROMPT = """你是一个专业的论文筛选助手。分析论文是否与 Linux 内核网络子系统直接相关。

Linux 内核网络相关主题：TCP/IP协议栈、Socket API、eBPF/XDP、Netfilter/nftables、Kernel Bypass、Virtio/vHost、网络驱动、路由/网桥/包处理。

返回JSON格式：
{"relevance": "high/medium/low/none", "summary": "中文总结150-300字", "tags": ["3-4个最主要标签"], "readingTime": 分钟数}

注意：tags数组最多包含3-4个最重要的标签，不要过多。"""

NEWS_PROMPT = """你是一个技术资讯筛选助手。分析文章是否与 Linux 内核网络相关。

相关主题：网络性能测试、内核网络更新、驱动发布、网络子系统讨论等。

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

def analyze_item_with_llm(title, content, is_news=False):
    prompt = f"""标题：{title}
内容：{content[:400]}

请分析并返回JSON，tags最多3-4个。"""
    
    system_prompt = NEWS_PROMPT if is_news else PAPER_PROMPT
    response = call_minimax(prompt, system_prompt)
    
    if not response:
        return None
    
    try:
        json_match = re.search(r'\{[^{}]+\}', response)
        if json_match:
            result = json.loads(json_match.group())
            if 'tags' in result and len(result['tags']) > 4:
                result['tags'] = result['tags'][:4]
            return result
    except:
        pass
    return None

def fetch_arxiv_papers(query, max_results=5):
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

def fetch_semantic_scholar_papers(query, max_results=5):
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

def get_hash(title):
    normalized = re.sub(r'[^\w]', '', title.lower())
    return hashlib.md5(normalized.encode()).hexdigest()

def load_existing_hashes(docs_dir):
    hashes = {"papers": set(), "news": set()}
    if not os.path.exists(docs_dir):
        return hashes
    
    for filename in os.listdir(docs_dir):
        if filename.endswith('.json'):
            filepath = os.path.join(docs_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for paper in data.get('categories', {}).get('papers', []):
                        hashes["papers"].add(get_hash(paper['title']))
                    for item in data.get('categories', {}).get('news', []):
                        hashes["news"].add(get_hash(item['title']))
            except:
                pass
    return hashes

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

def main():
    print("Starting Linux kernel networking content fetch...")
    print("=" * 50)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    docs_dir = os.path.join(script_dir, "..", "docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    existing_hashes = load_existing_hashes(docs_dir)
    print(f"Loaded {len(existing_hashes['papers'])} paper hashes, {len(existing_hashes['news'])} news hashes")
    
    paper_candidates = []
    
    print("\n[Phase 1] Fetching papers from arXiv...")
    for keyword in SEARCH_KEYWORDS[:6]:
        print(f"  Keyword: {keyword}")
        paper_candidates.extend(fetch_arxiv_papers(keyword, 5))
    
    print("\n[Phase 2] Fetching papers from Semantic Scholar...")
    for keyword in SEARCH_KEYWORDS[6:]:
        print(f"  Keyword: {keyword}")
        paper_candidates.extend(fetch_semantic_scholar_papers(keyword, 5))
    
    paper_candidates = deduplicate(paper_candidates, existing_hashes, "papers")
    paper_candidates = paper_candidates[:MAX_CANDIDATES]
    
    print("\n[Phase 3] Fetching news from LWN/Phoronix...")
    news_candidates = []
    news_candidates.extend(fetch_lwn_news())
    news_candidates.extend(fetch_phoronix_news())
    news_candidates.extend(fetch_kernel_newbies())
    
    news_candidates = deduplicate(news_candidates, existing_hashes, "news")
    news_candidates = news_candidates[:10]
    
    selected_papers = []
    selected_news = []
    
    print(f"\n[Phase 4] LLM Analysis of {len(paper_candidates)} paper candidates...")
    for i, paper in enumerate(paper_candidates):
        print(f"\n[{i+1}/{len(paper_candidates)}] {paper['title'][:50]}...")
        random_delay(LLM_DELAY_MIN, LLM_DELAY_MAX)
        
        analysis = analyze_item_with_llm(paper['title'], paper['abstract'], is_news=False)
        
        if analysis and analysis.get('relevance') in ['high', 'medium']:
            selected_papers.append({
                "title": paper['title'],
                "url": paper['url'],
                "summary": analysis.get('summary', ''),
                "summary_en": paper['abstract'][:150] + "...",
                "source": paper['source'],
                "tags": analysis.get('tags', [])[:4],
                "readingTime": analysis.get('readingTime', 5),
                "relevance": analysis.get('relevance')
            })
            print(f"  ✓ Selected")
        
        if len(selected_papers) >= MAX_PAPERS:
            break
    
    print(f"\n[Phase 5] Processing news...")
    lwn_items = [n for n in news_candidates if n.get('source') == 'LWN.net' and n.get('summary')]
    other_items = [n for n in news_candidates if n.get('source') != 'LWN.net' or not n.get('summary')]
    
    print(f"  LWN items (already processed): {len(lwn_items)}")
    for item in lwn_items:
        if len(selected_news) < MAX_NEWS:
            selected_news.append(item)
            print(f"    ✓ {item['title'][:40]}...")
    
    print(f"\n  Other items need analysis: {len(other_items)}")
    for i, item in enumerate(other_items):
        if len(selected_news) >= MAX_NEWS:
            break
        print(f"\n  [{i+1}/{len(other_items)}] {item['title'][:50]}...")
        random_delay(LLM_DELAY_MIN, LLM_DELAY_MAX)
        
        analysis = analyze_item_with_llm(item['title'], item.get('abstract', ''), is_news=True)
        
        if analysis and analysis.get('relevance') in ['high', 'medium']:
            selected_news.append({
                "title": item['title'],
                "url": item['url'],
                "summary": analysis.get('summary', ''),
                "source": item['source'],
                "tags": analysis.get('tags', [])[:4],
                "readingTime": analysis.get('readingTime', 3),
                "relevance": analysis.get('relevance')
            })
            print(f"    ✓ Selected")
    
    paper_tags = count_tags(selected_papers)
    news_tags = count_tags(selected_news)
    all_tags = {**paper_tags, **news_tags}
    
    print("\n" + "=" * 50)
    print(f"Summary: {len(selected_papers)} papers, {len(selected_news)} news")
    
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
    
    print(f"Output: {output_path}")

if __name__ == "__main__":
    main()