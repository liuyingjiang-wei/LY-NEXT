<div align="center">

# 扩展 HTTP API 插件

**用户自定义 `.py` 插件 · 由 `APILoader` 启动时扫描加载**

[![Plugin](https://img.shields.io/badge/Type-BaseAPI_Plugin-6366f1?style=for-the-badge)](./README.md)
[![Security](https://img.shields.io/badge/Security-Security_Profile-2563eb?style=flat-square)](../../SECURITY.md)

[← 返回 README](../../README.md) · [AGENTS.md](../../AGENTS.md)

</div>

---

## 目录

- [与内置路由的区别](#与内置路由的区别)
- [加载约定](#加载约定)
- [安全说明](#安全说明)

---

## 与内置路由的区别

| 类型 | 位置 | 说明 |
|------|------|------|
| **内置路由** | `ly_next/api/` | `ly_api.py`、`ws_api.py` 等，随应用注册 |
| **插件 API** | `ly_next/apis/`（本目录） | 用户 `.py`，由 `APILoader` 按配置扫描 |

---

## 加载约定

- 默认配置 **`api.api_dir`** 指向本目录
- 每个插件可导出 **`default: dict`** 或 **`BaseAPI`** 实例 → 详见 [`ly_next/api/base.py`](../api/base.py)
- 加载模块名 **`ly_next_plugin_<stem>`**，避免与内置包冲突
- `__init__.py` 仅 re-export `BaseAPI`，便于：

```python
from ly_next.apis import BaseAPI
```

---

## 安全说明

动态目录 API 在进程内执行，等价于**本地代码执行**。生产环境请使用 `api.security_profile: production` 或 `verified`，详见 [`SECURITY.md`](../../SECURITY.md#高风险能力)。
