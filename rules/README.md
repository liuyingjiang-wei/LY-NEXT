<div align="center">

# rules/

**给在本仓库写代码的 AI 助手与人类用的规则块**

[![Not Runtime](https://img.shields.io/badge/Runtime-Not_Loaded-64748b?style=plastic)](./README.md)

[← 返回 README](../README.md) · [AGENTS.md](../AGENTS.md)

</div>

---

> 本目录**不参与** ly-next 运行时，不会被 FastAPI / Agent 读取。

---

## 各文件读什么

| 文件 | 何时打开 |
|------|----------|
| `ly-next-project.mdc` | 任何改动：目录入口、加路由/工具、质量命令、配置来源 |
| `response-safety.mdc` | 删除数据、改鉴权、出站请求、执行命令、处理用户输入 |
| `api-trust-and-tools.mdc` | 动 `ly_next/apis/`、工具、`http_fetch`、MCP、`api.security_profile` |

更完整的威胁模型与生产清单 → [`SECURITY.md`](../SECURITY.md)；总索引 → [`AGENTS.md`](../AGENTS.md)。

---

## 和 Cursor 的关系

Cursor 默认常读 **`.cursor/rules/`**。若希望 IDE 自动带上本目录规则：

- 将 `.mdc` **复制或软链**到 `.cursor/rules/`，或
- 在 Cursor 项目规则里引用这些路径

本仓库保留 `rules/`，便于不依赖 Cursor 的协作者与 CI 文档引用。
