# 参与贡献

> 英文原版见 [CONTRIBUTING.md](CONTRIBUTING.md)。本文件为中文版（可选维护）；如保留，需与英文版保持同步。

感谢你愿意参与 NexusDesk 的建设。可参与的方向包括问题反馈、文档改进、测试用例与代码贡献。

在动手之前，请先了解这个项目的**当前状态与边界**，这能省下双方很多时间：

- 项目处于持续开发阶段，已具备可运行的客服核心流程，但**尚未达到开箱即用的生产可用程度**。
- 功能现状与规划是分开说明的。各模块 README 的第 1 节描述**代码现状**，其余章节保留的是**目标规划**，不代表已交付。
- 已知限制见[项目主页的当前状态与边界](README.md#current-status-and-limits)和各模块 README 第 1 节；归档文档仅用于历史追溯。

## 提交问题

1. 使用对应的 issue 模板：**Bug 报告**、**功能建议**、**部署问题**。
2. 说明**使用场景、复现步骤、部署方式与脱敏日志**。部署问题尤其需要"部署方式 / 中间件 / 日志"这三样。
3. 如果还不确定是否适合你的场景，或问题还不到能复现的程度，欢迎先到
   [Discussions](https://github.com/GroundedCoreAI/nexusdesk/discussions) 讨论。

⚠️ **请勿在问题报告、截图或代码中包含 API Key、访问令牌、数据库密码及客户隐私数据。**

涉及安全漏洞请**不要**开公开 issue，按 [SECURITY.md](SECURITY.md) 的方式私下报告。

## 分享使用场景

我们在收集真实环境中的智能客服应用场景，用来决定平台下一步抽象哪些能力。
如果你正在用（或者试用过、放弃过）客服 agent，欢迎到
[使用场景征集](https://github.com/GroundedCoreAI/nexusdesk/discussions/93) 按模板分享一段。

**不需要使用 NexusDesk**，也不需要把字段填满——一个具体段落比空白表单有用得多。
这是产品调研：具体的缺陷与功能需求仍请走上面的 issue 模板。

## 从哪个分支开发

| 分支 | 用途 | PR 目标 |
|---|---|---|
| `integration` | 日常开发集成 —— **仓库默认分支** | **功能、修复、重构、文档改动都提到这里** |
| `main` | 正式发布线（上次发版的快照） | 只接收来自 `integration` 的合并，以及维护者的 `release/*`、`hotfix/*` 分支 |

仓库的**默认分支是 `integration`**：clone、浏览代码、Fork 和新建 PR 都默认落在它上面。从这个分支切出你的工作分支：

```bash
git fetch origin
git switch -c fix/your-change origin/integration
```

功能与修复 PR **不要提到 `main`** —— 它是发布线，不直接接收开发改动。如果已经基于 `main` 开了分支，提交 PR 前先迁移过来：

```bash
git rebase --onto origin/integration origin/main your-branch
```

`main` 不适合作为起点的原因：它是发布快照，而 `integration` 上是最新的文档结构和模块路径。基于 `main` 的分支合进 `integration` 时，会产生大量与本次改动无关的冲突，review 也会被这些噪音淹没。拿不准就直接开 PR，我们会帮你调整。

## 贡献代码

1. **开发前先阅读** [本地开发](docs/development/local-development.md) 与 [模块开发规范](docs/development/module-development.md)。
2. 涉及架构或数据结构变化的改动，建议**先开 issue 或 discussion 对齐方向**，避免做完再返工。
3. 提交变更时说明**解决的问题、影响范围与验证结果**。
4. 接口或数据结构发生变化时，**同步更新文档和数据库迁移**。迁移只新增、不修改已应用的历史迁移。

### 提交前的自检

在 `backend` 目录下运行（本项目的 CI 执行的就是这些）：

```bash
# 代码风格与静态检查
ruff check .
ruff format --check .

# 后端测试
pytest
```

> 提示：未设置 `TEST_DATABASE_URL` 时，标记为 `postgres` 的测试会被跳过。涉及迁移或事务的改动请配置真实 PostgreSQL 后再跑一遍。

前端在 `frontend` 目录下：

```bash
npm run build      # 含 i18n 检查与 TypeScript 编译
```

### 一些约定

- **文档以英文撰写**：`docs/`、`README*`、`CHANGELOG*` 的新增或修改只需英文版本。现有中文版本
  （如 `README.zh-CN.md`、`CONTRIBUTING.zh-CN.md`）为可选维护，可保留、更新或逐步下线。
  前端多语言文案仍在 `frontend/src/i18n/locales/` 下维护。
- **如保留中文版，两份都要同步改**：只改一份会让两个语言版本悄悄分叉。两份的章节结构应保持一致。
- **不要顺手批量格式化**与本次改动无关的文件，避免制造巨大的无关 diff。
- 新增功能请尽量**带上测试**，尤其是事务、迁移与权限相关部分。
- **写操作必须保持"提议 → 人工确认"的既有约束**：Agent 不得直接执行不可逆的业务动作。

## 贡献文档

文档错误、表述不清、示例跑不通，都是很有价值的反馈。直接提 PR 或在 issue 中说明位置即可。

## 行为准则

请保持技术讨论的专注与礼貌：就事论事、不针对个人、不引战。这个项目面向企业私有化场景，
讨论中经常出现真实客户环境的信息，**请勿索取或泄露他人的敏感配置**。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。提交贡献即表示你同意以该许可证授权你的贡献。
