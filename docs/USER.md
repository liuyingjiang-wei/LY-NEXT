# LY-NEXT 用户排障手册

面向自托管用户的**症状 → 原因 → 处理**速查。架构与接口见 [TECHNICAL.md](../TECHNICAL.md)；上手见 [README](../README.md) 与 [QUICKSTART.md](./QUICKSTART.md)。

---

## 登录与工作台

| 症状 | 常见原因 | 处理 |
|------|----------|------|
| 登录提示密钥错误 | `FIRST_RUN.txt` 与 `config.yaml` 中 `auth.api_key` 不一致 | 工作台「访问控制」一键同步，或运行 `uv run ly doctor` 查看提示 |
| 打开 `/ly` 空白或 404 | 未构建工作台静态资源 | 在项目根执行 `pnpm build:workbench`，确认存在 `www/app.html` |
| 顶部横幅「可对话：否」 | 默认 LLM 未配置或 API Key 仍为占位符 | 「模型配置」填写有效 Key / Ollama 地址，保存后看横幅是否变绿 |

---

## 智能对话

| 症状 | 常见原因 | 处理 |
|------|----------|------|
| 刷新后对话消失 | 未启用 PostgreSQL 或未开「同步」 | 启动 `docker compose`，对话页侧栏打开「同步：开」 |
| WebSocket 断开、回退 HTTP | 代理未透传 WS、网络抖动 | 看对话头「传输」徽章；检查反向代理 Upgrade 头 |
| 工具不执行 / 一直闲聊 | Agent 模式为 `chat` 或 tier 过低 | 场景菜单底部「Agent 预设」一键应用「工具助手」；或应用设置调 tier |
| host 命令无响应 | 需工作台审批 | tier=host 时到「访问控制 → 待审批操作」批准 |
| 思考很久无输出 | 推理模型或 coordinator | 属正常；可换更快模型或改用 `react` + 较小 `max_steps` |

### 对话里一键换 Agent 策略

1. 侧栏点 **场景** 打开菜单  
2. 底部 **全局 Agent 预设** 点 **应用**（自动写入 `config.yaml` 并热更新）  
3. 若匹配对话场景（如「工具助手」→「联网调研」），会自动切换当前会话场景  

移动端：**更多** → 选择对应「应用「xxx」」项。

---

## 模型配置

| 症状 | 常见原因 | 处理 |
|------|----------|------|
| OpenAI 兼容网关连不上 | `base_url` 填成了 LY-NEXT 自己的 `:8000` | 应填 Ollama/vLLM 等上游地址，不是本服务 |
| 工作台改了模型但 YAML 还有旧块 | 遗留 `openai_llm` / `ollama_llm` 与 `llm.models[]` 并存 | 以工作台「模型配置」为准；后续版本将提供 `ly config migrate` |
| Embedding / RAG 报错 | pgvector 未安装 | `CREATE EXTENSION IF NOT EXISTS vector;` 见 [QUICKSTART.md](./QUICKSTART.md) 路径② |

---

## QQ / Telegram 桥接

| 症状 | 常见原因 | 处理 |
|------|----------|------|
| QQ 无回复 | NapCat WS 未连上或未 @ | 「桥接总览」看 WS 状态；NapCat WebUI 配反向 WS 到 LY-NEXT |
| 配置已启用但插件未加载 | 未 clone 插件目录 | 「基础设施 → 插件」复制 `git clone` 命令，重启 `uv run ly` |
| Telegram 待配对 | `dm_policy=pairing` | 「Telegram 桥接」批准配对码 |

---

## 插件与依赖

| 症状 | 常见原因 | 处理 |
|------|----------|------|
| `doctor` 报插件缺失 | `bridge.*.enabled` 为 true 但目录空 | 按 `plugins/catalog.json` 安装到 `plugins/local/` |
| Redis / PG 横幅一直黄 | 可选依赖未起 | 可忽略（仅本地会话）；要持久化则 `docker compose up -d` |

---

## 长期记忆 MEMORY.md

- 路径默认：`agent.memory.path`（常为 `MEMORY.md`，相对数据目录）  
- 在 **智能体进阶 → 长期记忆** 启用 `memory.enabled`  
- Agent 通过 `remember_fact` 等工具写入；文件需对运行用户可写  

---

## 升级与变更

见项目根目录 [CHANGELOG.md](../CHANGELOG.md)。升级后建议：

```bash
uv sync
pnpm build:workbench   # 若使用内置工作台
uv run ly doctor
```

---

## 仍无法解决？

1. `uv run ly doctor` 全文复制  
2. 相关配置段（脱敏 API Key）  
3. 复现步骤与 Tab/场景名称  

到项目 Issues 反馈。
