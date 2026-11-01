# 05. 迁移计划

## 执行顺序

1. 冻结目标目录和依赖边界。
2. 移动 Core Platform 代码。
3. 移动 Extension Contracts。
4. 移动 Business Capabilities。
5. 移动 Applications、Worker 和初始化脚本。
6. 按最长前缀优先修复全部 import。
7. 删除空的旧目录，不保留兼容层。
8. 更新架构测试和静态门禁。
9. 更新 `/docs` 运行手册和架构链接。
10. 执行后端、前端和 PostgreSQL 回归验证。

## 当前已完成

- 四个主目录已建立。
- 主要平台、业务和应用代码已完成物理迁移。
- 旧 `modules`、`apps`、`integrations`、`platform` 目录已从工作树移除。
- 主要运行时 import 已切换到新命名空间。
- 外部插件、Capability 和 UI Extension 代码保留在新扩展边界内；示例实现位于 `business_capabilities/sample_operations`，不再保留独立顶层 `extensions/` 目录。

## 当前收口工作

- 完成文档旧路径清理。
- 修正架构测试中的历史路径假设。
- 执行完整导入、Ruff、pytest 和前端构建验证。
- 记录真实失败用例，不以“目录移动完成”代替重构完成。

## 操作约束

- 不执行 `git reset` 或 `git clean`。
- 不覆盖用户已有未提交改动。
- 不为目录迁移新增数据库表或迁移。
- 不扩展插件市场、SDK 生态或新业务功能。
