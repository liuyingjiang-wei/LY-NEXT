# 扩展 HTTP API 插件目录

本目录用于**用户自定义 API 插件**（`.py` 文件），由 `APILoader` 在启动时扫描加载。

- 内置路由在 `ly_next/api/`（如 `ly_api.py`、`ws_api.py`），与此目录无关。
- 默认配置项 `api.api_dir` 指向 `ly_next/apis`。
- 每个插件模块可导出 `default: dict` 或 `BaseAPI` 实例；详见 `ly_next/api/base.py`。

`__init__.py` 仅 re-export `BaseAPI`，便于插件文件 `from ly_next.apis import BaseAPI` 写法。
