<div align="center">

# LY-NEXT 安全说明

[![Security](https://img.shields.io/badge/Security-Review-2563eb?style=plastic)](./SECURITY.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat)](./LICENSE)

[← 返回 README](./README.md)

</div>

---

## 目录

- [威胁模型](#威胁模型默认假设)
- [高风险能力](#高风险能力)
- [鉴权与 Cookie](#鉴权与-cookie)
- [出站请求](#出站请求)
- [上线检查清单](#上线前检查清单)

---

本文描述**默认威胁模型**、动态 API / 工具 / 出站请求相关的**信任边界**，以及上线前**检查项**。实现细节以代码与配置为准。

---

## 威胁模型（默认假设）

| # | 假设 | 说明 |
|---|------|------|
| 1 | **运维与配置可信** | 能写 `config.yaml`、`ly_next/apis/`、环境变量者视为高权限 |
| 2 | **单进程身份** | Agent、工具、MCP、动态 API 同进程同 OS 用户执行 |
| 3 | **已认证调用方** | 持有 API Key / Cookie 的用户仍可能被模型诱导调用工具 |
| 4 | **第三方不可信** | 上游 LLM、远端 MCP 返回内容不做隐式信任 |

---

## 高风险能力

### 动态目录 API（`APILoader`）

从 `api.api_dir` 加载的 `.py` 在进程内执行，等价于**本地代码执行**。`api.auto_load: false` 时不加载。

| `api.security_profile` | 行为 |
|------------------------|------|
| `development`（默认） | `auto_load` 为真时加载目录模块 |
| `production` | **从不**从目录加载 |
| `verified` | 仅加载 `trusted_module_hashes` 中 SHA-256 匹配的文件；哈希表为空则不加载 |

`api.trusted_module_hashes`：键为**相对于 `api_dir` 的正斜杠路径**（如 `my_plugin.py`、`pkg/__init__.py`），值为小写十六进制 SHA-256。

**计算哈希（PowerShell）：**

```powershell
Get-FileHash -Algorithm SHA256 ly_next\apis\your_module.py
```

### 计算器工具

使用 **AST** 白名单解析，不再使用通用 `eval`（见 `ly_next/tools/math_safe.py`）。

---

## 鉴权与 Cookie

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `auth.allow_api_key_in_query` | `false` | 为 `true` 才允许 URL / WS / MCP 查询参数传 `api_key` |
| `auth.cookie_secure` | `false` | HTTPS 部署时设为 `true`（配合 `HttpOnly`、`SameSite=lax`） |
| `auth.whitelist` | — | 放行 `/docs`、`/api/health`、`/ly/login`、`/ly/static/*`；`/ly/` 与 `/api/*` 需登录 |

> 启动快照（`logger.py`）会在控制台**打印完整 `auth.api_key`**，生产环境注意终端与日志留存。

---

## 出站请求

### `http_fetch` 与 `web_fetch`

- **`http_fetch`**：原始 HTTP（状态码、头、正文），供 API/JSON 场景
- **`web_fetch`**：GET 后抽取主正文；入口 URL 做 SSRF 校验；默认 provider 为 **`jina`**
- **local / trafilatura / html** 路径走本地 httpx，与 `http_fetch` 类似的 `trust_env=False` 与重定向复验
- 出站客户端 **`trust_env=False`**：不因 `HTTP_PROXY` / `ALL_PROXY` 自动走系统代理
- 过滤模型/用户传入的 **Request Headers**：丢弃 `Host`、`Content-Length`、`X-Forwarded-*` 等
- 仅允许 `http`/`https`，对主机名做 SSRF 限制

### `web_scrape`

默认在 `tools.built_in` 中启用，但**未**做与 `http_fetch` 相同的 SSRF 校验，且 httpx **未**设 `trust_env=False`。生产环境若不需要，应从 `tools.built_in` 移除，或配合 `agent.tool_policy` 收紧 `network` 层工具。

### 本机 Redis（`core/cache.py`）

- 各平台启动 `redis-server` 均使用**参数列表、非 shell** 的 subprocess
- 自动拉起仅在非 Docker、非 production 环境下尝试

---

## 上线前检查清单

- [ ] `auth.enabled` 与强随机 `auth.api_key`；勿使用默认或弱密钥
- [ ] `auth.allow_api_key_in_query` 符合场景（默认 `false`）；HTTPS 下 `auth.cookie_secure: true`
- [ ] `api.security_profile` 为 `production` 或 `verified`（维护 `trusted_module_hashes`）
- [ ] `apis/`、配置目录对运行用户**只读**
- [ ] `cors.origins` 不用 `*`（尤其 Cookie 鉴权时）
- [ ] 密钥走环境变量或密钥管理；日志不对外暴露完整密钥
- [ ] 按需收紧 `agent.tool_policy` 与 `tools.built_in`（尤其 `web_scrape`、network 工具）

---

## 漏洞报告

若发现安全漏洞，**不要**在公开 Issue 中张贴可利用细节。请通过维护者私有渠道或 GitHub **Private vulnerability reporting** 说明影响范围与复现思路。

---

## 免责声明

安全取决于部署方式、网络环境与运维实践。本文不构成法律意见；生产环境请结合组织安全策略与渗透测试持续加固。
