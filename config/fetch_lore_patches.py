#!/usr/bin/env python3
"""Fetch yesterday's netdev + bpf patch activity from patchwork.kernel.org
and summarize via LLM.

This is a standalone module imported by fetch_papers.py.
- Source: patchwork.kernel.org Netdev + BPF (project link_name = "netdevbpf")
- Strategy:
    inReview  = state in (new, changes-requested, superseded, rfc)
                 whose submission date falls on "yesterday" (Beijing)
    merged    = state == accepted
                 (the date of a merged patch in patchwork reflects submission
                  time, not merge time; we just show the most recent accepted
                  set, capped at MAX_MERGED)
- The patchwork API has a quirk: ?project_id=<int> silently falls back to
  "Linux Input" for unknown ids. The reliable query is ?project=<link_name>.
- Apply domain gate (Linux kernel + network) and run MiniMax LLM for
  Chinese summary + tags + readingTime. Every surviving patch gets an
  LLM summary; calls run concurrently via a thread pool to amortize
  latency (see summarize_patches).
- Write docs/<YYYY-MM-DD>.patches.json
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

PATCHWORK_API = "https://patchwork.kernel.org/api/patches/"
NETDEV_PROJECT = "netdevbpf"  # Netdev + BPF on patchwork
PAGE_SIZE = 30
# Safety cap on pages; the early-stop below usually bails much earlier
# (typically around page 9 for a busy day).
MAX_INREVIEW_PAGES = 20
MAX_MERGED_PAGES = 10
DEFAULT_MAX_INREVIEW = 24  # cap LLM calls for in-review
DEFAULT_MAX_MERGED = None  # Keep merged feed complete; page fetch already bounds scope.
STATE_MERGED = "accepted"
STATE_IN_REVIEW_STATES = {"new", "changes-requested", "superseded", "rfc"}

# Beijing timezone
BEIJING_TZ = timezone(timedelta(hours=8))


# ---------------- HTTP ----------------
def _http_get_json(url, timeout=60, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "CatNews-Fetcher/1.0",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {e.reason}"
            if e.code == 429:
                time.sleep(15 + attempt * 10)
            else:
                time.sleep(3 + attempt * 3)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(3 + attempt * 3)
    print(f"  [lore] GET {url} failed after {retries} attempts: {last_err}", flush=True)
    return None


# ---------------- Fetch helpers ----------------
def _fetch_paginated(url_base, max_pages, stop_date_utc=None):
    """Walk a paginated patchwork endpoint, newest first.

    If `stop_date_utc` is given (ISO string like '2026-06-11T16:00:00'),
    stop early once a page's last (oldest) entry is older than that.
    Returns a list of patch dicts.
    """
    out = []
    hit_page_cap = False
    for page in range(1, max_pages + 1):
        sep = "&" if "?" in url_base else "?"
        url = f"{url_base}{sep}page={page}"
        data = _http_get_json(url)
        if not data or not isinstance(data, list) or len(data) == 0:
            break
        out.extend(data)
        if stop_date_utc:
            # API returns results sorted by `order` (we use order=-date),
            # so the last entry in the page is the oldest of this page.
            last_date = (data[-1].get("date") or "")[:19]
            if last_date and last_date < stop_date_utc:
                break
        if page == max_pages:
            hit_page_cap = True
        time.sleep(0.5)
    return out, hit_page_cap


def fetch_in_review_submissions(stop_date_utc=None):
    """Pull recent submissions across all in-review states, sorted by date desc."""
    url = f"{PATCHWORK_API}?project={NETDEV_PROJECT}&order=-date"
    return _fetch_paginated(url, MAX_INREVIEW_PAGES, stop_date_utc=stop_date_utc)


def fetch_accepted_merges(stop_date_utc=None):
    """Pull recent accepted patches (these are merged)."""
    url = f"{PATCHWORK_API}?project={NETDEV_PROJECT}&state={STATE_MERGED}&order=-date"
    return _fetch_paginated(url, MAX_MERGED_PAGES, stop_date_utc=stop_date_utc)


# ---------------- Date filter ----------------
def _safe_parse_date(date_str):
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        return datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _is_in_day(date_str, target_date_str):
    """Check whether date_str (patchwork 'date') is on target_date_str.

    Patchwork's 'date' field has uncertain timezone semantics (some
    records have future dates due to bad mail headers; some look like UTC).
    To stay correct we treat the date as wall-clock and apply a +8h Beijing
    shift, then take the calendar day. With ±2h fuzz this gives a 24h
    window for a single Beijing day, with up to 2h of overlap into
    neighbors which we accept.
    """
    if not date_str or not target_date_str:
        return False
    dt = _safe_parse_date(date_str)
    if dt is None:
        return False
    bj = dt.astimezone(BEIJING_TZ)
    return bj.strftime("%Y-%m-%d") == target_date_str


# ---------------- Patch classification ----------------
def _is_rfc(p):
    """RFC tag in patchwork 'tags' dict or [RFC] in name prefix."""
    tags = p.get("tags") or {}
    if isinstance(tags, dict) and any("rfc" in str(k).lower() for k in tags.keys()):
        return True
    name = p.get("name") or ""
    if re.match(r"^\s*\[RFC\b", name, re.IGNORECASE):
        return True
    prefixes = p.get("prefixes") or []
    return any("rfc" in str(p_).lower() for p_ in prefixes)


def _has_series_marker(p):
    prefixes = p.get("prefixes") or []
    for pfx in prefixes:
        if re.match(r"^\d+/\d+$", str(pfx).strip()):
            return True
    return False


def _is_in_review_state(p):
    state = p.get("state") or ""
    return state in STATE_IN_REVIEW_STATES


# ---------------- Normalize ----------------
def _normalize_patch(p):
    """Turn a patchwork patch dict into a flat dict for downstream processing."""
    prefixes = p.get("prefixes") or []
    name = p.get("name") or ""
    submitter = (p.get("submitter") or {}).get("name") or (p.get("submitter") or {}).get("email") or ""
    return {
        "id": p.get("id"),
        "title": name,
        "url": p.get("list_archive_url") or p.get("web_url"),
        "patchworkUrl": p.get("web_url"),
        "mbox": p.get("mbox"),
        "hash": p.get("hash"),
        "commitRef": p.get("commit_ref"),
        "version": ",".join(prefixes),
        "prefixes": prefixes,
        "isRfc": _is_rfc(p),
        "isSeries": _has_series_marker(p),
        "state": p.get("state"),
        "submitter": submitter,
        "date": p.get("date"),
        "raw": p,
    }


def _load_patch_detail(patch):
    """Fetch full detail to get content/diff (if not already in list response)."""
    raw = patch.get("raw") or {}
    if raw.get("content") or raw.get("diff"):
        return raw
    pid = patch.get("id")
    if not pid:
        return raw
    detail = _http_get_json(f"{PATCHWORK_API}{pid}/")
    if detail:
        patch["raw"] = detail
        return detail
    return raw


# ---------------- Domain gate ----------------
def passes_domain(patch, gate_fn, excluded_fn):
    text = f"{patch.get('title', '')} {patch.get('summary', '')}".strip()
    if not text:
        return False
    if excluded_fn(text):
        return False
    return bool(gate_fn(patch.get("title", ""), text, source="lore.kernel.org"))


# ---------------- LLM summarization ----------------
PATCH_SUMMARY_PROMPT = """你是 Linux 内核网络补丁分析助手。阅读给定的 patch 标题与正文片段，
判断它是否属于 Linux 内核网络子系统（TCP/IP 协议栈 / eBPF / XDP / Netfilter /
网络驱动 / 路由网桥 / virtio-net / 网络性能优化等）。

如果属于，用 100-200 字中文总结它改动的核心点：必须具体到被修改的内核对象 /
函数 / 数据结构（如 sk_buff、napi、qdisc、conntrack、tcp_sock、virtio_net、
bpf_prog、xdp_buff 等）、改动机制（新增 / 替换 / 移除 / 优化）、要解决的问题、
对性能或正确性的影响。如果补丁正文给出测试数据、benchmark 或具体数值，必须引用。

强约束：
1. summary 严禁复述、引用或翻译 patch 标题；不要以《标题》、
   "本补丁"、"该补丁"等开头提及标题；摘要直接陈述改动的对象与机制。
2. summary 严禁空泛套话，例如"主要围绕...进行调整"、"实现与优化"、
   "建议重点关注"、"参考信息："、"归入"、"被归入"、"阅读时重点核对三点"等。
3. 如果补丁正文信息不足，必须直说"补丁正文未提供 X 信息"，禁止用模板凑字数。

如果不属于 Linux 内核网络，relevance 设为 'none'。

返回严格的 JSON 格式：
{
  "relevance": "high/medium/low/none",
  "summary": "中文总结，不复述标题",
  "tags": ["从下列标签中选 2-3 个：eBPF, XDP, TCP/IP, Socket, Netfilter, 路由, 网桥, 驱动, 包处理, 虚拟化, 性能, 容器网络, Linux内核网络"],
  "readingTime": 整数分钟数
}"""


def _format_patch_for_prompt(p):
    raw = p.get("raw") or {}
    title = p.get("title", "")
    parts = [f"标题：{title}"]
    prefix = p.get("version") or ""
    if prefix:
        parts.append(f"前缀：[{prefix}]")
    content = (raw.get("content") or "").strip()
    if content:
        parts.append(f"补丁内容（前 1500 字）：\n{content[:1500]}")
    diff = (raw.get("diff") or "").strip()
    if diff:
        parts.append(f"diff（前 1200 字）：\n{diff[:1200]}")
    parts.append(f"提交者：{p.get('submitter', '')}")
    parts.append(f"链接：{p.get('url', '')}")
    if p.get("commitRef"):
        parts.append(f"合并 commit：{p['commitRef']}")
    return "\n\n".join(parts)


def _call_minimax_summary(call_minimax_fn, prompt):
    try:
        return call_minimax_fn(prompt, PATCH_SUMMARY_PROMPT, max_tokens=600)
    except Exception as e:
        print(f"  [lore] LLM call failed: {e}", flush=True)
        return None


_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _parse_summary_response(resp):
    if not resp:
        return None
    m = _JSON_RE.search(resp)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    rel = obj.get("relevance", "low")
    if rel not in ("high", "medium", "low", "none"):
        rel = "low"
    summary = (obj.get("summary") or "").strip()
    if not summary:
        return None
    tags = obj.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip() for t in tags if str(t).strip()][:3]
    try:
        reading_time = int(obj.get("readingTime", 3))
    except Exception:
        reading_time = 3
    return {
        "relevance": rel,
        "summary": summary,
        "tags": tags,
        "readingTime": max(1, min(reading_time, 30)),
    }


def _compact_patch_subject(title):
    text = re.sub(r"^\s*\[[^\]]+\]\s*", "", str(title or "")).strip()
    text = re.sub(r"^\s*(?:[A-Za-z0-9_.+-]+:\s*)+", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > 60:
        text = text[:60].rstrip()
    return text or "该补丁"


def _paraphrase_commit_style_text(text):
    cleaned = re.sub(r"^\s*\[[^\]]+\]\s*", "", str(text or "")).strip()
    cleaned = re.sub(r"^\s*(?:[A-Za-z0-9_.+-]+:\s*)+", "", cleaned).strip()
    cleaned = cleaned.replace("don't", "avoid").replace("do not", "avoid")

    replacements = [
        (r"(?i)\bswitch to\b", "切换为"),
        (r"(?i)\bconvert(?:ed)? to\b", "改为"),
        (r"(?i)\breplace(?:d)? with\b", "替换为"),
        (r"(?i)\breplace(?:d)?\b", "替换"),
        (r"(?i)\bfix(?:es|ed)?\b", "修复"),
        (r"(?i)\bremove(?:s|d)?\b", "移除"),
        (r"(?i)\badd(?:s|ed)?\b", "新增"),
        (r"(?i)\bupdate(?:s|d)?\b", "更新"),
        (r"(?i)\boptimi[sz]e(?:s|d)?\b", "优化"),
        (r"(?i)\bavoid(?:s|ed)?\b", "避免"),
        (r"(?i)\bprevent(?:s|ed)?\b", "防止"),
        (r"(?i)\brework(?:s|ed)?\b", "重构"),
        (r"(?i)\buse\b", "改用"),
        (r"(?i)\bgeneric learning enablement\b", "通用学习启用逻辑"),
        (r"(?i)\breallocated skb header\b", "重新分配后的 skb 头部"),
        (r"(?i)\bsource address\b", "源地址"),
        (r"(?i)\bread the ip source address\b", "读取 IP 源地址"),
    ]
    for pattern, repl in replacements:
        cleaned = re.sub(pattern, repl, cleaned)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-，,；;")
    return cleaned


def _chinese_fallback(title, content):
    subject = _compact_patch_subject(title)
    detail = _paraphrase_commit_style_text(content)
    if not detail:
        return f"《{subject}》主要调整 Linux 内核网络相关实现，重点在稳定性和可维护性。"

    title_text = re.sub(r"\s+", " ", str(title or "")).strip().lower()
    detail_text = re.sub(r"\s+", " ", detail).strip().lower()
    similar = bool(title_text and (detail_text == title_text or detail_text in title_text or title_text in detail_text))
    if similar or len(detail) < 28:
        return f"《{subject}》主要围绕相关实现做调整，重点是修复边界问题并提升一致性。"

    if len(detail) > 84:
        detail = detail[:84].rstrip() + "..."
    return f"《{subject}》主要围绕“{detail}”进行调整，修正相关实现并降低维护成本。"


_LORE_TAG_HINTS = {
    "ebpf": "eBPF", "bpf": "eBPF",
    "xdp": "XDP", "af_xdp": "XDP",
    "tcp": "TCP/IP", "ip": "TCP/IP",
    "netfilter": "Netfilter", "nftables": "Netfilter", "iptables": "Netfilter",
    "conntrack": "Netfilter",
    "routing": "路由", "route": "路由", "forwarding": "路由", "fib": "路由",
    "bridge": "网桥", "vlan": "网桥",
    "driver": "驱动", "drv": "驱动", "nic": "驱动",
    "packet": "包处理", "skb": "包处理", "softnet": "包处理",
    "virtio": "虚拟化", "vhost": "虚拟化", "vhost_net": "虚拟化",
    "performance": "性能", "latency": "性能", "throughput": "性能",
    "optimization": "性能", "qdisc": "性能",
    "container": "容器网络", "kubernetes": "容器网络", "netns": "容器网络",
    "veth": "容器网络", "cni": "容器网络",
    "linux kernel": "Linux内核网络",
}


def _infer_tags_from_text(text, max_tags=3):
    lower = (text or "").lower()
    out = []
    for k, t in _LORE_TAG_HINTS.items():
        if k in lower and t not in out:
            out.append(t)
        if len(out) >= max_tags:
            break
    return out


def _process_single_patch(p, call_minimax_fn, gate_fn, excluded_fn):
    """Process one patch end-to-end inside a worker thread.

    Steps: load detail -> domain gate -> LLM summary -> heuristic fallback.
    Returns the patched dict (with summary/tags/relevance/readingTime) on
    success, or None if filtered out by gate / skipped as unrelated.
    """
    try:
        _load_patch_detail(p)
    except Exception as e:
        print(f"  [lore] detail fetch failed for {p.get('id')}: {e}", flush=True)
        return None

    raw = p.get("raw") or {}
    gate_text = f"{p.get('title', '')}\n{(raw.get('content') or '')[:600]}"
    if not passes_domain({"title": p.get("title", ""), "summary": gate_text},
                         gate_fn, excluded_fn):
        print(f"  [lore] skip (gate) {p.get('id')} {p.get('title', '')[:40]}", flush=True)
        return None

    parsed = None
    if call_minimax_fn:
        prompt = _format_patch_for_prompt(p)
        resp = _call_minimax_summary(call_minimax_fn, prompt)
        parsed = _parse_summary_response(resp)

    if not parsed:
        # LLM path exhausted (call failure / unparseable response). Keep a
        # heuristic summary so the patch still shows up in the feed, but
        # mark relevance as low to signal it was not LLM-summarized.
        fallback_text = (raw.get("content") or p.get("title", "")).strip()
        if not fallback_text:
            return None
        parsed = {
            "relevance": "low",
            "summary": _chinese_fallback(p.get("title", ""), fallback_text),
            "tags": _infer_tags_from_text(gate_text),
            "readingTime": 3,
        }

    if parsed.get("relevance") == "none":
        print(f"  [lore] skip (none) {p.get('id')} {p.get('title', '')[:40]}", flush=True)
        return None

    p["summary"] = parsed["summary"]
    p["tags"] = parsed["tags"]
    p["relevance"] = parsed["relevance"]
    p["readingTime"] = parsed["readingTime"]
    # Drop raw to keep JSON small
    p.pop("raw", None)
    return p


def summarize_patches(call_minimax_fn, patches, gate_fn, excluded_fn,
                      limit=None, max_workers=4, llm_budget=None,
                      delay_min=None, delay_max=None):
    """Run domain gate + LLM summary on every patch, in parallel.

    Behavior:
      * Domain gate is applied to every patch; non-networking patches are
        dropped entirely.
      * EVERY network patch now goes through the LLM (the previous
        ``llm_budget`` cap that limited LLM calls to the first N net
        patches has been removed). The historical ``llm_budget`` parameter
        is kept in the signature for backward compatibility but ignored.
      * Calls are executed concurrently via ThreadPoolExecutor to amortize
        MiniMax latency; ``max_workers`` bounds concurrency to avoid
        tripping rate limits.
      * If ``call_minimax_fn`` is None, every patch falls back to the
        heuristic path.
      * Output order follows input order (filtered to entries that
        survived the gate).
    """
    candidates = list(patches)
    if limit and len(candidates) > limit:
        candidates = candidates[:limit]

    if not candidates:
        return []

    workers = max(1, int(max_workers or 1))
    results_by_index = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(
                _process_single_patch,
                p, call_minimax_fn, gate_fn, excluded_fn,
            ): i
            for i, p in enumerate(candidates)
        }
        done = 0
        total = len(future_to_index)
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            done += 1
            try:
                result = future.result()
            except Exception as e:
                print(f"  [lore] worker error on patch #{idx}: {e}", flush=True)
                result = None
            if result is not None:
                results_by_index[idx] = result
            if done % 10 == 0 or done == total:
                print(f"  [lore] progress {done}/{total} (kept {len(results_by_index)})", flush=True)

    return [results_by_index[i] for i in range(len(candidates)) if i in results_by_index]


# ---------------- Writer ----------------
def write_patches_file(docs_dir, target_date_str, in_review, merged, fetched_at):
    os.makedirs(docs_dir, exist_ok=True)
    rfc_count = sum(1 for p in in_review if p.get("isRfc"))
    payload = {
        "date": target_date_str,
        "fetchedAt": fetched_at,
        "totals": {
            "inReview": len(in_review),
            "merged": len(merged),
            "rfc": rfc_count,
        },
        "inReview": in_review,
        "merged": merged,
    }
    out_path = os.path.join(docs_dir, f"{target_date_str}.patches.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


# ---------------- Top-level ----------------
def run(docs_dir, target_date_str, *,
        call_minimax_fn, gate_fn, excluded_fn,
        max_in_review=80, max_merged=DEFAULT_MAX_MERGED, llm_budget_per_side=None,
        max_workers=4, delay_min=None, delay_max=None):
    print(f"[lore] fetching netdevbpf patches for {target_date_str}", flush=True)

    # Compute the Beijing-day window in UTC, used as the early-stop boundary.
    y, m, d = (int(x) for x in target_date_str.split("-"))
    day_start_bj = datetime(y, m, d, 0, 0, 0, tzinfo=BEIJING_TZ)
    # Anything dated before this is OUTSIDE the target day in BJ time.
    stop_utc = day_start_bj.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    # 1. In-review submissions: filter by Beijing "yesterday" date
    in_review_raw, in_review_hit_cap = fetch_in_review_submissions(stop_date_utc=stop_utc)
    in_review_raw = [p for p in in_review_raw if _is_in_review_state(p)]
    in_review_raw = [p for p in in_review_raw if _is_in_day(p.get("date"), target_date_str)]
    print(f"[lore]   in-review submissions on {target_date_str}: {len(in_review_raw)}", flush=True)

    # 2. Merged (accepted): the date in patchwork is submission time, not merge time.
    #    We take the most recent accepted set and present them as the
    #    "recently merged" feed (capped). We use a wider stop window here so
    #    users see accepted commits that landed in the last few days, not
    #    only those submitted in the target day.
    merged_stop_utc = (day_start_bj - timedelta(days=5)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    merged_raw, merged_hit_cap = fetch_accepted_merges(stop_date_utc=merged_stop_utc)
    print(f"[lore]   total accepted fetched: {len(merged_raw)}", flush=True)
    if in_review_hit_cap:
        print(f"[lore]   warning: in-review fetch hit page cap ({MAX_INREVIEW_PAGES} pages)", flush=True)
    if merged_hit_cap:
        print(f"[lore]   warning: merged fetch hit page cap ({MAX_MERGED_PAGES} pages)", flush=True)

    in_review_normalized = [_normalize_patch(p) for p in in_review_raw]
    merged_normalized = [_normalize_patch(p) for p in merged_raw]

    in_review = summarize_patches(call_minimax_fn, in_review_normalized, gate_fn, excluded_fn,
                                  limit=max_in_review, max_workers=max_workers)
    merged = summarize_patches(call_minimax_fn, merged_normalized, gate_fn, excluded_fn,
                               limit=max_merged, max_workers=max_workers)

    fetched_at = datetime.now(BEIJING_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")
    out_path = write_patches_file(docs_dir, target_date_str, in_review, merged, fetched_at)
    print(f"[lore] wrote {out_path}  inReview={len(in_review)} merged={len(merged)}", flush=True)
    return out_path
