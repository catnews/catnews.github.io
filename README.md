# CatNews

CatNews 是一个基于 GitHub Pages 的学术内容精选站点，聚焦 Linux 内核网络方向的论文与期刊研究。

## 项目目标

- 聚合 Linux 内核网络相关论文、期刊与会议研究
- 对候选内容做自动筛选、摘要生成和标签归类
- 以静态页面形式展示，低成本部署与维护

## 项目结构

```text
catnews.github.io/
├── docs/                      # 每日数据输出目录（YYYY-MM-DD.json）
├── config/
│   ├── AGENTS.md              # 任务与领域规则说明
│   └── fetch_papers.py        # 内容抓取、筛选、摘要与输出脚本
├── .github/workflows/
│   └── fetch-papers.yml       # 定时执行抓取并自动提交结果
├── index.html                 # 前端静态页面
└── README.md
```

## 数据流

1. `fetch_papers.py` 从 arXiv / Semantic Scholar / OpenAlex / Crossref 抓取论文候选内容。
2. 对候选项执行去重、关键词打分、热点加权与领域硬门槛过滤。
3. 调用 LLM 生成中文摘要、相关性评级、标签与阅读时长。
4. 写入 `docs/YYYY-MM-DD.json` 并更新 `docs/.hashes.json`。
5. 同时输出 `docs/YYYY-MM-DD.metrics.json` 用于记录筛选质量指标。
6. `index.html` 按日期加载 JSON 并展示论文与标签统计。

## 数据来源（论文/期刊）

- `arXiv`：系统与网络方向预印本，更新快。
- `Semantic Scholar`：跨会议/期刊聚合，便于补充高相关候选。
- `OpenAlex`：学术索引数据源，覆盖期刊与会议论文。
- `Crossref`：DOI 元数据源，偏向正式发表论文（当前优先 `journal-article`）。

说明：资讯抓取默认开启（可通过脚本配置关闭），主流程优先保证论文与期刊研究质量。

## 当前筛选策略（已优化）

- **领域硬门槛**：必须同时满足“内核锚点 + 网络锚点”，并排除明显非内核网络语境内容。
- **两阶段筛选**：先快速过滤再精筛，降低无关内容进入最终结果的概率。
- **标签标准化**：同义标签统一映射为规范标签，减少统计噪声。
- **输出校验**：落盘前校验必填字段、类型和枚举值，避免脏数据写入。
- **中文总结兜底**：若 LLM 返回英文或空摘要，会自动生成中文可读摘要。

## 展示策略（已优化）

- **每日内容区**：按日期展示当天论文。
- **本周精选论文区**：固定展示最近 7 天内高匹配论文，缓解论文非日更导致的空档。

## 前端安全策略（已优化）

- 使用 DOM API + `textContent` 构建动态内容，避免直接拼接外部 HTML。
- 外链统一使用 `target="_blank"` + `rel="noopener noreferrer"`。

## 输出数据格式

示例：

```json
{
  "date": "2026-04-22",
  "categories": {
    "papers": [
      {
        "title": "...",
        "url": "...",
        "summary": "...",
        "summary_en": "...",
        "source": "arXiv",
        "tags": ["eBPF", "性能"],
        "readingTime": 5,
        "relevance": "high"
      }
    ],
    "news": []
  },
  "tagStats": {
    "eBPF": 2
  }
}
```

## 自动化任务

GitHub Actions 文件：`.github/workflows/fetch-papers.yml`

- 每天 UTC `02:00`（北京时间 `10:00`）自动运行
- 支持手动触发 `workflow_dispatch`
- 若 `docs` 目录有更新则自动提交

## 本地开发说明

### 1) 手动执行抓取

```bash
MINIMAX_API_KEY=your_key python config/fetch_papers.py
```

### 2) 本地查看页面

可使用任意静态文件服务器在仓库根目录启动，例如：

```bash
python -m http.server 8000
```

然后访问 `http://localhost:8000`。

## 后续优化建议

- 增加可配置白名单/黑名单词库，支持更细粒度领域控制。
- 为 `docs` 数据增加 Schema 文件，并在 CI 中独立校验。
- 引入简单质量报表（命中率、过滤率、标签分布变化）。
