# 07. 验收报告

> 当前状态：代码回归已通过，等待最终提交
> 记录日期：2026-10-27

## 已确认

- [x] 新的 `core_platform/`、`extension_contracts/`、`business_capabilities/`、`applications/` 目录已建立。
- [x] 主要代码已完成物理迁移。
- [x] 旧运行时目录 `modules/`、`apps/`、`integrations/`、`platform/`、`contracts/`、`extensions/` 已移除。
- [x] 旧运行时 import 已完成主要替换；当前代码扫描未发现旧命名空间引用。
- [x] `Settings` 已移入 `core_platform/platform_services/platform_settings`。
- [x] 外部插件示例已移入 `business_capabilities/sample_operations`。
- [x] Capability、UI Extension 和插件生命周期仍通过新的扩展体系接入。

## 尚未最终确认

- [x] 非 PostgreSQL 后端测试：353 passed。
- [x] PostgreSQL 后端测试：308 passed，33 skipped。
- [x] Ruff 检查通过。
- [x] 架构门禁脚本通过。
- [x] compileall 通过。
- [x] 前端 typecheck、i18n、build 全部通过。
- [x] `docs/architecture.md` 和 `docs/module-development.md` 中的旧路径已同步更新。
- [x] 根目录运行文档中的代码路径已切换到新目录；历史需求文档中的旧路径暂作为历史记录保留。
- [ ] 最终变更清单和遗留问题评审。

## 当前判断

根据本次回归报告，可以确认：**目录收口和代码回归验收已完成。**

当前仅剩提交前的变更范围复核；`__pycache__` 等运行时缓存不属于项目架构目录，也不应提交。

## 下一步

1. 排除 `__pycache__`、pytest 临时目录等运行时产物。
2. 复核最终提交范围。
3. 使用 `--no-issue` 标准提交并推送到个人开发分支。
