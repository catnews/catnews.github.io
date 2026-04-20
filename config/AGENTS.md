# Agent Skills 配置

## 目录结构

```
catnews.github.io/
├── docs/          # 存放生成的页面（markdown/html），由 AI agent 每日从论文数据库、Linux社区等站点获取信息后生成
├── config/        # 存放 skill 和配置文件
├── LICENSE
└── README.md
```

## 说明

- `docs/`: 用于存放 AI agent 生成的内容页面，可以是 markdown 或 html 格式
- `config/`: 存放 agent 运行所需的 skills 脚本和其他配置文件