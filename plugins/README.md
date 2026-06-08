# LY-NEXT 插件（独立开发）

核心仓库 **不包含** 第三方或消息桥接插件源码。每人可在自己的仓库里开发插件，安装到本机后 Git 不会跟踪。

## 安装方式（三选一）

### 1. 放入 `plugins/local/`（最简单）

```bash
git clone https://github.com/you/ly-next-telegram-bot.git plugins/local/telegram_bot
# 或
git clone https://github.com/you/ly-next-qq-onebot.git plugins/local/qq_onebot
```

默认会扫描 `plugins/` 与 `plugins/local/`（见 `config/default_config.yaml` 的 `plugins.extra_dirs`）。  
这些目录已在根 `.gitignore` 中忽略，**提交 core 时不会带上插件**。

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

## 插件仓库最小结构

```
my_plugin/
├── pyproject.toml          # 可选，方式 2/3
├── README.md
├── .gitignore              # .env、__pycache__ 等
├── __init__.py
├── plugin.py               # 导出 plugin = MyPlugin()
└── ...                     # api、bridge、config 等
```

`plugin.py` 示例：

```python
from ly_next.core.plugin.protocol import LyNextPlugin

class MyPlugin(LyNextPlugin):
    name = "my-plugin"
    version = "0.1.0"
    description = "…"

plugin = MyPlugin()
```

实现 `register_tools` / `register_apis` / `register_bridges` 等见 `plugins/hello_plugin.py` 与 [LyNextPlugin 协议](../ly_next/core/plugin/protocol.py)。

## 配置与密钥

| 内容 | 位置 | 是否进 Git |
|------|------|------------|
| Bot Token、API Key | `.env` 或 `data/ly_next/config.yaml` | 否（已 ignore） |
| 插件源码 | `plugins/local/*` 或 venv 内 pip 包 | 否 |
| 示例单文件插件 | `plugins/hello_plugin.py` | 是（LyNextPlugin 演示） |
| 工具目录示例 | `tests/fixtures/sample_tool_plugin.py` | 否（仅供测试，勿放 `plugins/`） |

桥接类插件常用配置键：`bridge.onebot11.*`、`bridge.telegram.*`（写在各插件 README 中）。

## 开发 core 时提交 Git

```bash
git status  
git add ly_next/ tests/ www/ config/
```

只改插件时，在 **插件自己的仓库** 里 commit / push，不要在 ly-next 主仓库提交插件目录。

## 验证是否加载

```bash
uv run ly
# 或
curl -H "X-API-Key: …" http://127.0.0.1:8000/api/system/extensions
```

工作台 → **设置 → 基础设施** 可查看已加载插件列表。
