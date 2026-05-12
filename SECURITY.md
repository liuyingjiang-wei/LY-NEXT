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

从 `api.api_dir` 加载的 `.py` 会在服务进程内执行，等价于**本地代码执行**。

| `api.security_profile` | 行为 |
|------------------------|------|
| `development`（默认） | `api.auto_load` 为真时加载目录下模块。 |
| `production` | **从不**从目录加载 API 模块（即使 `api.auto_load` 为真）。 |
| `verified` | 仅加载 `api.trusted_module_hashes` 中列出且 **SHA-256** 匹配的文件。 |

`api.trusted_module_hashes`：键为**相对于 `api_dir` 的正斜杠路径**（如 `my_plugin.py`、`pkg/__init__.py`），值为小写十六进制 SHA-256。

**计算哈希（PowerShell）：** `Get-FileHash -Algorithm SHA256 ly_next\apis\your_module.py`

### 计算器工具

已不再使用通用 `eval`；使用 **AST** 白名单解析（见 `ly_next/tools/math_safe.py`）。

### 鉴权与 Cookie

- **`auth.allow_api_key_in_query`**（默认 **`false`**）：为 `true` 时，才允许从 URL 查询参数读取 `api_key`（HTTP 与 **WebSocket `/api/ws*`、MCP WS** 一致）。默认关闭，避免 Key 进入访问日志、Referer；仅本机调试需要时可临时改为 `true`。  
- **`auth.cookie_secure`**（默认 `false`）：全站 **HTTPS** 时设为 **`true`**，为登录 Cookie 加上 `Secure`。

### 工具 `http_fetch`

- 出站客户端 **`trust_env=False`**：不因进程环境里的 `HTTP_PROXY` / `ALL_PROXY` 等自动走系统代理，降低被恶意环境变量劫持出站的风险（若业务需要代理，应在代码或显式客户端配置中单独支持）。  
- 对模型/用户传入的 **Request Headers** 做过滤：丢弃 `Host`、`Content-Length`、`X-Forwarded-*` 等可影响路由或链路的头，减少误用与部分绕过面。  
- 仍仅允许 `http`/`https`，并对解析后的主机名做 SSRF 方向限制；重定向后的最终 URL 会再次校验。

### 本机拉起 Redis（`core/cache.py`）

- Windows 上启动 `redis-server` 已改为 **参数列表 + 非 shell** 的 `subprocess.Popen`，避免 `shell=True` 拼接命令带来的注入面。

## 生产环境检查清单

- [ ] `auth.enabled` 与强随机 `auth.api_key`；生产勿依赖默认或弱密钥。  
- [ ] 确认 `auth.allow_api_key_in_query` 是否符合场景（默认已 `false`）；全站 HTTPS 时 `auth.cookie_secure: true`。  
- [ ] `api.security_profile` 为 `production` 或 `verified`；`verified` 时维护 `trusted_module_hashes`。  
- [ ] `apis/`、配置目录对运行用户**只读**。  
- [ ] `cors.origins` 不用 `*`（尤其在使用 Cookie 鉴权时）。  
- [ ] 密钥走环境变量或密钥管理；日志不打印完整密钥与敏感请求体。  
- [ ] 按需收紧 `agent.tool_policy` 与 `tools.built_in`。

## 漏洞报告

若你认为发现了安全漏洞，请**不要**在公开 Issue 中张贴可利用细节。建议通过仓库维护者提供的**私有渠道**说明影响范围与复现思路；若仓库已开启 GitHub **Private vulnerability reporting**，请使用该入口提交。

## 免责声明

安全取决于部署方式、网络环境与运维实践。本文不构成法律意见；生产环境请结合组织安全策略与渗透测试结果持续加固。
