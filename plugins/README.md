# LY-NEXT 插件（独立开发）

核心仓库 **不包含** 第三方插件源码。每人可在自己的仓库里开发插件，安装到本机后 Git 不会跟踪。

官方工作台 **插件管理** 页列出目录中的插件槽位（见 `catalog.json`，含 QQ / Telegram 桥接），**不包含官方托管仓库** — 请填写 **一个 Git 仓库地址**（`plugins.git_clone.repo_url`），并可配置本机代理或镜像加速后复制克隆命令。其它能力插件由第三方自行分发。

## 插件类型

| 类型 | 说明 | 官方目录示例 |
|------|------|----------------|
| **桥接** | 接入外部 IM，注册 `register_bridges` | `qq-onebot` · `telegram-bot` · `wechat-oc` |
| **能力** | HTTP 路由 + Agent 工具 + 可选 OneBot 指令 | 第三方自行发布 |
| **示例** | core 自带演示 | `plugins/hello_plugin.py` |

桥接常用配置键：`bridge.onebot11.*`、`bridge.telegram.*`、`bridge.wechat_oc.*`。  
能力插件可在 `data/ly_next/config.yaml` 用 `plugins.<name>` 覆盖，或使用插件自有数据目录（`data/<plugin_name>/`）。

---

## 安装方式（三选一）

### 1. 放入 `plugins/local/`（最简单）

在工作台 **插件管理** 填写 Git 仓库地址，配置代理或镜像加速后复制克隆命令，或在项目根目录手动执行（目标目录由 URL 自动推断，一般为 `plugins/local/<repo名>/`）：

```bash
# 示例：克隆到 plugins/local/qq_onebot（以工作台显示的命令为准）
git clone <你的仓库地址> plugins/local/qq_onebot
# 第三方能力插件：按其 README clone 到 plugins/local/<name>/
```

默认会扫描 `plugins/` 与 `plugins/local/`（见 `config/default_config.yaml` 的 `plugins.extra_dirs`）。  
这些目录已在根 `.gitignore` 中忽略，**提交 core 时不会带上插件**。

若插件有额外 pip 依赖，在其目录执行 `uv pip install -r requirements.txt`（路径以插件 README 为准）。

### 2. pip 可编辑安装 + `plugins.modules`

在插件仓库根目录：

```bash
pip install -e .
```

在 **已被 Git 忽略的** `data/ly_next/config.yaml` 中：

```yaml
plugins:
  modules:
    - telegram_bot.plugin
    - qq_onebot.plugin
    - my_capability_plugin.plugin
```

模块名以你插件包的实际 import 路径为准（例如 `my_plugin.plugin`）。

### 3. pip 包 + entry point（适合发布）

插件 `pyproject.toml`：

```toml
[project]
name = "ly-next-my-plugin"
dependencies = ["ly-next"]

[project.entry-points."ly_next.plugins"]
my-plugin = "my_plugin.plugin:plugin"
```

安装后无需写 `plugins.modules`，启动时自动发现（`plugins.entry_points: true`）。

---

## 插件仓库最小结构

```
my_plugin/
├── pyproject.toml          # 可选，方式 2/3
├── README.md
├── requirements.txt        # 可选，额外 pip 依赖
├── .gitignore
├── __init__.py
├── plugin.py               # 导出 plugin = MyPlugin()
└── ...                     # api、bridge、service、tools 等
```

`plugin.py` 示例：

```python
from ly_next.core.plugin.protocol import LyNextPlugin

class MyPlugin(LyNextPlugin):
    name = "my-plugin"
    version = "0.1.0"
    description = "…"

    def register_tools(self, registry, ctx):
        ...

    def register_apis(self, api_registry, ctx):
        ...

plugin = MyPlugin()
```

实现钩子见 `plugins/hello_plugin.py` 与 [LyNextPlugin 协议](../ly_next/core/plugin/protocol.py)。

### OneBot 指令扩展（非桥接插件）

桥接由 `qq-onebot` 提供 WS 连接；其它插件可注册群/私聊指令，在自动回复之前处理：

```python
from ly_next.messaging.onebot_commands import register_onebot_command_handler

def handle_custom_command(ctx):
    ...

register_onebot_command_handler(handle_custom_command, priority=50)
```

实现细节见 `ly_next/messaging/onebot_commands.py`。

---

## 配置与密钥

| 内容 | 位置 | 是否进 Git |
|------|------|------------|
| Bot Token、API Key | `.env` 或 `data/ly_next/config.yaml` | 否（已 ignore） |
| 插件源码 | `plugins/local/*` 或 venv 内 pip 包 | 否 |
| 插件运行时数据 | `data/<plugin_name>/` 等 | 否 |
| 示例单文件插件 | `plugins/hello_plugin.py` | 是（LyNextPlugin 演示） |

---

## 开发 core 时提交 Git

```bash
git status
git add ly_next/ tests/ www/ config/ README.md TECHNICAL.md docs/
```

只改插件时，在 **插件自己的仓库** 里 commit / push，不要在 ly-next 主仓库提交 `plugins/local/` 目录。

---

## 验证是否加载

```bash
uv run ly --no-prompt
curl -H "X-API-Key: …" http://127.0.0.1:8000/api/system/extensions
```

工作台 → **设置 → 基础设施** 可查看已加载插件列表（含桥接状态、工具数）。

---

## 官方桥接插件索引

| 目录（本地安装） | `name` | 类型 |
|------------------|--------|------|
| `plugins/local/qq_onebot/` | `qq-onebot` | 桥接 |
| `plugins/local/telegram_bot/` | `telegram-bot` | 桥接 |
| `plugins/local/wechat_oc/` | `wechat-oc` | 桥接（微信 iLink 扫码） |

第三方能力插件不在此列表；安装后同样出现在 `GET /api/system/extensions`，但请阅读其独立文档。
