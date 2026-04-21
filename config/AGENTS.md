# CatNews Agent 配置指南

## 项目概述

CatNews 是一个基于 GitHub Pages 的每日论文精选网站，专注于 Linux 内核网络相关的研究论文。

**仓库地址**: `~/workspace/code/catnews.github.io`

## 目录结构

```
catnews.github.io/
├── docs/                    # 存放每日论文数据 (JSON格式)
│   └── YYYY-MM-DD.json      # 按日期命名的数据文件
├── config/                  # 存放 agent 配置和脚本
│   ├── AGENTS.md            # Agent 配置指南（本文件）
│   └── fetch_papers.py      # 论文检索脚本（Python）
├── .github/workflows/       # GitHub Actions 自动化
│   └── fetch-papers.yml     # 每日自动运行 workflow
├── index.html               # 网站主页
├── LICENSE
└── README.md
```

## 论文检索要求

### 目标领域
专注于 **Linux 内核网络子系统** 相关研究，包括：

- **核心主题**:
  - Linux TCP/IP 协议栈实现与优化
  - Linux Socket API 与性能
  - Linux 网络子系统架构
  - Linux 路由与转发机制
  - Linux 网桥 与虚拟网络

- **高级特性**:
  - eBPF/XDP 数据包处理
  - Netfilter/nftables 防火墙框架
  - Kernel Bypass (DPDK, user-space networking)
  - Virtio/vHost 虚拟化网络
  - Linux 网络驱动开发

### 排除范围
以下内容**不属于**检索范围：
- 通用网络协议研究（不涉及 Linux 内核实现）
- 纯应用层网络编程
- 其他操作系统的网络实现
- 与 Linux 内核网络无关的 eBPF 应用（如安全、监控）

### 数据源
- **arXiv**: 计算机系统领域论文
- **Semantic Scholar**: 期刊、会议论文索引

### 年份要求
仅收录 **2020年及之后** 发表的论文。

## 数据格式

每篇论文包含以下字段：

```json
{
  "title": "论文标题",
  "url": "论文链接",
  "summary": "中文总结（AI生成，150-300字）",
  "summary_en": "英文摘要原文",
  "source": "arxiv 或 Semantic Scholar",
  "tags": ["eBPF", "XDP", "性能"],
  "readingTime": 5,
  "relevance": "high/medium/low"
}
```

### 标签定义

| 标签 | 关键词 |
|------|--------|
| eBPF | ebpf, bpf, extended bpf, berkeley packet filter |
| XDP | xdp, express data path |
| 旁路 | bypass, kernel bypass, dpdk, user-space networking |
| TCP/IP | tcp/ip, tcp congestion, protocol stack |
| Socket | socket, socket api, unix socket |
| Netfilter | netfilter, iptables, nftables |
| 路由 | routing, routing table, forwarding |
| 网桥 | bridge, linux bridge, bridging |
| 驱动 | driver, nic driver, ethernet driver, network device driver |
| 包处理 | packet processing, skb, sk_buff |
| 虚拟化 | virtio, vhost, sriov, virtual networking |
| 性能 | performance, optimization, latency, throughput |

## Agent 工作流程

### 当前状态
- [x] 网站页面搭建完成
- [x] GitHub Actions 自动化配置完成
- [x] 标签筛选功能完成
- [ ] 论文质量筛选需要改进（当前自动化脚本筛选精度不足）

### 待改进任务

#### 1. 论文筛选机制改进
**问题**: 当前 Python 脚本仅基于关键词匹配，导致大量无关论文被收录。

**改进方案**:
- AI agent 直接参与筛选过程
- 查看论文摘要/正文后判断相关性
- 手动生成中文总结
- 评估实际阅读时长

#### 2. 如何执行手动筛选
当 agent 被触发运行时：
1. 调用 `fetch_papers.py` 获取候选论文列表
2. 逐篇分析每篇论文的摘要内容
3. 判断是否属于 Linux 内核网络领域
4. 为相关论文生成中文总结
5. 估算阅读时长（基于摘要长度和内容深度）
6. 输出到 `docs/YYYY-MM-DD.json`

## GitHub Actions 配置

Workflow 每日北京时间 10:00 自动运行：
- Cron: `0 2 * * *` (UTC 02:00 = 北京时间 10:00)
- 时区设置: `TZ: Asia/Shanghai`
- 支持手动触发: `workflow_dispatch`

## 历史数据去重

脚本会加载 `docs/` 目录下所有历史 JSON 文件，提取论文标题哈希，避免重复收录同一论文。

## 注意事项

1. 时区问题：所有日期使用北京时间 (UTC+8)
2. Node.js 版本：GitHub Actions 已设置 `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true`
3. 写权限：Workflow 需要 `permissions: contents: write`
4. 数据完整性：每篇论文必须有 `title`, `url`, `summary`, `source` 字段