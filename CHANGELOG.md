# Changelog

本文件记录面向用户的版本变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [Unreleased]

### Added

- `uv run ly config migrate`：合并 legacy LLM 块、修正错误的 compat Base URL、清理 `*_llm` 遗留键
- 智能对话页「仅本机浏览器保存」提示条（导出备份 / 跳转基础设施）
- 配置预设 API（minimal / standard / full_stack）与依赖横幅可执行操作
- 侧栏分组搜索、对话场景生效配置 chips、传输状态徽章
- 桥接总览 Tab、桥接插件槽位与 Git 克隆加速设置、doctor 缺插件检查
- 对话内 **Agent 预设一键应用并保存**（场景菜单 / 移动端「更多」）
- 工具时间线收起/展开、host tier 审批提示
- 用户排障手册 [`docs/USER.md`](docs/USER.md)
- 设置热更新矩阵：`SettingsSection` 生效标注 + `GET /api/system/settings/apply-guide`
- 侧栏「我想…」快捷入口（模型 / 安全 tier / MCP / 桥接 / RAG 等）
- 智能对话「生效配置一页纸」折叠面板（含跳转链接）
- MCP 向导添加（HTTP / stdio 表单 + `POST /api/system/mcp/preflight` 连接测试）
- 桥接一站式安装向导（插件 → 配置 → 验证）
- 运行概览「可选依赖」信息卡片（PG / Redis / pgvector 非告警态）
- 侧栏独立 **插件管理** Tab（统一 Git 仓库地址克隆、代理/镜像加速，不再藏在基础设施深处）
- 运行概览 **环境诊断（ly doctor）** 面板与 `POST /api/system/doctor/fix` 一键修复
- 对话页活动状态条（工具轮次 / 推理 / 传输方式）与侧边栏存储备份卡片

### Changed

- 默认 LLM 改为 **Ollama**（零 API Key 可试聊）；修正 `openai_compat` 默认 Base URL
- 顶部状态横幅仅在 LLM / 登录密钥异常时提示，PostgreSQL / Redis 可选依赖不再常驻黄条
- 入门引导入口与侧栏导航对齐，统一图标与页脚布局
- 应用设置场景预设支持「应用并保存」按钮
- compat 引擎选项移至「智能体进阶」；工具时间线展示失败原因、轮次与 spill 路径
- host tier 与 production 安全策略启用前二次确认；待审批批准需双击确认

### Fixed

- 插件目录 API 缩进问题
- 设置页搜索区块 JSX 条件渲染

---

## [1.0.1] - Alpha

初始 Alpha 打包版本。详见 [README.md](README.md) 与 [docs/QUICKSTART.md](docs/QUICKSTART.md)。
