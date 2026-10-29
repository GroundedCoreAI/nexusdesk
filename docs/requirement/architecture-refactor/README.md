# NexusDesk 架构重构与目录收口

> 状态：实施中
> 开始日期：2026-10-27
> 工作分支：`refactor/plugin-platform`

## 1. 目标

本目录记录 NexusDesk 从历史 `apps / modules / integrations / platform` 结构，收口到四层目标架构的完整决策、迁移和验收证据：

```text
NexusDesk
├── Core Platform
├── Extension Contracts
├── Business Capabilities
└── Applications
```

本次工作是**模块化单体内部的大重构**，不改变部署形态，不拆分微服务，不新增业务范围。

## 2. 文档边界

- `docs/`：记录当前系统的架构、功能和运行方式。
- 本目录：记录本次架构重构的背景、目标、迁移映射、边界规则和验收结果。
- 具体业务功能文档继续放在 `docs/` 根目录或对应需求目录，不在本目录重复维护。

## 3. 文档集

| 文件 | 内容 | 状态 |
|---|---|---|
| `01-background-and-goals.md` | 背景、问题和重构目标 | 已建立 |
| `02-target-architecture.md` | 四层目标架构和职责 | 已建立 |
| `03-directory-migration-map.md` | 旧目录到新目录的迁移映射 | 已建立 |
| `04-boundary-and-contracts.md` | 依赖边界和扩展契约规则 | 已建立 |
| `05-migration-plan.md` | 分批落地顺序和操作原则 | 已建立 |
| `06-acceptance-plan.md` | 代码、测试、文档验收标准 | 已建立 |
| `07-acceptance-report.md` | 当前实际验收结果和遗留项 | 初始记录 |
| `08-group-application-and-business-registry.md` | 阶段二统一入口与业务注册机制 | 已完成 |
| `09-business-scope-context.md` | 阶段三租户、业务与工作空间上下文 | 已完成 |
| `10-resource-scope-data-plane.md` | 阶段三核心资源数据面过滤 | 已完成 |

## 4. 当前结论

代码目录已完成主要物理迁移，`agent_platform/modules`、`apps`、`integrations`、`platform` 不再作为运行时目录保留。阶段二已完成，阶段三已完成上下文边界和 Agent、知识库、渠道等主要配置资源的数据面过滤。

升级注意：Python 启动模块已从 `agent_platform.apps.*` 统一迁移到
`agent_platform.applications.*`。Quickstart/API 默认可在 API 进程内嵌 Worker；
生产环境使用独立 Worker 入口，例如
`python -m agent_platform.applications.worker.memory`，并通过
`AGENT_EMBEDDED_WORKER=false` 关闭 API 内嵌 Worker。

详细状态以 `07-acceptance-report.md` 为准。
