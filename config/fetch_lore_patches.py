#!/usr/bin/env python3
"""Pull yesterday's netdev patches from patchwork.kernel.org and summarize via LLM.

This is a standalone module imported by fetch_papers.py.
- Source: patchwork.kernel.org Netdev + BPF project (project_id=399)
- For each patch on the previous Beijing-time day, classify:
    * inReview  (state == 'new')   - including RFC tags
    * merged    (state == 'accepted')
- Run domain gate (Linux kernel + network) using the same keywords as the
  papers pipeline; summarize accepted/new patches via MiniMax LLM.
- Write docs/<YYYY-MM-DD>.patches.json
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PATCHWORK_API = "https://patchwork.kernel.org/api/patches/"
NETDEV_PROJECT_ID = 399  # "Netdev + BPF" project on patchwork.kernel.org
PATCHWORK_MAX_PAGES = 4  # 120 patches latest, plenty for a single day
DEFAULT_MAX_INREVIEW = 12
DEFAULT_MAX_MERGED = 8

# State values from patchwork
STATE_IN_REVIEW = "new"          # posted, awaiting review
STATE_MERGED = "accepted"        # accepted into maintainer tree
# We also treat 'handled-elsewhere' as effectively merged info; skip for now.

# Beijing timezone for "yesterday" calculation (matches the main script)
BEIJING_TZ = timezone(timedelta(hours=8))


def _http_get_json(url, timeout=60, retries=3):
    """GET a JSON URL with retry/backoff. Returns parsed JSON or None."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "CatNews-Fetcher/1.0",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code} {e.reason}"
            if e.code == 429:
                wait = 15 + attempt * 10
                print(f"  [lore] rate-limited, waiting {wait}s", flush=True)
                time.sleep(wait)
            else:
                # 5xx transient
                time.sleep(5 + attempt * 5)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(3 + attempt * 3)
    print(f"  [lore] GET {url} failed after {retries} attempts: {last_err}", flush=True)
    return None


def _safe_parse_date(date_str):
    """Parse patchwork 'date' (ISO 8601, may be in the future due to bad header)."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        # Patchwork dates end without tz; assume UTC.
        return datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _is_recent_enough(date_obj, day_start_utc, day_end_utc, now_utc):
    """Filter: keep patches whose date falls within [day_start_utc, day_end_utc].

    Also handles the patchwork oddity where some legacy patches have
    far-future Date headers (e.g. 2085). For those, if they appear near
    the end of the page list we still want them - so we treat a future
    date as "very old / unknown" and drop it.
    """
    if date_obj is None:
        return False
    if date_obj > now_utc + timedelta(days=1):
        # Far-future (patchwork anomaly) - drop.
        return False
    return day_start_utc <= date_obj <= day_end_utc


def _is_rfc(name, prefixes):
    name_l = (name or "").lower()
    if "[rfc]" in name_l:
        return True
    for p in prefixes or []:
        if "rfc" in p.lower():
            return True
    return False


def _has_series_marker(prefixes):
    """A patch that's part of a series typically has '1/N', 'v2', 'PATCH net-next'."""
    for p in prefixes or []:
        if re.match(r"^\d+/\d+$", p.strip()):
            return True
        if re.match(r"^v\d+$", p.strip(), re.IGNORECASE):
            return True
    return False


def fetch_recent_patches(project_id=NETDEV_PROJECT_ID, max_pages=PATCHWORK_MAX_PAGES):
    """Walk patchwork by id descending, return raw patch list (newest first)."""
    out = []
    for page in range(1, max_pages + 1):
        url = f"{PATCHWORK_API}?project_id={project_id}&order=-id&page={page}"
        data = _http_get_json(url)
        if not data:
            break
        if not isinstance(data, list) or len(data) == 0:
            break
        out.extend(data)
        # Heuristic stop: if the oldest in this page is already well before "yesterday", bail.
        oldest_id = data[-1].get("id", 0)
        # Patches have monotonically increasing id; for netdev we get ~200-400 patches/day,
        # so 4 pages (120 patches) is more than enough for a 24h window.
        if page >= 3:
            break
        time.sleep(1.0)
    return out


def filter_by_date(patches, target_date_str):
    """Return (in_review, merged) for patches whose date is target_date_str (Beijing).

    target_date_str: 'YYYY-MM-DD' in Beijing time.
    """
    if not target_date_str:
        return [], []
    y, m, d = (int(x) for x in target_date_str.split("-"))
    day_start_local = datetime(y, m, d, 0, 0, 0, tzinfo=BEIJING_TZ)
    day_end_local = day_start_local + timedelta(days=1) - timedelta(seconds=1)
    day_start_utc = day_start_local.astimezone(timezone.utc)
    day_end_utc = day_end_local.astimezone(timezone.utc)
    now_utc = datetime.now(timezone.utc)

    in_review = []
    merged = []
    for p in patches:
        state = p.get("state")
        if state not in (STATE_IN_REVIEW, STATE_MERGED):
            continue
        dt = _safe_parse_date(p.get("date"))
        if not _is_recent_enough(dt, day_start_utc, day_end_utc, now_utc):
            # Once we exit the window, stop scanning (list is sorted -id).
            # Only stop if we passed the window from the bottom side; we cannot
            # easily detect that here, so do a soft pass.
            continue
        item = _normalize_patch(p)
        if state == STATE_IN_REVIEW:
            in_review.append(item)
        else:
            merged.append(item)
    return in_review, merged


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
        "isRfc": _is_rfc(name, prefixes),
        "isSeries": _has_series_marker(prefixes),
        "state": p.get("state"),
        "submitter": submitter,
        "date": p.get("date"),
        "raw": p,
    }


# -------------------- Domain gate (reuse from main module) --------------------
# We expect passes_domain_gate / is_hard_excluded to be passed in by the caller
# so we don't duplicate keyword lists. See fetch_papers.main().

def passes_domain(patch, gate_fn, excluded_fn):
    """Apply the same Linux kernel + network gate used for papers."""
    text = f"{patch.get('title', '')} {patch.get('summary', '')}".strip()
    if not text:
        return False
    if excluded_fn(text):
        return False
    return bool(gate_fn(patch.get("title", ""), text, source="lore.kernel.org"))


# -------------------- LLM summarization --------------------
PATCH_SUMMARY_PROMPT = """你是 Linux 内核网络补丁分析助手。阅读给定的 patch 标题与正文片段，
判断它是否属于 Linux 内核网络子系统（TCP/IP 协议栈 / eBPF / XDP / Netfilter /
网络驱动 / 路由网桥 / virtio-net / 网络性能优化等）。

如果属于，用 100-200 字中文总结它改动的核心点（实现机制 / 解决的问题 / 性能影响）。
如果不属于 Linux 内核网络，relevance 设为 'none'。

返回严格的 JSON 格式：
{
  "relevance": "high/medium/low/none",
  "summary": "中文总结",
  "tags": ["从下列标签中选 2-3 个：eBPF, XDP, TCP/IP, Socket, Netfilter, 路由, 网桥, 驱动, 包处理, 虚拟化, 性能, 容器网络, Linux内核网络"],
  "readingTime": 整数分钟数
}"""


def _format_patch_for_prompt(p):
    """Concatenate available text fields to feed the LLM."""
    raw = p.get("raw") or {}
    title = p.get("title", "")
    parts = [f"标题：{title}"]
    prefix = p.get("version") or ""
    if prefix:
        parts.append(f"前缀：[{prefix}]")
    # content may be huge; truncate
    content = (raw.get("content") or "").strip()
    if content:
        parts.append(f"补丁内容（截取前 1500 字）：\n{content[:1500]}")
    diff = (raw.get("diff") or "").strip()
    if diff:
        parts.append(f"diff（截取前 1200 字）：\n{diff[:1200]}")
    parts.append(f"提交者：{p.get('submitter', '')}")
    parts.append(f"链接：{p.get('url', '')}")
    return "\n\n".join(parts)


def _call_minimax_summary(call_minimax_fn, prompt):
    """Call the host's call_minimax; tolerate failures."""
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


def summarize_patches(call_minimax_fn, patches, gate_fn, excluded_fn,
                      limit=None, delay_min=2, delay_max=4):
    """Run LLM summary + domain gate on a list of normalized patches.

    Returns a filtered list with `summary`, `tags`, `relevance`, `readingTime` filled in.
    """
    results = []
    for p in patches:
        if limit and len(results) >= limit:
            break
        # Fetch full content if not already loaded
        raw = p.get("raw") or {}
        if not raw.get("content") and p.get("id"):
            detail = _http_get_json(f"{PATCHWORK_API}{p['id']}/")
            if detail:
                p["raw"] = detail
        prompt = _format_patch_for_prompt(p)
        if not prompt.strip():
            continue
        # Domain gate first (cheap)
        # Build a quick text corpus for the gate
        raw_now = p.get("raw") or {}
        gate_text = f"{p.get('title', '')}\n{(raw_now.get('content') or '')[:600]}"
        if not passes_domain({"title": p.get("title", ""), "summary": gate_text},
                             gate_fn, excluded_fn):
            print(f"  [lore] skip (gate) {p.get('id')} {p.get('title', '')[:40]}", flush=True)
            continue
        resp = _call_minimax_summary(call_minimax_fn, prompt)
        parsed = _parse_summary_response(resp)
        if not parsed:
            # Fallback: heuristic summary from the title + raw content head
            raw_now = p.get("raw") or {}
            fallback_text = (raw_now.get("content") or p.get("title", "")).strip()
            if not fallback_text:
                continue
            parsed = {
                "relevance": "low",
                "summary": _chinese_fallback(p.get("title", ""), fallback_text),
                "tags": _infer_tags_from_text(gate_text),
                "readingTime": 3,
            }
        if parsed["relevance"] == "none":
            print(f"  [lore] skip (none) {p.get('id')} {p.get('title', '')[:40]}", flush=True)
            continue
        p["summary"] = parsed["summary"]
        p["tags"] = parsed["tags"]
        p["relevance"] = parsed["relevance"]
        p["readingTime"] = parsed["readingTime"]
        # Drop raw to keep JSON small
        p.pop("raw", None)
        results.append(p)
        if delay_min and delay_max:
            time.sleep(random.uniform(delay_min, delay_max))
    return results


def _chinese_fallback(title, content):
    """Build a minimal Chinese summary when LLM is unavailable."""
    text = re.sub(r"\s+", " ", content or "").strip()
    if not text:
        return f"《{title}》与 Linux 内核网络相关，请参考原文获取完整信息。"
    clipped = text[:160]
    if len(text) > 160:
        clipped += "..."
    return f"《{title}》涉及 Linux 内核网络相关改动。摘要：{clipped}"


# Tag inference fallback (subset; the main script has a richer table).
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


# -------------------- Writer --------------------
def write_patches_file(docs_dir, target_date_str, in_review, merged, fetched_at):
    """Write docs/<date>.patches.json; returns the path."""
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


def run(docs_dir, target_date_str, *,
        call_minimax_fn, gate_fn, excluded_fn,
        max_in_review=DEFAULT_MAX_INREVIEW, max_merged=DEFAULT_MAX_MERGED,
        delay_min=2, delay_max=4):
    """Top-level entry point used by fetch_papers.main()."""
    print(f"[lore] fetching netdev patches for {target_date_str}", flush=True)
    raw = fetch_recent_patches()
    print(f"[lore]   raw pages fetched: {len(raw)} patches", flush=True)
    in_review, merged = filter_by_date(raw, target_date_str)
    print(f"[lore]   in day window: inReview={len(in_review)} merged={len(merged)}", flush=True)

    in_review = summarize_patches(call_minimax_fn, in_review, gate_fn, excluded_fn,
                                  limit=max_in_review, delay_min=delay_min, delay_max=delay_max)
    merged = summarize_patches(call_minimax_fn, merged, gate_fn, excluded_fn,
                               limit=max_merged, delay_min=delay_min, delay_max=delay_max)

    fetched_at = datetime.now(BEIJING_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")
    out_path = write_patches_file(docs_dir, target_date_str, in_review, merged, fetched_at)
    print(f"[lore] wrote {out_path}  inReview={len(in_review)} merged={len(merged)}", flush=True)
    return out_path
