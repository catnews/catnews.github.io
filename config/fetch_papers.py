#!/usr/bin/env python3
import json
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import os
import sys
import hashlib
import re
import time
import random
import html as html_lib
import threading
import socket

# Process-wide MiniMax rate-limit throttle. Any worker that receives an
# HTTP 429 sets `_MINIMAX_THROTTLE_UNTIL` to a future epoch timestamp;
# every worker honors this before issuing a new request to avoid
# compounding rate-limit failures when running concurrently (e.g. the
# netdev patch summarization thread pool).
_MINIMAX_LOCK = threading.Lock()
_MINIMAX_THROTTLE_UNTIL = 0.0

ARXIV_API = "http://export.arxiv.org/api/query"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_API = "https://api.openalex.org/works"
CROSSREF_API = "https://api.crossref.org/works"
DBLP_API = "https://dblp.org/search/publ/api"
OPENREVIEW_API = "https://api2.openreview.net/notes"
MINIMAX_API = "https://api.minimaxi.com/v1/chat/completions"
MINIMAX_MODEL = "MiniMax-M3"

REQUEST_DELAY_MIN = 4
REQUEST_DELAY_MAX = 7
LLM_DELAY_MIN = 3
LLM_DELAY_MAX = 5
ARXIV_DELAY = 5

# Polite User-Agent identifying the bot and pointing to the project repo +
# issues entry. Crossref looks for a mailto in UA to enter its polite pool;
# we use the issues URL as the contact surface so we don't fabricate an
# unreachable mailbox. arXiv / S2 / OpenAlex / DBLP all prefer a UA that
# identifies the crawler rather than a generic browser string.
APP_USER_AGENT = "CatNews/2.0 (https://github.com/catnews/catnews.github.io; contact: https://github.com/catnews/catnews.github.io/issues)"

SEARCH_KEYWORDS = [
    # 核心代码符号 / 子系统（精确）
    "Linux sk_buff kernel",
    "Linux net_device kernel",
    "Linux qdisc traffic control",
    "Linux netlink kernel",
    # XDP / eBPF / 数据面
    "Linux XDP data path",
    "Linux eBPF networking",
    "Linux AF_XDP zero copy",
    "Linux sock_map sockhash",
    # netfilter / conntrack（iptables 已并入 netfilter nftables）
    "Linux netfilter nftables",
    "Linux conntrack netfilter",
    # TCP / 协议栈
    "Linux TCP IP stack kernel",
    "Linux TCP congestion kernel",
    "Linux socket kernel performance",
    # 虚拟化 / 内核 bypass
    "Linux virtio network",
    "Linux vhost_net vhost-net",
    "Linux kernel bypass networking",
    # 容器网络（veth 已并入 network namespace；tc flower 召回差已删）
    "Linux network namespace kernel",
    "Linux Cilium eBPF",
    # 驱动 / 中断
    "Linux network driver kernel",
    "Linux NAPI softirq network",
    # 其他
    "Linux io_uring network",
    # SmartNIC offload / kernel bypass / 用户态高速网络栈
    # （off-path / BlueField / hardware-offloaded 均已并入 SmartNIC 总称）
    "SmartNIC offload network stack",
    "DPDK kernel bypass network",
    "RDMA Linux kernel network",
    # AI 沙箱 / 代码执行沙箱网络隔离
    # （LLM code interpreter / agent sandbox 的网络面，最终仍落到 netns / veth / eBPF）
    "AI code interpreter sandbox network",
    "LLM agent sandbox network namespace",
    "code execution sandbox Linux network",
    # MicroVM 沙箱数据面
    # （firecracker / kata / cloud-hypervisor 的 virtio-net / vhost-net 数据面）
    "Firecracker microVM virtio network",
    "Kata containers virtio-net sandbox",
    "Cloud Hypervisor vhost-net network",
    "microVM network isolation kernel",
    # 容器 / eBPF 网络策略（AI 工作负载网络隔离）
    "Cilium NetworkPolicy AI workload",
    "eBPF sandbox network isolation",
    "Tetragon sandbox network policy",
    # AI 推理 / 训练网络（GPU 直通 / SR-IOV / RDMA 在沙箱容器内的网络栈）
    "GPU SR-IOV container networking",
    "RDMA RoCE AI training network",
    "virtio GPU passthrough networking",
    "AI inference container network stack",
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
    # AI 沙箱 / MicroVM 热点加权
    "microvm",
    "firecracker",
    "kata",
    "cloud hypervisor",
    "code interpreter",
    "agent sandbox",
    "ai sandbox",
    "llm sandbox",
    "gpu passthrough",
    "sriov vf",
    "rdma roce",
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
    # AI 沙箱 / MicroVM 沙箱（网络面）
    "microvm": "沙箱",
    "firecracker": "沙箱",
    "kata": "沙箱",
    "cloud hypervisor": "沙箱",
    "code interpreter": "沙箱",
    "agent sandbox": "沙箱",
    "ai sandbox": "沙箱",
    "llm sandbox": "沙箱",
    "sandbox network": "沙箱",
    # AI 推理 / 训练网络
    "gpu passthrough": "虚拟化",
    "sriov vf": "虚拟化",
    "vfio": "虚拟化",
    "rdma roce": "旁路",
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
    # AI 沙箱 / MicroVM 沙箱网络面
    "microvm": "沙箱",
    "microvm network": "沙箱",
    "firecracker": "沙箱",
    "kata": "沙箱",
    "kata container": "沙箱",
    "cloud hypervisor": "沙箱",
    "code interpreter sandbox": "沙箱",
    "agent sandbox": "沙箱",
    "ai sandbox": "沙箱",
    "llm sandbox": "沙箱",
    "沙箱": "沙箱",
    "沙箱网络": "沙箱",
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

# 仅在 Linux 内核网络源码 / 子系统上下文中才会出现的术语。
# 用于 passes_domain_gate 的硬锚点：必须命中至少一个，才认为论文
# 可能真正触及 Linux 内核网络代码路径，而非通用网络研究。
KERNEL_SPECIFIC_TERMS = [
    # 核心 skb / 设备 / sock 结构
    "sk_buff", "skb", "net_device", "netdev",
    "sock_map", "sockmap", "sockhash",
    "bpf_prog", "bpf_sk", "bpf_xdp", "bpf_redirect", "bpf_map", "bpf_sk_lookup",
    "napi", "softirq", "netif_rx", "netif_receive_skb", "dev_queue_xmit",
    "ndo_start_xmit", "ip_rcv", "nf_hook", "nf_hook_slow",
    "tcp_sock", "tcp_v4", "tcp_v6", "tcp_listen",
    # 子系统 / 工具
    "qdisc", "netlink", "ethtool", "iproute2",
    "ip_tables", "iptables", "nf_tables", "nftables", "nft_",
    "conntrack", "nf_conntrack",
    # 多队列 / 协议卸载
    "xps", "rps", "rfs", " gro ", " gso ", " tso ", " rss ",
    # 虚拟化
    "virtio-net", "virtio_net", "vhost-net", "vhost_net",
    "af_xdp", "afxdp", "xdp_buff", "xdp_redirect", "xdp_meta",
    # 命名空间
    "net_namespace", "netns", " veth ",
    # 内核子系统短语（宽松但内核专属）
    "kernel network stack",
    "kernel networking stack",
    "kernel networking subsystem",
    "kernel network subsystem",
    "linux networking stack",
    "linux network stack",
    "linux kernel network",
    "kernel tcp/ip",
    "kernel tcp stack",
    # 论文摘要中常见的高层概念词（非源码符号）；与上面源码符号互补，
    # 避免 KERNEL_SPECIFIC_TERMS 全部是 sk_buff/net_device 这类论文
    # 摘要几乎不会出现的源码符号，导致硬锚点过严、召回几乎全空
    "linux kernel",
    "kernel networking",
    "linux networking",
    "kernel socket",
    "kernel tcp",
    "kernel udp",
    "kernel ip",
    "kernel packet",
    "ebpf",
    "bpf",
    "xdp",
    "netfilter",
    "virtio",
    "vhost",
    "sriov",
    # SmartNIC offload / kernel bypass / 用户态高速网络栈
    # （AGENTS.md 高级特性 "Kernel Bypass (DPDK, user-space networking)" 范畴）
    "smartnic",
    "off-path smartnic",
    "hardware-offloaded network stack",
    "hardware offloaded network",
    "kernel bypass",
    " dpdk ",
    "rdma ibv",
    "bluefield",
    "dpu network",
    "userspace network stack",
    "user-space network stack",
    "user space network stack",
    # 其他
    "proc/sys/net", "sysctl net", "rxhash", "kfunc",
    # AI 沙箱 / MicroVM 沙箱数据面
    # （这些虽不是源码符号，但论文摘要中只要提到通常都依赖内核网络能力，
    # 与 SmartNIC / kernel bypass 同等对待，作为硬锚点放行）
    "microvm",
    "microvm network",
    "firecracker",
    "firecracker network",
    "kata containers",
    "kata container",
    "cloud hypervisor",
    "qemu microvm",
    # AI 工作负载 GPU 直通 / SR-IOV 网络面（virtio/vfio 路径与内核网络栈交互）
    "vfio",
    "vfio mdev",
    "sriov vf",
    "sriov network",
    "rdma roce",
    "gpu passthrough network",
    # 沙箱网络隔离常用内核机制（netns+veth+eBPF 已在前文，这里补具体子项）
    "code interpreter sandbox",
    "agent sandbox",
    "ai sandbox",
    "llm sandbox",
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
MAX_NEWS = 10
MAX_CANDIDATES = 80
MIN_PAPERS_TARGET = 12
MIN_NEWS_TARGET = 4
ENABLE_NEWS = True

TECH_NEWS_RSS_FEEDS = [
    {
        "source": "Cloudflare Blog",
        "url": "https://blog.cloudflare.com/tag/networking/rss/",
        "limit": 4,
    },
    {
        "source": "Cilium Blog",
        "url": "https://cilium.io/blog/rss.xml",
        "limit": 4,
    },
]

TECH_NEWS_STRONG_TERMS = [
    "linux kernel", "linux network", "kernel network", "netdev", "ebpf", "bpf", "xdp",
    "cilium", "datapath", "cubic", "bbr", "congestion control", "tcp", "quic",
    "smartnic", "dpu", "dpdk", "rdma", "af_xdp", "napi", "qdisc", "netfilter",
    # AI 沙箱 / MicroVM 沙箱数据面
    "microvm", "firecracker", "kata", "cloud hypervisor", "code interpreter",
    "agent sandbox", "ai sandbox", "llm sandbox", "gpu passthrough", "sriov vf",
]

TECH_NEWS_REQUIRED_CONTEXT = [
    "network", "networking", "packet", "datapath", "tcp", "quic", "socket", "latency",
    "throughput", "performance", "kernel", "linux", "ebpf", "xdp", "cilium",
    # 沙箱 / AI 推理网络相关上下文
    "sandbox", "microvm", "firecracker", "kata", "virtio", "vhost", "vfio", "sriov",
    "rdma", "gpu passthrough",
]

PAPER_PROMPT = """你是 Linux 内核网络论文筛选与摘要专家。严格判断论文是否直接涉及 Linux 内核网络子系统（tcp/ip stack、netfilter、xdp、bpf、socket、net_device、virtio-net、napi、qdisc 等代码路径），或与之密切相关的旁路 / 硬件卸载高速网络研究。

判断维度（kernelNetworkScope）：
- kernel_internal: 论文直接修改 / 分析 / 评估 Linux 内核网络源码路径（如 sk_buff 处理、netfilter hook、qdisc 调度、XDP 数据面、virtio-net 驱动、napi 轮询、tcp 协议栈内部）。
- kernel_interface: 论文通过内核暴露的稳定接口（socket / netlink / setsockopt / tc / BPF hook / ip / ethtool）使用或扩展内核网络能力，但不深入内核源码。
- kernel_bypass_offload: SmartNIC offload / DPDK / RDMA / DPU / 用户态高速网络栈研究（如 SmartNIC-centric network stack、BlueField-3、off-path smartnic、hardware-offloaded network stack、microkernel-based baseline 等），通过旁路 / 卸载方式提供与内核网络并行的高速数据面。
- userspace_application: 论文聚焦用户态应用层 / 容器编排 / 微服务 / 虚拟机用户态应用（如 Kubernetes / Docker / Cilium 控制面、HTTP/gRPC 应用层、机器学习训练网络等），未触内核代码也未做高速网络栈研究。
- unrelated: 与 Linux 内核网络无关（其他 OS、应用层 ML/HTTP、IoT、传感器网络、推荐系统等）。

输出 JSON：
{"kernelNetworkScope": "kernel_internal|kernel_interface|kernel_bypass_offload|userspace_application|unrelated", "relevance": "high|medium|low|none", "reason": "20-50字简述判断依据", "summary": "中文总结220-400字", "tags": ["3-4个最重要标签"], "readingTime": 分钟数}

强约束：
1. relevance 必须与 kernelNetworkScope 一致：kernel_internal→high/medium；kernel_interface→medium/low；kernel_bypass_offload→medium/low；userspace_application→low；unrelated→none。
2. 若论文仅讨论 Kubernetes/Docker 等编排面或纯应用层网络，未触内核代码也未做高速网络栈研究，强制 userspace_application→low。
3. tags 数组最多 3-4 个最重要标签，不要过多。
4. summary 必须为基于摘要原文的真实总结，按自然段覆盖：研究问题/背景、核心方法或系统设计（必须具体到数据结构 / 算法 / 机制名称）、实验评估（数据集、对比基线、关键指标如吞吐 / 时延 / CPU 占用 / 丢包率）、与 Linux 内核网络 / 旁路高速网络的关系、读者应关注的限制或落地点。长度 220-400 字。
5. summary 严禁复述、引用或翻译论文标题；不要以 "《论文标题》"、"本文"、"该论文"、"这篇研究工作" 等开头提及标题；摘要开头直接陈述研究对象 / 问题。
6. summary 严禁使用空泛套话，包括但不限于："主要围绕"、"进行调整"、"实现与优化"、"建议重点关注"、"可重点关注"、"参考信息："、"相关的细节"、"问题定义、方法设计与性能影响"、"内容聚焦 Linux 内核网络场景"、"原文摘要信息有限"、"当前数据未提供足够摘要线索"、"归入"、"被归入"、"阅读时重点核对"、"摘要线索显示"。
7. summary 必须从摘要原文中提取具体名词（如 BBR、CUBIC、sk_buff、XDP、virtio-net、conntrack、tc、ethtool、NAPI、GRO/GSO、AF_XDP、BlueField-3、P4、PQC、SmartNIC、DPDK、RDMA 等）、具体数值（如 10Gbps、100us、2x throughput）、具体方法名 / 系统名，不能只给形容词描述。
8. 如果摘要原文信息不足，summary 必须直说 "原摘要未提供 X 信息"，禁止用模板化套话凑字数。

反例（禁止）：
"这篇研究工作《...》与eBPF、XDP、路由相关，内容聚焦 Linux 内核网络场景下的实现与优化。可重点关注其问题定义、方法设计与性能影响。参考信息：..."

正例（要求）：
"研究在多链路回传场景下评估 MPTCP 与 MPQUIC 在 eMBB / mMTC 混合流量下的拥塞控制行为。基于 Linux 内核 MPTCP 子系统构建实验床，对比 coupled / OLIA / BALIA 等拥塞控制算法在共享链路争用下的吞吐分配与队列堆积。结果显示 MPQUIC 在短流 mMTC 场景下延迟优于 MPTCP，但长流吞吐稳定性下降。该工作面向 5G 回传场景，不直接修改内核网络代码路径，仅通过 socket 层调用评估；对内核网络维护者的参考价值在于 MPQUIC / MPTCP 互操作边界与拥塞窗口共享机制的实测对比。"
"""

NEWS_PROMPT = """你是一个技术资讯筛选助手。严格分析文章是否与 Linux 内核网络、eBPF/XDP、内核网络性能、容器网络数据面、SmartNIC/DPU/DPDK/RDMA 等高速网络路径相关。

相关主题：Linux 网络子系统更新、网络性能优化、eBPF/XDP/Cilium 数据面、驱动/NIC/SmartNIC、内核旁路、netdev 讨论、容器网络中明确依赖内核网络能力的技术变化。
排除：泛云产品发布、纯安全营销、通用 Kubernetes 运维、HTTP/应用层服务、与 Linux 网络栈无直接关系的公司新闻。

返回JSON格式：
{"relevance": "high/medium/low/none", "summary": "中文总结120-240字，说明具体技术点和为什么值得关注，不要复述标题", "tags": ["3-4个最主要标签"], "readingTime": 分钟数}

注意：只有明确命中 Linux 网络/eBPF/XDP/SmartNIC/DPDK/RDMA/Cilium 数据面等技术点时才给 high/medium；tags数组最多包含3-4个最重要的标签，不要过多。"""

LWN_SUMMARY_PROMPT = """你是一个技术文章总结助手。请阅读LWN.net的文章内容，提取与Linux内核网络相关的重要信息。

返回JSON格式：
{"summary": "中文总结280-600字，覆盖背景、核心变化、实现机制、影响，不要过度压缩，不要复述标题", "keyPoints": ["按原文重要信息输出完整条目列表，数量不要人为限制，尽可能覆盖完整内容"], "tags": ["3-4个最主要标签"], "readingTime": 分钟数}

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


# ---------------- HTTP helper with rate-limit handling ----------------
def _parse_retry_after(headers):
    """Best-effort parse of Retry-After (delta-seconds or HTTP-date)."""
    if not headers:
        return 0
    raw = headers.get("Retry-After")
    if not raw:
        return 0
    raw = raw.strip()
    try:
        return max(0, int(raw))
    except ValueError:
        pass
    # HTTP-date form - rare for these APIs; fall back to 0.
    return 0


def _http_get(url, *, as_json=True, timeout=30, retries=3, base_delay=15,
              max_delay=120, source_name="http"):
    """GET helper with polite rate-limit handling.

    Behavior:
      * 429: honor Retry-After header if present, otherwise exponential
        backoff base_delay * 2^attempt (capped at max_delay).
      * 5xx: exponential backoff.
      * 4xx other than 429 (404/400/403/etc.): not retryable. 404 is
        logged silently (these APIs return 404 for empty/unknown queries);
        other 4xx are logged once.
      * Network / timeout errors: retry with exponential backoff.
    Returns parsed JSON (when as_json) or raw text on success, or None on
    persistent failure.
    """
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": APP_USER_AGENT,
                "Accept": "application/json" if as_json else "*/*",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if as_json:
                    return json.loads(raw)
                return raw
        except urllib.error.HTTPError as e:
            code = e.code
            last_err = f"HTTP {code} {e.reason}"
            # Non-retryable 4xx (404/400/403/410/...). 404 is silent.
            if 400 <= code < 500 and code != 429:
                if code != 404:
                    print(f"  [{source_name}] {code} {e.reason} (not retryable) url={url[:90]}")
                return None
            # 429 / 5xx: backoff
            retry_after = _parse_retry_after(e.headers) if code == 429 else 0
            if retry_after > 0:
                wait = min(retry_after, max_delay)
            else:
                wait = min(base_delay * (2 ** attempt), max_delay)
            print(f"  [{source_name}] {code} {e.reason}, backoff {wait}s (attempt {attempt + 1}/{retries})")
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout) as e:
            last_err = f"{type(e).__name__}: {e}"
            wait = min(base_delay * (2 ** attempt), max_delay)
            print(f"  [{source_name}] network error {last_err}, backoff {wait}s (attempt {attempt + 1}/{retries})")
            time.sleep(wait)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"  [{source_name}] unexpected error {last_err}")
            return None
    print(f"  [{source_name}] giving up after {retries} attempts: {last_err}")
    return None

def call_minimax(prompt, system_prompt, max_retries=5, max_tokens=500):
    global _MINIMAX_THROTTLE_UNTIL
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        print("Warning: MINIMAX_API_KEY not set")
        return None

    for attempt in range(max_retries):
        # Honor the process-wide throttle set by any worker that hit 429.
        with _MINIMAX_LOCK:
            wait_for = _MINIMAX_THROTTLE_UNTIL - time.time()
        if wait_for > 0:
            cap = min(wait_for, 90.0)
            print(f"  MiniMax shared throttle, waiting {cap:.1f}s (rate-limit backoff)")
            time.sleep(cap)
            continue

        try:
            payload = {
                "model": MINIMAX_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens
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

            with urllib.request.urlopen(req, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result.get("choices", [{}])[0].get("message", {}).get("content", "")

        except urllib.error.HTTPError as e:
            if e.code == 429:
                # Exponential backoff shared across all workers:
                # 15s, 30s, 60s, 120s, 120s (capped).
                wait_time = min(15 * (2 ** attempt), 120)
                print(f"  Rate limited (429), shared throttle {wait_time}s (attempt {attempt + 1}/{max_retries})")
                with _MINIMAX_LOCK:
                    _MINIMAX_THROTTLE_UNTIL = max(
                        _MINIMAX_THROTTLE_UNTIL,
                        time.time() + wait_time,
                    )
                time.sleep(wait_time)
            else:
                print(f"MiniMax API HTTP error: {e.code} {e.reason}")
                if attempt < max_retries - 1:
                    time.sleep(5 + 3 * attempt)
                else:
                    return None
        except Exception as e:
            print(f"MiniMax API error: {e}")
            if attempt < max_retries - 1:
                time.sleep(8 + 4 * attempt)
            else:
                return None

    return None

QUICK_FILTER_PROMPT = """你是 Linux 内核网络论文初筛助手。快速判断论文是否直接涉及 Linux 内核网络子系统（tcp/ip stack、netfilter、xdp、bpf、socket、net_device、virtio-net、napi、qdisc 等代码路径），或与之密切相关的旁路 / 硬件卸载高速网络研究。

严格标准：必须直接涉及 Linux 内核网络代码 / 实现，或属于 SmartNIC offload / DPDK / RDMA / DPU / 用户态高速网络栈等 kernel bypass 类研究，而非通用网络研究或纯应用层。

判断维度（kernelNetworkScope）：
- kernel_internal: 论文直接修改 / 分析 / 评估 Linux 内核网络源码路径。
- kernel_interface: 论文通过内核暴露的稳定接口（socket / netlink / tc / BPF hook / ethtool）使用或扩展内核网络能力，但不深入内核源码。
- kernel_bypass_offload: SmartNIC offload / DPDK / RDMA / DPU / 用户态高速网络栈研究（与内核网络并行的高速数据面）。
- userspace_application: 论文聚焦用户态应用层 / 容器编排 / 微服务（如 Kubernetes / Docker 控制面），未触内核代码也未做高速网络栈研究。
- unrelated: 与 Linux 内核网络无关。

输出 JSON：{"kernelNetworkScope": "kernel_internal|kernel_interface|kernel_bypass_offload|userspace_application|unrelated", "relevance": "high|medium|low|none"}
强约束：kernel_internal→high/medium；kernel_interface→medium/low；kernel_bypass_offload→medium/low；userspace_application→low；unrelated→none。"""

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
        result = parse_json_object(response)
        if result:
            scope = result.get('kernelNetworkScope', '')
            rel = result.get('relevance', 'none')
            return reconcile_relevance(scope, rel)
    except:
        pass

    return heuristic_relevance(title, abstract)

def reconcile_relevance(scope, relevance):
    """根据 LLM 给出的 kernelNetworkScope 强制校正 relevance。

    校正规则与 PAPER_PROMPT 中的强约束保持一致，避免 LLM 自身
    在 summary 中表述"无关"但 relevance 字段仍标 medium 的矛盾。
    """
    scope = (scope or '').strip().lower()
    relevance = (relevance or 'none').strip().lower()
    if relevance not in ('high', 'medium', 'low', 'none'):
        relevance = 'none'

    if scope == 'kernel_internal':
        return relevance if relevance in ('high', 'medium') else 'medium'
    if scope == 'kernel_interface':
        return relevance if relevance in ('medium', 'low') else 'low'
    if scope == 'kernel_bypass_offload':
        # SmartNIC offload / DPDK / RDMA / 用户态高速网络栈等
        # 旁路研究：放宽为 medium/low，不强制 low
        return relevance if relevance in ('medium', 'low') else 'medium'
    if scope == 'userspace_application':
        return 'low'
    if scope == 'unrelated':
        return 'none'
    # LLM 没给出 scope（news / 兜底场景）：保持原 relevance
    return relevance

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

def is_hard_excluded_reasoned(text):
    """与 is_hard_excluded 等价，但额外返回命中关键词用于诊断日志。

    返回 (bool, reason)。reason 形如 'hard-excluded:neural network'，未命中时为 ''。
    """
    text_lower = (text or "").lower()
    for keyword in HARD_EXCLUDE_KEYWORDS:
        if keyword in text_lower:
            return True, f"hard-excluded:{keyword}"
    return False, ""

def passes_domain_gate(title, abstract, source=""):
    merged = f"{title} {abstract}".lower()
    if is_hard_excluded(merged):
        return False

    if any(keyword in merged for keyword in NON_KERNEL_CONTEXT_KEYWORDS):
        if "linux" not in merged and "kernel" not in merged:
            return False

    # 硬锚点：必须命中至少 1 个内核专属词（KERNEL_SPECIFIC_TERMS）
    # + 1 个网络通用词，才认为可能真正涉及 Linux 内核网络代码。
    # 否则像 "tcp"/"socket" 这种通用词不应单独作为内核证据。
    kernel_specific_hit = any(term in merged for term in KERNEL_SPECIFIC_TERMS)
    network_hit = any(keyword in merged for keyword in NETWORK_ANCHOR_KEYWORDS)

    if not network_hit:
        return False

    if kernel_specific_hit:
        return True

    # LWN 文章 / 资讯可能描述内核讨论但 abstract 不含源码符号，保留例外：
    # 仅当 network_hit 成立，且 source 为 LWN 时放行进入 LLM 判断。
    if source == "LWN.net":
        return True

    # 论文类：无内核专属词一律挡下，由 LLM 再筛
    return False

def passes_domain_gate_reasoned(title, abstract, source=""):
    """与 passes_domain_gate 等价，但返回 (bool, reason)。

    reason 取值（仅在 False 时有意义）：
      - 'hard-excluded:<kw>'        命中 HARD_EXCLUDE 关键词
      - 'non-kernel-context'        命中 NON_KERNEL_CONTEXT 且无 linux/kernel 上下文
      - 'no-network-anchor'        缺 NETWORK_ANCHOR_KEYWORDS
      - 'no-kernel-anchor'         有 network 锚点但缺 KERNEL_SPECIFIC_TERMS
                                    （source 非 LWN.net 时挡下）
      - ''                          通过
    """
    merged = f"{title} {abstract}".lower()
    hard_hit, hard_reason = is_hard_excluded_reasoned(merged)
    if hard_hit:
        return False, hard_reason

    if any(keyword in merged for keyword in NON_KERNEL_CONTEXT_KEYWORDS):
        if "linux" not in merged and "kernel" not in merged:
            return False, "non-kernel-context"

    network_hit = any(keyword in merged for keyword in NETWORK_ANCHOR_KEYWORDS)
    if not network_hit:
        return False, "no-network-anchor"

    if any(term in merged for term in KERNEL_SPECIFIC_TERMS):
        return True, ""

    if source == "LWN.net":
        return True, "lwn-exception"

    return False, "no-kernel-anchor"

def passes_tech_news_gate(title, abstract, source=""):
    merged = f"{title} {abstract}".lower()
    if is_hard_excluded(merged):
        return False
    if any(keyword in merged for keyword in NON_KERNEL_CONTEXT_KEYWORDS):
        if not any(term in merged for term in ("linux", "kernel", "ebpf", "xdp", "cilium")):
            return False

    strong_hits = sum(1 for term in TECH_NEWS_STRONG_TERMS if term in merged)
    context_hits = sum(1 for term in TECH_NEWS_REQUIRED_CONTEXT if term in merged)
    source_bonus = 1 if source in ("LWN.net", "Cloudflare Blog", "Cilium Blog") else 0
    return strong_hits + source_bonus >= 2 and context_hits >= 2

def passes_news_domain_gate(title, abstract, source=""):
    return passes_domain_gate(title, abstract, source) or passes_tech_news_gate(title, abstract, source)

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

def is_generic_summary(text):
    generic_patterns = [
        "主要围绕",
        "进行调整",
        "实现与优化",
        "建议重点关注",
        "可重点关注",
        "参考信息：",
        "相关的细节",
        "问题定义、方法设计与性能影响",
        "内容聚焦 Linux 内核网络场景",
        "原文摘要信息有限",
        "当前数据未提供足够摘要线索",
        "归入",
        "被归入",
        "摘要线索显示",
        "阅读时重点核对",
        "摘要线索",
    ]
    normalized = (text or "").strip()
    if len(normalized) < 120:
        return True
    return any(pattern in normalized for pattern in generic_patterns) or re.search(r"被归入.*方向。摘要显示", normalized) is not None

def has_usable_abstract(abstract, title="", min_len=80):
    normalized = re.sub(r"\s+", " ", abstract or "").strip()
    normalized_title = re.sub(r"\s+", " ", title or "").strip()
    if not normalized:
        return False
    if normalized_title and normalized.lower() == normalized_title.lower():
        return False
    if normalized.lower().startswith("venue:"):
        return False
    words = re.findall(r"[A-Za-z0-9_+-]+", normalized)
    return len(normalized) >= min_len and len(words) >= 10

def _normalize_title_for_match(title):
    """Lowercase, collapse whitespace, strip bracket prefixes used in
    patch / paper titles, so that LLM summary openings like "研究了..."
    or "Research on ..." can be matched even when the summary dropped a
    colon or reordered words.
    """
    text = (title or "").strip().lower()
    # Drop leading [PATCH]/[RFC]/[net-next]/version prefixes
    text = re.sub(r"^\s*\[[^\]]*\]\s*", "", text)
    text = re.sub(r"^\s*\d+/\d+\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_title_from_summary(title, summary):
    """Remove the paper title from the beginning of `summary`.

    LLMs commonly start summaries with "《title》..." or "title: ..." or
    "这篇研究工作《title》..." — all of these echo the title verbatim
    and are not allowed per the prompt. This helper strips such
    openings so the published summary begins with content, not the
    title. We only strip a *prefix*; later mentions of the title inside
    the body are left alone to avoid corrupting technical statements.
    """
    cleaned = (summary or "").strip()
    normalized_title = (title or "").strip()
    if not cleaned or not normalized_title:
        return cleaned

    title_lower = _normalize_title_for_match(normalized_title)
    cleaned_lower = cleaned.lower().lstrip()

    # 1) Common LLM template openings that wrap the title verbatim.
    title_pattern = re.escape(normalized_title)
    title_pattern_lower = re.escape(title_lower)
    replacements = [
        # 这篇(研究工作|技术资讯)?《title》被归入(...)方向。摘要显示，其核心内容是:?
        (rf"^这篇(?:研究工作|技术资讯|论文|文章)?《{title_pattern}》被归入([^。]+)方向。摘要显示，其核心内容是[:：]?\s*", ""),
        # 这篇(研究工作|...)?《title》与(...)相关，
        (rf"^这篇(?:研究工作|技术资讯|论文|文章)?《{title_pattern}》与([^，。]+)相关，", ""),
        # 《title》归入(...)方向。
        (rf"^《{title_pattern}》归入([^。]+)方向。", ""),
        # 这篇(研究工作|...)《title》...（其他任意衔接）
        (rf"^这篇(?:研究工作|技术资讯|论文|文章)?《{title_pattern}》[:：，,。]?\s*", ""),
        # 《title》[:：，,。-]?
        (rf"^《{title_pattern}》[:：，,。\-—]?\s*", ""),
        # title[:：，,。-]? （裸标题开头）
        (rf"^{title_pattern}[:：，,。\-—]?\s*", ""),
        # "本文介绍了《title》" / "该论文《title》..." / "本研究《title》..."
        (rf"^(?:本文|该论文|本研究|这项研究|这项工作|这项论文|这篇论文)[:：,，]?\s*(?:介绍|提出|讨论|研究|分析|探索)?了?\s*《{title_pattern}》[:：，,。]?\s*", ""),
        (rf"^(?:本文|该论文|本研究|这项研究|这项工作|这项论文|这篇论文|本研究)[:：,，]?\s*(?:介绍|提出|讨论|研究|分析|探索)?了?\s*{title_pattern}[:：，,。\-—]?\s*", ""),
    ]
    for pattern, replacement in replacements:
        new_cleaned = re.sub(pattern, replacement, cleaned).strip()
        if new_cleaned != cleaned:
            cleaned = new_cleaned
            cleaned_lower = cleaned.lower().lstrip()

    # 2) Case-insensitive fallback: if the summary still starts with the
    # title verbatim (LLM may use different casing / spacing), strip it.
    if cleaned_lower.startswith(title_lower):
        cleaned = cleaned[len(title_lower):].lstrip(" :：，,。\\-—").strip()

    # 3) Strip a leading "本文 / 该论文 / 本研究 ..." connective if the
    # title was already removed above, so the summary starts with content.
    cleaned = re.sub(
        r"^(?:本文|该论文|本研究|这项研究|这项工作|这项论文|这篇论文|这篇研究工作|这篇技术资讯)[:：,，]?\s*(?:介绍|提出|讨论|研究|分析|探索|聚焦|围绕|总结|阐述|说明)?了?\s*[:：,，]?\s*",
        "",
        cleaned,
    ).strip()

    return cleaned

def extract_focus_terms(text, limit=6):
    candidates = []
    for keyword, tag in DOMAIN_KEYWORDS.items():
        if keyword in (text or "").lower() and tag not in candidates:
            candidates.append(tag)
        if len(candidates) >= limit:
            break
    return candidates

def extract_abstract_sentences(content, max_sentences=3):
    normalized = re.sub(r"\s+", " ", content or "").strip()
    if not normalized:
        return []
    pieces = re.split(r"(?<=[.!?])\s+", normalized)
    sentences = []
    for piece in pieces:
        clean = piece.strip()
        if len(clean) < 30:
            continue
        sentences.append(clean)
        if len(sentences) >= max_sentences:
            break
    if not sentences and normalized:
        sentences.append(normalized[:260])
    return sentences

def contains_chinese(text):
    if not isinstance(text, str):
        return False
    return re.search(r"[\u4e00-\u9fff]", text) is not None

def chinese_fallback_summary(title, content, tags, is_news=False):
    """Heuristic fallback when LLM is unavailable or returns a generic
    summary. Returns a clear Chinese hint instead of dumping the English
    abstract verbatim with a Chinese prefix ("原摘要要点：<english>"),
    which previously read like a bug rather than a deliberate fallback.
    The Phase 6.5 retry round in main() attempts to replace this with a
    real LLM-generated Chinese summary; if retry still fails, this hint
    stays and the reader falls back to summary_en.
    """
    if has_usable_abstract(content, title, min_len=60):
        return "⚠️ 此论文 AI 中文总结暂未生成（LLM 调用失败或被限流），请直接查看下方原文摘要。"
    return "原摘要信息不足，建议打开原文查看研究目标、方法与实验设置。"

def parse_json_object(response):
    if not response:
        return None
    start = response.find('{')
    end = response.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(response[start:end + 1])
    except json.JSONDecodeError:
        json_match = re.search(r'\{[^{}]+\}', response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                return None
    return None

def analyze_item_with_llm(title, content, is_news=False):
    prompt = f"""标题：{title}
内容：{content[:1800]}

请分析并返回JSON，tags最多3-4个。论文 summary 要具体说明主要内容、方法、评估结论和关注点。"""
    
    system_prompt = NEWS_PROMPT if is_news else PAPER_PROMPT
    response = call_minimax(prompt, system_prompt, max_tokens=700 if is_news else 1000)
    
    if not response:
        inferred_relevance = heuristic_relevance(title, content)
        return {
            "relevance": inferred_relevance if inferred_relevance != "none" else "low",
            "summary": chinese_fallback_summary(title, content, infer_tags(f"{title} {content}"), is_news=is_news),
            "tags": infer_tags(f"{title} {content}"),
            "readingTime": 3 if is_news else 5,
        }
    
    try:
        result = parse_json_object(response)
        if result:
            if 'tags' in result and len(result['tags']) > 4:
                result['tags'] = result['tags'][:4]
            if is_generic_summary(result.get('summary', '')):
                result['summary'] = chinese_fallback_summary(title, content, result.get('tags', []), is_news=is_news)
            # 用 kernelNetworkScope 强制校正 relevance，避免 LLM 自相矛盾
            scope = result.get('kernelNetworkScope', '')
            result['relevance'] = reconcile_relevance(scope, result.get('relevance', 'none'))
            return result
    except:
        pass

    inferred_relevance = heuristic_relevance(title, content)
    return {
        "relevance": inferred_relevance if inferred_relevance != "none" else "low",
        "summary": chinese_fallback_summary(title, content, infer_tags(f"{title} {content}"), is_news=is_news),
        "tags": infer_tags(f"{title} {content}"),
        "readingTime": 3 if is_news else 5,
    }

def fetch_arxiv_papers(query, max_results=8):
    papers = []
    print(f"  Waiting {ARXIV_DELAY}s for arXiv...")
    time.sleep(ARXIV_DELAY)

    # arXiv API 把空格当作 OR 分隔符，所以多 token query 必须显式
    # 用 AND 连接每个 all:token，否则只有第一个 token 受 all: 限定，
    # 命中量爆炸且召回质量极差。
    tokens = [t for t in query.split() if t]
    search_query = " AND ".join(f"all:{t}" for t in tokens) if tokens else f"all:{query}"

    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"

    data = _http_get(url, as_json=False, source_name="arXiv")
    if not data:
        return papers

    try:
        root = ET.fromstring(data)
    except Exception as e:
        print(f"  arXiv XML parse error: {e}")
        return papers

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

    return papers

def fetch_semantic_scholar_papers(query, max_results=8):
    papers = []
    random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)

    params = {
        "query": query,
        "limit": max_results,
        "year": f"{MIN_YEAR}-",
        "fields": "title,url,abstract,year",
    }
    url = f"{SEMANTIC_SCHOLAR_API}?{urllib.parse.urlencode(params)}"

    data = _http_get(url, source_name="S2")
    if not data:
        return papers

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
    return papers

def fetch_openalex_papers(query, max_results=8):
    papers = []
    random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)

    params = {
        "search": query,
        "filter": f"from_publication_date:{MIN_YEAR}-01-01,language:en",
        "per-page": max_results,
        "sort": "publication_date:desc",
    }
    url = f"{OPENALEX_API}?{urllib.parse.urlencode(params)}"
    data = _http_get(url, source_name="OpenAlex")
    if not data:
        return papers

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
    return papers

def fetch_crossref_papers(query, max_results=8):
    papers = []
    random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)

    params = {
        "query": query,
        "filter": f"from-pub-date:{MIN_YEAR}-01-01,type:journal-article",
        "rows": max_results,
        "sort": "published",
        "order": "desc",
    }
    url = f"{CROSSREF_API}?{urllib.parse.urlencode(params)}"
    data = _http_get(url, source_name="Crossref")
    if not data:
        return papers

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
    return papers

def fetch_dblp_papers(query, max_results=8):
    papers = []
    random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)

    params = {
        "q": query,
        "h": max_results,
        "format": "json",
    }
    url = f"{DBLP_API}?{urllib.parse.urlencode(params)}"
    data = _http_get(url, source_name="DBLP")
    if not data:
        return papers

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
    return papers

def fetch_openreview_papers(query, max_results=8):
    papers = []
    random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)

    params = {
        "query": query,
        "limit": max_results,
    }
    url = f"{OPENREVIEW_API}?{urllib.parse.urlencode(params)}"
    data = _http_get(url, source_name="OpenReview")
    if not data:
        return papers

    notes = data.get("notes", [])
    for note in notes:
        content = note.get("content", {})
        title = content.get("title", {}).get("value", "") if isinstance(content.get("title"), dict) else content.get("title", "")
        abstract = content.get("abstract", {}).get("value", "") if isinstance(content.get("abstract"), dict) else content.get("abstract", "")
        cdate = note.get("cdate", 0)
        try:
            year = datetime.fromtimestamp(cdate / 1000, tz=timezone.utc).year if cdate else 0
        except Exception:
            year = 0
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


def strip_html_to_text(html):
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html or '', flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.DOTALL)
    text = re.sub(r'<(p|br|li|h[1-6]|blockquote|div|tr|ul|ol)[^>]*>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_lib.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

def text_from_xml_node(node):
    if node is None or node.text is None:
        return ""
    return strip_html_to_text(node.text)

def find_xml_text(node, names):
    for name in names:
        found = node.find(name)
        text = text_from_xml_node(found)
        if text:
            return text
    for child in list(node):
        tag = child.tag.split('}', 1)[-1].lower()
        if tag in names:
            text = text_from_xml_node(child)
            if text:
                return text
    return ""

def find_xml_link(node):
    link = find_xml_text(node, ["link"])
    if link:
        return link
    for child in list(node):
        tag = child.tag.split('}', 1)[-1].lower()
        if tag == "link":
            href = child.attrib.get("href", "")
            if href:
                return href
    return ""

def fetch_tech_rss_news():
    news = []
    for feed in TECH_NEWS_RSS_FEEDS:
        source = feed["source"]
        try:
            print(f"  Fetching {source}...")
            random_delay(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
            req = urllib.request.Request(feed["url"], headers={"User-Agent": "CatNews/2.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                xml_text = response.read().decode("utf-8")

            root = ET.fromstring(xml_text)
            items = []
            for node in root.iter():
                tag = node.tag.split('}', 1)[-1].lower()
                if tag in ("item", "entry"):
                    items.append(node)

            source_items = []
            for item in items[: feed.get("limit", 4) * 3]:
                title = find_xml_text(item, ["title"])
                url = find_xml_link(item)
                abstract = find_xml_text(item, ["description", "summary", "content", "encoded"])
                if not abstract:
                    abstract = title
                if not title or not url:
                    continue
                if not passes_news_domain_gate(title, abstract, source):
                    continue
                source_items.append({
                    "title": title,
                    "url": url,
                    "abstract": abstract[:1200],
                    "source": source,
                })
                if len(source_items) >= feed.get("limit", 4):
                    break
            news.extend(source_items)
            print(f"    Found {len(source_items)} {source} items")
        except Exception as e:
            print(f"{source} fetch error: {e}")
    return news


def extract_lwn_article_text(html):
    if not html:
        return ""

    match = re.search(
        r'<div\s+class="ArticleText"[^>]*>(.*?)(?:<div\s+class="CommentBox"|<div\s+class="bottomnav"|</body>)',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if match:
        return strip_html_to_text(match.group(1))

    main_match = re.search(r'<main[^>]*>(.*?)</main>', html, flags=re.DOTALL | re.IGNORECASE)
    if main_match:
        return strip_html_to_text(main_match.group(1))

    return strip_html_to_text(html)


def _lwn_weekly_index_urls(url):
    """Return candidate URLs that usually contain the full weekly edition text.

    For weekly edition pages (Front page / Leading items / Brief items /
    Announcements) the actual long-form content lives in the per-page
    `bigpage` variant, or in the "Leading items" page of the same edition.
    """
    candidates = []
    stripped = url.rstrip("/")
    if not stripped:
        return candidates

    is_index = re.search(r"/Articles/\d+/?$", stripped) is not None
    if is_index:
        page = _lwn_fetch_html(stripped + "/bigpage")
        if page:
            candidates.append((stripped + "/bigpage", page))
        for offset in (1, 2, 3):
            lead = f"{stripped.rsplit('/', 1)[0]}/{int(stripped.rsplit('/', 1)[-1]) + offset}/"
            lead_page = _lwn_fetch_html(lead)
            if lead_page:
                candidates.append((lead, lead_page))
    elif not stripped.endswith("/bigpage"):
        page = _lwn_fetch_html(stripped + "/bigpage")
        if page:
            candidates.append((stripped + "/bigpage", page))
    return candidates


def _lwn_fetch_html(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CatNews/2.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        print(f"    Error fetching {url}: {e}")
        return None


def _lwn_is_weekly_index(html):
    if not html:
        return False
    head = re.search(r"<title>(.*?)</title>", html, flags=re.DOTALL | re.IGNORECASE)
    title = head.group(1).lower() if head else ""
    return any(token in title for token in (
        "weekly edition", "front page", "leading items", "brief items", "announcements"
    ))


def fetch_lwn_article_content(url):
    try:
        html = _lwn_fetch_html(url)
        if not html:
            return None

        is_free = is_lwn_free_article(html)
        text_content = extract_lwn_article_text(html)

        weekly_index = _lwn_is_weekly_index(html)
        too_short = len(text_content) < 1500

        resolved_url = url
        if (too_short or weekly_index) and not url.rstrip('/').endswith('/bigpage'):
            for candidate_url, candidate_html in _lwn_weekly_index_urls(url):
                candidate_text = extract_lwn_article_text(candidate_html)
                if len(candidate_text) > len(text_content):
                    text_content = candidate_text
                    is_free = is_lwn_free_article(candidate_html)
                    resolved_url = candidate_url

        return {
            "content": text_content[:14000],
            "is_free": is_free,
            "url": resolved_url,
        }
    except Exception as e:
        print(f"    Error fetching article content: {e}")
        return None

def summarize_lwn_article(title, content):
    prompt = f"""标题：{title}
内容：{content[:10000]}

请提取重要信息并返回JSON。"""
    
    response = call_minimax(prompt, LWN_SUMMARY_PROMPT, max_tokens=1800)
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
            resolved_url = article_data.get("url") or article['url']
            abstract_text = re.sub(r"\s+", " ", content).strip()
            summary_data = summarize_lwn_article(article['title'], content)
            if not summary_data:
                summary_data = analyze_item_with_llm(article['title'], content, is_news=True)

            if summary_data:
                news.append({
                    "title": article['title'],
                    "url": resolved_url,
                    "abstract": abstract_text[:1200],
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
    source_text = item.get("summary_en") or item.get("abstract") or item.get("summary") or ""
    fallback_source = source_text if has_usable_abstract(source_text, item.get("title", ""), min_len=60) else ""
    item["tags"] = normalize_tags(item.get("tags", []), max_tags=4)
    item["summary"] = ensure_non_empty_summary(
        item.get("summary", ""),
        chinese_fallback_summary(item.get("title", ""), fallback_source, item["tags"], is_news=is_news),
    )
    if not contains_chinese(item["summary"]) or is_generic_summary(item["summary"]):
        item["summary"] = chinese_fallback_summary(
            item.get("title", ""),
            fallback_source,
            item["tags"],
            is_news=is_news,
        )
    item["summary"] = strip_title_from_summary(item.get("title", ""), item["summary"])
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
    before_abstract_gate = len(paper_candidates)
    paper_candidates = [
        paper for paper in paper_candidates
        if has_usable_abstract(paper.get("abstract", ""), paper.get("title", ""))
    ]
    dropped_no_abstract = before_abstract_gate - len(paper_candidates)
    if dropped_no_abstract:
        print(f"  Dropped {dropped_no_abstract} paper candidates without usable abstracts")
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
        print("\n[Phase 4] Fetching curated Linux networking tech updates...")
        news_candidates.extend(fetch_lwn_news())
        news_candidates.extend(fetch_tech_rss_news())
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

            if not passes_news_domain_gate(item['title'], item.get('abstract', item['title']), item.get('source', '')):
                print("    -> excluded by domain gate")
                continue
            
            relevance = heuristic_relevance(item['title'], item.get('abstract', item['title']))
            if relevance == 'none' and passes_tech_news_gate(item['title'], item.get('abstract', item['title']), item.get('source', '')):
                relevance = 'medium'
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
            if not passes_news_domain_gate(item['title'], item.get('abstract', item['title']), item.get('source', '')):
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
                "summary_en": paper['abstract'][:600] + ("..." if len(paper['abstract']) > 600 else ""),
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
                "summary_en": paper['abstract'][:600] + ("..." if len(paper['abstract']) > 600 else ""),
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

    # Phase 6.5: Retry LLM for papers that fell into chinese_fallback_summary
    # (typically because the first call_minimax hit a transient 429 / timeout
    # while quick_filter phase was draining the MiniMax quota). A short
    # cool-off + spaced retries usually recovers real Chinese summaries
    # instead of leaving the ugly "⚠️ 此论文 AI 中文总结暂未生成..." hint.
    def _is_fallback_summary(s):
        s = (s or "").lstrip()
        return s.startswith("⚠️") or s.startswith("原摘要信息不足")

    fallback_papers = [p for p in selected_papers if _is_fallback_summary(p.get("summary", ""))]
    if fallback_papers:
        print(f"\n[Phase 6.5] Retrying LLM for {len(fallback_papers)} papers that fell into fallback...")
        time.sleep(25)
        retry_rounds = 2
        for round_idx in range(retry_rounds):
            if not fallback_papers:
                break
            print(f"  retry round {round_idx + 1}/{retry_rounds}: {len(fallback_papers)} papers left")
            still_failed = []
            for i, paper in enumerate(fallback_papers):
                print(f"  [{i+1}/{len(fallback_papers)}] {paper['title'][:50]}...")
                time.sleep(LLM_DELAY_MAX)
                retry_content = paper.get("summary_en", "") or paper.get("title", "")
                analysis = analyze_item_with_llm(paper["title"], retry_content, is_news=False)
                new_summary = (analysis or {}).get("summary", "")
                if new_summary and not _is_fallback_summary(new_summary):
                    paper["summary"] = new_summary
                    if analysis.get("tags"):
                        paper["tags"] = normalize_tags(analysis["tags"], max_tags=4)
                    paper["readingTime"] = analysis.get("readingTime", paper.get("readingTime", 5))
                paper["relevance"] = analysis.get("relevance", paper.get("relevance", "high"))
                paper = sanitize_item(paper, is_news=False)
                print(f"    ✓ retry succeeded (relevance={paper.get('relevance')})")
            else:
                print(f"    ✗ retry still failed; keeping fallback")
                still_failed.append(paper)
        fallback_papers = still_failed
        if fallback_papers and round_idx < retry_rounds - 1:
            wait_s = 45
            print(f"  cool-off {wait_s}s before next round...")
            time.sleep(wait_s)
    # Phase 6.5 收尾：retry 可能将 relevance 校正为 'none'（LLM 判定
    # kernelNetworkScope=unrelated，reconcile_relevance 强制改 none）。
    # Phase 6 主路径根本不会收录 relevance='none' 的论文，但 retry 在
    # 论文已加入 selected_papers 之后才更新 relevance，导致 'none' 论文
    # 仍留在结果里（如 2026-08-09 的 ATLAS HL-LHC I/O 论文）。在此统一
    # 清理，避免与 Linux 内核网络无关的论文被发布到首页。
    removed = [p for p in selected_papers if p.get("relevance") == "none"]
    if removed:
        for p in removed:
            print(f"  ✗ removing unrelated paper from selection: {p.get('title', '')[:60]}")
        selected_papers[:] = [p for p in selected_papers if p.get("relevance") != "none"]
    still_fallback = sum(1 for p in selected_papers if _is_fallback_summary(p.get("summary", "")))
    print(f"[Phase 6.5] done: kept {len(selected_papers)} (removed {len(removed)} unrelated, {still_fallback} still fallback)")
    
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
                and passes_news_domain_gate(item['title'], item.get('abstract', item['title']), item.get('source', ''))
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
                and passes_news_domain_gate(item['title'], item.get('abstract', item['title']), item.get('source', ''))
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

    # ---------- Lore kernel patches (yesterday) ----------
    try:
        script_dir_lore = os.path.dirname(os.path.abspath(__file__))
        if script_dir_lore not in sys.path:
            sys.path.insert(0, script_dir_lore)
        import fetch_lore_patches  # type: ignore
        yesterday_str = (beijing_now - timedelta(days=1)).strftime("%Y-%m-%d")
        fetch_lore_patches.run(
            docs_dir,
            yesterday_str,
            call_minimax_fn=call_minimax,
            gate_fn=passes_domain_gate_reasoned,
            excluded_fn=is_hard_excluded_reasoned,
            delay_min=LLM_DELAY_MIN,
            delay_max=LLM_DELAY_MAX,
            max_workers=4,
        )
    except Exception as e:
        print(f"[lore] skipped: {e}", flush=True)
    
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
