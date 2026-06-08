# LY-NEXT Web 工作台重构规格（填写模板）

> **用途**：按 8 个维度定义重构目标，填完后可作为实施依据。  
> **现状快照**（2026-06）：源码在 `.workbench-src/src/`（gitignore），构建产物输出 `www/`；React 18 + Vite 7；入口 `home` / `app` / `login` / `firefly`；工作台 16 个 Tab，组件与样式均为扁平单目录。  
> **Agent 宪法**：前端实施永久遵循 [`rules/workbench-frontend-constitution.mdc`](../rules/workbench-frontend-constitution.mdc)（框架官方规范、组件库优先、禁止重复手写组件）。

**填写说明**：将 `[待填写]` 替换为你的决策；保留 `（可选）` 段落可删；勾选框用 `[x]` / `[ ]`。

---

## 1. 视觉风格（整体设计基调）

### 1.1 品牌定位

| 项 | 填写 |
|---|---|
| 产品气质关键词（3–5 个） | `专业运维，略带克制的科技感` 例：专业运维 / 开发者工具 / 克制科技感 |
| 参考产品或站点（附链接） | `https://mimo.xiaomi.com/mimo-v2-5，claude ai` 例：Linear、Vercel Dashboard、自建 Firefly 页 |
| 明确不要的风格 | `过度液态玻璃，过度ai模板` 例：过度玻璃拟态、花哨粒子、AI 模板紫渐变 |

### 1.2 视觉语言

| 项 | 填写 |
|---|---|
| 主色 / 强调色 | `崩坏星穹铁道角色流萤配色，且适配我的项目` 当前 `--wb-accent: #5e6ad2`，是否保留？ |
| 明暗模式策略 | `[1]` 保留双主题 `[ ]` 仅暗色 `[ ]` 仅亮色 `[ ]` 跟随系统 |
| 圆角尺度（sm / md / lg） | `自己适配` 当前 6 / 8 / 12px |
| 阴影与层次 | `引入好看的体系` 当前几乎无阴影，是否引入 elevation 体系？ |
| 动效原则 | `GSAP` GSAP / Motion 保留范围；`prefers-reduced-motion` 是否强制降级？ |

### 1.3 页面级差异

| 页面 | 与工作台关系 | 填写 |
|---|---|---|
| `/` 首页 `home` | `是` 是否独立视觉体系？ |
| `/ly/` 工作台 `app` | `信息疏松一点，侧栏风格简约一点` 信息密度、侧栏风格 |
| `/ly/login` | `不用，创建一个暗色主题的登录页面，页面中央有一个可交互的台灯 SVG 装饰和一个登录表单。
台灯交互逻辑：
1、台灯有一根可拖拽的拉绳，用 GSAP Draggable 实现。拖拽距离超过 50px 时触发开关切换
2、拉绳拉动时用 GSAP MorphSVGPlugin 制作绳子弹动动画
3、拉绳时播放一个"咔哒"音效
4、台灯切换时，灯光颜色随机变换（随机 hue 值），整个页面配色通过 CSS 变量 --on 和 --shade-hue 联动响应
5、灯关闭时台灯眼睛朝下（rotate 180°），开启时眼睛朝上（rotate 0°）
登录表单：
默认隐藏（opacity: 0，scale 缩小），台灯开启时以弹簧动画（cubic-bezier 弹性曲线）淡入并放大出现
表单边框和阴影使用台灯当前随机颜色，营造"灯光照亮表单"的视觉效果
包含：标题"欢迎回来"、账号输入框、密码输入框、登录按钮、"忘记密码？"链接
输入框获焦时显示彩色发光边框
页面整体：
背景色 #121921 深夜色
台灯和登录表单横向并排居中，flex 布局，响应式换行
页面底部显示日期和作者署名` 是否与工作台统一？ |
| `firefly` 营销/展示页 | `保留并搜索流萤这个角色完善展示页` 保留 / 合并 / 下线 |

### 1.4 关键界面截图或草图（可选）

```
[待填写：粘贴链接或附件路径]
- 目标侧栏 + 主内容布局
- 智能对话页目标态
- 设置表单页目标态
```

---

## 2. 技术方案（核心架构选型）

### 2.1 基础栈（勾选确认）

- [1] **保留** React 18 + Vite 7 多入口构建（`home` / `app` / `login` / `firefly`）
- [1] **保留** 构建输出到 `www/`，`base: /ly/static/`
- [1] **引入** TypeScript（迁移策略：`渐进` 全量 / 渐进 / 仅新代码）
- [ ] **引入** 路由库（`[待填写]` 无 / React Router / TanStack Router）— 当前 Tab 由 URL `?tab=` + state 驱动
- [ ] **引入** 全局状态（`[待填写]` 无 / Zustand / Jotai / Context only）
- [ ] **引入** 数据请求层（`[待填写]` 保留 `apiClient.js` / 加 TanStack Query / SWR）

### 2.2 与后端集成约定

| 项 | 填写 |
|---|---|
| API 基址 | `默认` 默认相对路径 `/api` |
| 鉴权方式 | Cookie + `X-API-Key`（沿用 `/ly/login`） |
| WebSocket | `chatTransport.js` 优先 WS，失败回退 HTTP — 是否重构为统一 transport 层？ `[待填写]` |
| 设置读写 | `GET/PATCH /api/system/settings` + `settings_effects` 热更新提示 — 表单抽象策略 `[待填写]` |
| 类型来源 | `手写types` 手写 types / 从 OpenAPI `/docs` 生成 |

### 2.3 构建与发布

| 项 | 填写 |
|---|---|
| 包管理器 | pnpm（当前 `packageManager: pnpm@10.33.2`） |
| 开发命令 | `pnpm dev:workbench` |
| 生产构建 | `pnpm build:workbench` → `scripts/sync_www_assets.py` |
| `.workbench-src/` 是否入仓 | `[1]` 继续 gitignore `[ ]` 提交源码（推荐重构后入仓） |
| CI 检查项 | `自己决定` lint / typecheck / build / 视觉回归 |

### 2.4 非目标（明确不做）

```
[待填写]
例：不拆独立前端仓库、不引入 Next.js、工作台不做 SSR
```

---

## 3. UI 组件库（标准化组件选型）

### 3.1 组件库决策

| 方案 | 选择 | 说明 |
|---|---|---|
| 引入完整组件库 | `[mui和ant design]` | 例：shadcn/ui、Ant Design、MUI — 写明理由 |

**最终选择**：`Ant Design 6`（桌面端）；**移动端（≤980px）** 使用 **`Ant Design Mobile 5`** 作为触控适配层，主题色与 tokens 与桌面流萤配色一致，不得混用 MUI 等第三套 UI 库。

> ⚠️ 本节选型为 **Agent 宪法** 依据：见 `rules/workbench-frontend-constitution.mdc`。

### 3.2 组件分层定义

| 层级 | 职责 | 命名前缀（建议） | 示例（对照现状） |
|---|---|---|---|
| Primitives | 按钮、输入、标签、开关 | `Ui` / `Base` | 从 `settingsForm.jsx` 抽离 |
| Patterns | 设置卡片、保存栏、空状态、加载 | `Pattern` | `SettingsConfigHeader` |
| Features | 业务面板 | 按 feature 目录 | `ChatPanel`、`ModelSettingsPanel` |
| Shell | 侧栏、Tab、布局、横幅 | `Shell` / `Layout` | `App.jsx` 内联部分 |

### 3.3 必要组件清单（勾选需要的）

**表单与反馈**
- [ ] Button（primary / secondary / ghost / danger）
- [ ] Input / Textarea / Select / Switch / Checkbox
- [ ] FormField（label + hint + error）
- [ ] SaveBar（保存 / 重置 / `settings_effects` 提示）
- [ ] Toast / InlineAlert / Banner（`SystemStatusBanner` 归哪类？`[待填写]`）

**数据展示**
- [ ] Table / DataList
- [ ] CodeBlock / JSON viewer（API 调试 Tab）
- [ ] Sparkline / Ring（`App.jsx` 运行概览图表）
- [ ] Timeline（`ChatToolTimeline`）

**导航**
- [ ] Sidebar + NavItem + 折叠态
- [ ] Tabs（工作台 16 Tab）
- [ ] Breadcrumb（是否需要 `[待填写]`）

**对话专用**
- [ ] MessageList / MessageBubble
- [ ] Composer（`ChatComposer`）
- [ ] ThinkBlock（推理过程折叠）
- [ ] ToolCallCard

### 3.4 装饰性组件去留

| 现状组件 | 去留 | 理由 |
|---|---|---|
| `LiquidGlass` | `[保留/简化/移除]` | `移除` |
| `Fireflies` / `Particles` / `Lightfall` | `[保留/仅首页/移除]` | `移除` |
| `OrbitImages` | `保留但美化` | |
| GSAP `ScrollReveal` 系 | `移除` | |

---

## 4. 目录结构（工程目录规范）

### 4.1 目标目录树（在 `.workbench-src/` 下）

> 将 `[?]` 改为你确认的文件夹名；删除不需要的分支。

```
.workbench-src/
├── index.html / app.html / home.html / login.html / firefly.html
├── vite.config.js
├── public/
└── src/
    ├── app/                    # 工作台壳（原 App.jsx 拆分）
    │   ├── App.jsx
    │   ├── tabs.config.js      # 16 个 Tab 元数据
    │   └── hooks/
    ├── pages/                  # 多入口页面薄包装
    │   ├── home/
    │   ├── login/
    │   └── firefly/
    ├── features/               # 按业务能力切分
    │   ├── chat/               # ChatPanel, ChatComposer, transport...
    │   ├── settings/           # SettingsPanel + 子表单逻辑
    │   ├── models/
    │   ├── rag/
    │   ├── mcp/
    │   ├── infrastructure/
    │   ├── security/
    │   ├── observability/
    │   ├── runs/
    │   ├── bridges/            # qq + telegram
    │   ├── image/
    │   ├── api-explorer/       # 接口调试
    │   └── tasks/
    ├── components/             # 跨 feature 复用
    │   ├── ui/                 # Primitives
    │   ├── patterns/
    │   └── shell/              # Sidebar, Panel, TabLoading
    ├── lib/                    # 无 UI 的工具
    │   ├── api/                # apiClient, ws client
    │   ├── storage/            # chatStorage, loginStorage, theme
    │   └── format/             # pretty JSON 等
    ├── styles/
    │   ├── tokens.css          # CSS 变量
    │   ├── themes/             # light / dark
    │   ├── global.css
    │   └── features/           # 按 feature 拆 css（可选）
    └── assets/                 # 图标、静态图
```

### 4.2 文件迁移对照表（必填）

> 把现有扁平文件映射到新位置，避免 refactor 时遗漏。

| 现有文件 | 目标路径 | 备注 |
|---|---|---|
| `App.jsx` | `[待填写]` | 壳 + 运行概览是否拆出 |
| `ChatPanel.jsx` | `[待填写]` | |
| `settingsShared.js` | `[待填写]` | |
| `settingsForm.jsx` | `[待填写]` | |
| `app.css`（5000+ 行） | `[待填写]` | 如何拆分 |
| `apiClient.js` | `[待填写]` | |
| … | | 自行补充其余 70+ 文件 |

### 4.3 命名与导入规范

| 规则 | 填写 |
|---|---|
| 组件文件 | `[待填写]` PascalCase.jsx / .tsx |
| hooks | `[待填写]` useXxx.js |
| 路径别名 | `[待填写]` `@/` → `src/`（是否在 vite 配置） |
|  barrel export | `[ ]` 每个 feature 用 index.js 导出 `[ ]` 禁止 barrel |

---

## 5. 模块边界（功能解耦定义）

### 5.1 垂直切片（Feature 边界）

每个 feature 对外只暴露 **入口 Panel + 可选 hooks**；禁止 feature 间直接 import 内部子组件。

| Feature ID | 入口组件 | 独占状态/API | 可依赖的共享模块 |
|---|---|---|---|
| `status` | 运行概览（现嵌在 App） | `GET /api/system/readiness`、metrics | `lib/api`, `components/ui` |
| `chat` | `ChatPanel` | WS 事件流、thread 同步 | `lib/api`, `chatStorage` |
| `settings` | `SettingsPanel` | `patchSettings`、agent presets | `settingsShared`, `settingsForm` |
| `models` | `ModelSettingsPanel` | `/api/models` | `[待填写]` |
| `rag` | `RagSettingsPanel` | RAG 试检索 API | `[待填写]` |
| `infra` | `InfrastructureSettingsPanel` | `/api/system/extensions` | `[待填写]` |
| `security` | `SecuritySettingsPanel` | 安全相关 settings 键 | `[待填写]` |
| `agent_adv` | `AgentAdvancedSettingsPanel` | `[待填写]` | |
| `observability` | `ObservabilitySettingsPanel` | `[待填写]` | |
| `runs` | `RunsHistoryPanel` | `/api/runs` | `[待填写]` |
| `mcp` | `McpSettingsPanel` | MCP 配置 | `[待填写]` |
| `image` | `ImageSettingsPanel` | 识图预描述配置 | `[待填写]` |
| `qq` | `QqBridgeSettingsPanel` | bridge.onebot11 | `[待填写]` |
| `telegram` | `TelegramBridgeSettingsPanel` | bridge.telegram | `[待填写]` |
| `api` | API 调试（现嵌在 App） | OpenAPI 路由列表 | `[待填写]` |
| `tasks` | 任务调度（现嵌在 App） | `/api/tasks` | `[待填写]` |

### 5.2 壳（App Shell）职责边界

**壳负责：**
- [ ] 侧栏与 Tab 路由（`?tab=`）
- [ ] 主题切换（`themePreference.js`）
- [ ] 移动端视口与侧栏折叠
- [ ] 懒加载 Panel + `Suspense` 占位
- [ ] 顶部 `SystemStatusBanner` / `OnboardingWizard` 挂载点

**壳不负责：**
```
[待填写]
例：不直接调用 patchSettings；不内联 Sparkline/Ring 业务逻辑
```

### 5.3 跨模块共享数据

| 数据 | 来源 | 共享方式 | 填写 |
|---|---|---|---|
| 主题 | localStorage | `[待填写]` Context / CSS only |
| API Key 登录态 | Cookie | `[待填写]` |
| settings 元数据 | `/api/system/settings` | 每 Panel 自拉取 vs 全局 store — `[待填写]` |
| readiness | `/api/system/readiness` | Banner 独占 vs 全局 — `[待填写]` |

### 5.4 与后端的契约文档

```
[待填写：列出每个 feature 依赖的 API 端点清单，或指向 OpenAPI tag]
```

---

## 6. 复用规则（组件公用逻辑）

### 6.1 设置类 Panel 统一模式

现状：多个 `*SettingsPanel` 重复 loading/saving/msg/err + `settingsShared`。

| 抽象项 | 是否提取 | 命名建议 | 填写 |
|---|---|---|---|
| `useSettingsForm(keys)` hook | `[ ]` | | `[待填写]` |
| `<SettingsPage layout>` 布局 | `[ ]` | header + sections + save bar | `[待填写]` |
| `hydrate` / `pick` 工具 | 已有 `settingsShared.js` | 迁到 `lib/settings/` | `[待填写]` |
| 密钥字段脱敏展示 | `[ ]` | | `[待填写]` |
| `settings_effects` 保存后提示 | `[ ]` | | `[待填写]` |

### 6.2 列表/表格类复用

```
[待填写]
例：Runs 历史、模型列表、插件列表是否共用 DataTable + 空状态
```

### 6.3 对话模块复用

| 模块 | 复用范围 | 填写 |
|---|---|---|
| `chatTransport.js` | HTTP + WS 统一接口 | `[待填写]` |
| `chatThreadSync.js` | 仅 chat feature | |
| `chatTranslate.js` | 可选能力 | `[待填写]` |
| `MessageActions` | 消息级操作 | |

### 6.4 Hooks 提取规则

**何时提取 hook：**
```
[待填写]
例：同一逻辑在 2+ Panel 出现；涉及订阅/清理的副作用
```

**禁止：**
```
[待填写]
例：feature 专属 hook 不要放到 global hooks 除非 2+ feature 使用
```

### 6.5 图标与文案

| 项 | 填写 |
|---|---|
| 图标方案 | 现状 `icons.jsx` — `[待填写]` 保留内联 SVG / Lucide / 其他 |
| 中文文案集中管理 | `[ ]` 需要 i18n 文件 `[ ]` 继续组件内硬编码 |
| Tab 标签与描述 | 统一在 `tabs.config.js` — `[待填写]` |

---

## 7. 样式系统（全局视觉规范）

### 7.1 Design Tokens（CSS 变量）

> 从 `app.css` `:root` 抽离到 `styles/tokens.css`。

| Token 组 | 变量示例 | 是否调整 | 填写 |
|---|---|---|---|
| 颜色-品牌 | `--wb-accent` | | `[待填写]` |
| 颜色-语义 | `--wb-success`, `--wb-error` | | `[待填写]` |
| 颜色-表面 | `--wb-main-panel`, `--wb-sidebar-*` | | `[待填写]` |
| 间距 | `--wb-layout-gap`, `--wb-layout-pad` | | `[待填写]` |
| 圆角 | `--wb-radius-*` | | `[待填写]` |
| 动效 | `--motion-sidebar`, `--motion-fade` | | `[待填写]` |
| 布局 | `--sidebar-width` | | `[待填写]` |

### 7.2 主题实现

| 项 | 填写 |
|---|---|
| 切换机制 | `data-theme` on `:root`（现状）— 是否保留 |
| 存储键 | `themePreference.js` / `THEME_PREF_KEY` |
| 组件内联硬编码色 | 清查策略 `[待填写]` 例：禁止新增 hex，仅允许 var() |

### 7.3 CSS 组织策略

- [ ] **方案 A**：Tailwind CSS 引入，逐步替换 `wb-*`
- [ ] **方案 B**：保留纯 CSS + BEM `wb-*`，按 feature 拆文件
- [ ] **方案 C**：CSS Modules per component

**选择**：`[待填写]`  
**`app.css` 拆分计划**：`[待填写]` 例：shell 800 行 / chat 1200 行 / settings 900 行 …

### 7.4 响应式与无障碍

| 断点 | 行为 | 填写 |
|---|---|---|
| mobile | `mobileViewport.js` 侧栏抽屉 | `[待填写]` |
| reduced-motion | `motionPrefs.js` | `[待填写]` |
| 焦点环 / 键盘 | `[待填写]` WCAG 目标级别 |
| 字号缩放 | `[待填写]` |

### 7.5 与装饰动画的样式隔离

```

Firefly 页专用 firefly.css，不污染工作台 token
```

---

## 8. 实施计划（开发迭代排期）

### 8.1 里程碑

| 阶段 | 目标 | 产出 | 预估 | 完成标准 |
|---|---|---|---|---|
| **P0 基线** | 规格冻结 + 目录脚手架 | 本文档填完、空目录、vite 别名 | `[待填写]` | `pnpm build:workbench` 通过 |
| **P1 样式/token** | 抽 tokens、壳布局 | `styles/tokens.css`、Shell 组件 | `[待填写]` | 明暗主题无回归 |
| **P2 组件库** | Primitives + Settings 模式 | `components/ui/*`、`useSettingsForm` | `[待填写]` | 迁移 1 个 SettingsPanel 试点 |
| **P3 核心 feature** | chat + settings + models | features 目录落地 | `[待填写]` | 对话 WS/HTTP 正常 |
| **P4 长尾 feature** | bridges / runs / mcp / api 调试 | 全部 Tab 迁移 | `[待填写]` | 16 Tab 功能对等 |
| **P5 清理** | 删旧文件、app.css 瘦身、文档 | 源码入仓决策 | `[待填写]` | 无死代码；**不**改 README（仅 `www/` 对外说明） |

### 8.2 迁移策略

- [ ] **绞杀者**：新目录并行，逐 Tab 切换，最后删旧文件
- [ ] **大爆炸**：停功能开发，集中迁移（风险高，需写明回滚点）

**选择**：`[待填写]`

### 8.3 每阶段验证清单

```bash
# 构建
pnpm build:workbench

# 本地预览（按需）
pnpm preview:workbench

# 后端联调
uv run ly
# 浏览器：/ly/login → /ly/?tab=chat → 各设置 Tab 保存
```

**人工回归重点：**
```
[待填写]
- [ ] 登录 Cookie 与 API Key 请求头
- [ ] 智能对话 WS 流式 + think_chunk 折叠
- [ ] settings 保存与 settings_effects 提示
- [ ] 移动端侧栏
- [ ] 暗色主题
```

### 8.4 风险与回滚

| 风险 | 缓解 | 填写 |
|---|---|---|
| `app.css` 拆分遗漏样式 | 按 Tab 截图对比 | `[待填写]` |
| WS 行为变化 | 保留 `chatTransport` 集成测试 | `[待填写]` |
| 构建产物路径变化 | `sync_www_assets.py` 契约 | `[待填写]` |

**回滚策略**：`[待填写]` 例：保留 `www/` 上一版 tag 可一键恢复

### 8.5 分工（可选）

| 负责人 | 范围 |
|---|---|
| `[待填写]` | 视觉 + tokens |
| `[待填写]` | Shell + 组件库 |
| `[待填写]` | chat feature |
| `[待填写]` | settings + models 系 |

---

## 附录 A：现状 Tab 一览（供填写时对照）

| tab id | 标签 | 主要组件 |
|---|---|---|
| `status` | 运行概览 | 内嵌于 `App.jsx` |
| `chat` | 智能对话 | `ChatPanel` |
| `infra` | 基础设施 | `InfrastructureSettingsPanel` |
| `security` | 访问控制 | `SecuritySettingsPanel` |
| `settings` | 应用设置 | `SettingsPanel` |
| `models` | 模型配置 | `ModelSettingsPanel` |
| `rag` | 文档检索 | `RagSettingsPanel` |
| `agent_adv` | 智能体进阶 | `AgentAdvancedSettingsPanel` |
| `observability` | 运行观测 | `ObservabilitySettingsPanel` |
| `runs` | 执行轨迹 | `RunsHistoryPanel` |
| `mcp` | MCP 协议 | `McpSettingsPanel` |
| `image` | 图像服务 | `ImageSettingsPanel` |
| `qq` | QQ 桥接 | `QqBridgeSettingsPanel` |
| `telegram` | Telegram 桥接 | `TelegramBridgeSettingsPanel` |
| `api` | 接口调试 | 内嵌于 `App.jsx` |
| `tasks` | 任务调度 | 内嵌于 `App.jsx` |

## 附录 B：填写优先级建议

1. **先填 §1 视觉 + §7 样式** — 避免迁移后返工  
2. **再填 §5 模块边界 + §4 目录** — 确定怎么拆  
3. **然后 §3 组件库 + §6 复用规则** — 确定抽象深度  
4. **最后 §2 技术方案 + §8 排期** — 锁定执行路径  

---

*文档版本：0.1 skeleton · 生成后请自行改版本号*
