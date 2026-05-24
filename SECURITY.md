# LY-NEXT 安全说明

本文描述**默认威胁模型**、与动态 API 加载 / 工具 / 出站请求相关的**信任边界**，以及上线前建议的**检查项**。实现细节以代码与配置为准。

## 威胁模型（默认假设）

1. **运维与配置文件可信**  
   能写 `data/ly_next/config.yaml`（或 `LY_NEXT_CONFIG_DIR`）、能写应用目录、`ly_next/apis/` 以及环境变量的一方，视为与高权限用户等价。

2. **应用进程身份**  
   Agent、工具、MCP 桥、从 `api_dir` 加载的 Python 模块均在**同一进程、同一 OS 用户**下执行。任何被加载的代码具备该用户的文件与网络能力（受系统防火墙等约束）。

3. **调用方**  
   启用 `auth` 后，持有合法 API Key / 登录 Cookie 的调用方被视为**已认证用户**，仍不应等同于「完全可信代码」：模型可能被诱导发起工具调用，因此工具与出站请求需按业务再做收敛。

4. **第三方模型与 MCP**  
   上游 LLM、远端 MCP 服务视为**不可信输入源**；对其返回内容不做隐式信任，敏感操作应放在额外审批或独立服务中。

## 高风险能力（已加强或需配置）

### 动态目录 API（`APILoader`）

从 `api.api_dir` 加载的 `.py` 会在服务进程内执行，等价于**本地代码执行**。`api.auto_load: false` 时所有 profile 均不加载。

| `api.security_profile` | 行为 |
|------------------------|------|
| `development`（默认） | `api.auto_load` 为真时加载目录下模块。 |
| `production` | **从不**从目录加载 API 模块（即使 `api.auto_load` 为真）。 |
| `verified` | 仅加载 `api.trusted_module_hashes` 中列出且 **SHA-256** 匹配的文件；哈希表为空则不加载任何模块。 |

`api.trusted_module_hashes`：键为**相对于 `api_dir` 的正斜杠路径**（如 `my_plugin.py`、`pkg/__init__.py`），值为小写十六进制 SHA-256。

**计算哈希（PowerShell）：** `Get-FileHash -Algorithm SHA256 ly_next\apis\your_module.py`

### 计算器工具

已不再使用通用 `eval`；使用 **AST** 白名单解析（见 `ly_next/tools/math_safe.py`）。

### 鉴权与 Cookie

- **`auth.allow_api_key_in_query`**（默认 **`false`**）：为 `true` 时，才允许从 URL 查询参数读取 `api_key`（HTTP 与 **WebSocket `/api/ws*`、MCP WS** 一致）。默认关闭，避免 Key 进入访问日志、Referer；仅本机调试需要时可临时改为 `true`。  
- **`auth.cookie_secure`**（默认 `false`）：全站 **HTTPS** 时设为 **`true`**，为登录 Cookie 加上 `Secure`（配合 `HttpOnly`、`SameSite=lax`）。  
- **`auth.whitelist`**：默认放行 `/docs`、`/api/health`、`/ly/` 等静态页；**`/api/*` 仍受鉴权**。  
- 启动快照（`logger.py`）会在控制台**打印完整 `auth.api_key`**，生产环境注意终端与日志留存。

### 工具 `http_fetch` 与 `web_fetch`

- **`http_fetch`**：原始 HTTP 请求（状态码、头、正文），供 API/JSON 等场景。  
- **`web_fetch`**：GET 后抽取页面主正文；入口 URL 做 SSRF 校验。默认 provider 为 **`jina`**（第三方 API）；**local / trafilatura / html** 路径走本地 httpx，与 `http_fetch` 类似的 `trust_env=False` 与重定向后复验。  
- 出站客户端 **`trust_env=False`**（`http_fetch` 与 `web_fetch` 本地路径）：不因进程环境里的 `HTTP_PROXY` / `ALL_PROXY` 等自动走系统代理。  
- 对模型/用户传入的 **Request Headers** 做过滤：丢弃 `Host`、`Content-Length`、`X-Forwarded-*` 等可影响路由或链路的头。  
- 仍仅允许 `http`/`https`，并对解析后的主机名做 SSRF 方向限制。

### 工具 `web_scrape`

默认在 `tools.built_in` 中启用，但**未**做与 `http_fetch` 相同的 SSRF 校验，且 httpx **未**设 `trust_env=False`。生产环境若不需要，应从 `tools.built_in` 移除，或配合 `agent.tool_policy` 收紧 `network` 层工具。

### 本机拉起 Redis（`core/cache.py`）

- 各平台启动 `redis-server` 均使用 **参数列表、非 shell** 的 subprocess，避免命令拼接注入。  
- 自动拉起仅在非 Docker、非 production 环境下尝试。

## 生产环境检查清单

- [ ] `auth.enabled` 与强随机 `auth.api_key`；生产勿依赖默认或弱密钥。  
- [ ] 确认 `auth.allow_api_key_in_query` 是否符合场景（默认已 `false`）；全站 HTTPS 时 `auth.cookie_secure: true`。  
- [ ] `api.security_profile` 为 `production` 或 `verified`；`verified` 时维护 `trusted_module_hashes`。  
- [ ] `apis/`、配置目录对运行用户**只读**。  
- [ ] `cors.origins` 不用 `*`（尤其在使用 Cookie 鉴权时）。  
- [ ] 密钥走环境变量或密钥管理；日志与启动快照不对外暴露完整密钥。  
- [ ] 按需收紧 `agent.tool_policy` 与 `tools.built_in`（尤其 `web_scrape` 等 network 工具）。

## 漏洞报告

若你认为发现了安全漏洞，请**不要**在公开 Issue 中张贴可利用细节。建议通过仓库维护者提供的**私有渠道**说明影响范围与复现思路；若仓库已开启 GitHub **Private vulnerability reporting**，请使用该入口提交。

## 免责声明

安全取决于部署方式、网络环境与运维实践。本文不构成法律意见；生产环境请结合组织安全策略与渗透测试结果持续加固。
