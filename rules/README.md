# rules/

给 **在本仓库里写代码的 AI 助手与人类** 用的规则块（**不参与** ly-next 运行时，不会被 FastAPI / Agent 读取）。

## 各文件读什么

| 文件 | 何时打开 |
|------|----------|
| `ly-next-project.mdc` | 任何改动：目录入口、怎么加路由/工具、质量命令、配置从哪来。 |
| `response-safety.mdc` | 涉及删除数据、改鉴权、改出站请求、执行命令、处理用户输入时。 |
| `api-trust-and-tools.mdc` | 动 `ly_next/apis/`、工具、`http_fetch`、MCP、或 `api.security_profile` 时。 |

更完整的威胁模型与生产清单见仓库根目录 **`SECURITY.md`**；总索引见 **`AGENTS.md`**。

## 和 Cursor 的关系

Cursor 默认常读 **`.cursor/rules/`**。若希望 IDE 自动带上本目录规则，可将本目录中的 `.mdc` **复制或软链**到 `.cursor/rules/`，或在 Cursor 项目规则里引用这些路径。本仓库仍保留 `rules/`，便于不依赖 Cursor 的协作者与 CI 文档引用。
