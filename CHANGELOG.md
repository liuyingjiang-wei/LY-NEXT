# Changelog

本文件记录面向用户的版本变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [Unreleased]

### Added

- 工作台首次配置向导（分步跳过、稍后再说、入门引导清单）
- 配置预设 API（minimal / standard / full_stack）与依赖横幅可执行操作
- 侧栏分组搜索、对话场景生效配置 chips、传输状态徽章
- 桥接总览 Tab、官方插件目录与 doctor 缺插件检查
- 对话内 **Agent 预设一键应用并保存**（场景菜单 / 移动端「更多」）
- 工具时间线收起/展开、host tier 审批提示
- 用户排障手册 [`docs/USER.md`](docs/USER.md)

### Changed

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
