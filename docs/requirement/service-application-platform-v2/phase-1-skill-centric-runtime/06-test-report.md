# Phase 1 · 技能中心的应用运行时 — 测试报告

> 状态：定向测试完成；全量 CI、quickstart 空卷与人工 UAT 未执行
> 创建：2026-11-12
> 范围：仅覆盖本次服务应用 v2、应用连接、技能、发布、渠道版本固定、迁移和前端服务应用改造
> 结论：与本次改动直接相关的后端测试、静态检查、前端门禁和 E2E 通过；本报告不宣称全仓或发布全绿

## 1. 执行原则

按用户要求，本轮不运行无关的全仓回归、Memory 测试或其他模块测试。测试资源集中在服务应用 v2 的五个后端测试文件、前端服务应用 E2E、前端编译门禁及后端静态/架构检查。

未执行的用例不会被推定通过；全量回归与 CI 结果仍需在创建 PR 后由流水线确认。

## 2. 执行结果

| 检查项 | 命令/范围 | 结果 |
|---|---|---|
| 后端服务应用 v2 定向测试 | `test_service_application_v2_contracts.py`、`test_service_application_v2_migrations.py`、`test_service_application_v2_preview_api.py`、`test_service_application_v2_preview_runtime.py`、`test_service_application_v2_services.py` | 34 passed，1 skipped，耗时 21.18s |
| 后端静态检查 | `uv run ruff check src tests migrations` | 通过 |
| 架构边界检查 | `python scripts/check_architecture.py` | `architecture gate passed` |
| 迁移状态 | `alembic current` | `0058_service_application_v2 (head)` |
| 前端类型检查 | `npm run typecheck` | 通过 |
| 前端 i18n 检查 | `npm run check:i18n` | 通过，2114 translations |
| 前端构建 | `npm run build` | 通过；保留既有主包体积警告 |
| 前端定向 E2E | 服务应用与渠道导航指定套件 | 9 passed |
| 补丁完整性 | `git diff --check` | 通过 |

## 3. 覆盖内容

### 3.1 后端契约与迁移

- v2 契约拒绝旧 `scenarios/capabilities` 字段，应用必须绑定已发布 Agent。
- 应用规则统一覆盖 fallback、handoff、人工确认、草稿写预览和结果校验，并兼容旧 `reply` 值归一化。
- 发布快照 digest 具备稳定性且不包含明文凭据。
- 同一 Agent 绑定两个应用时，运行时只授权各自应用的技能。
- `0058_service_application_v2` 完成 clean-break 表结构、渠道应用版本字段、审计和 trace 契约。

### 3.2 服务、渠道与预览

- 标准示例不可变；复制后归用户所有，示例不会被重启或复制覆盖。
- 未发布 Agent 不能绑定应用；发布 readiness 会检查 Agent 版本、连接与凭据。
- 凭据只写不读，API 仅返回 `credentials_configured`，不返回明文或密文。
- 回滚以追加新版本实现，历史版本内容保持不变。
- 渠道入站固定应用发布版本；会话、run 和 trace 能保留应用上下文。
- 草稿预览使用当前 Agent；固定版本预览严格使用发布快照中的 Agent 与规则。
- 写技能预览要求应用规则与平台设置双开关；HTTP 技能在预览中使用 MockTools，不产生真实上游调用。

### 3.3 前端

- 服务应用目录使用 v2 契约，默认分页 10，连接列表使用真实服务端分页参数。
- 详情页只显示六个 v2 页签；规则模型与后端字段同步。
- 发布与回滚、不可变示例复制、Agent 使用关系展示均有定向 E2E 覆盖。
- 渠道页面只允许绑定已发布应用版本。
- i18n、类型检查和生产构建通过。

## 4. 未执行与未验证

- 未运行后端全量 pytest。
- 未运行 Memory、单个模块之外的其他全仓回归。
- 未执行 quickstart 空数据卷一次启动、迁移和 seed 的部署冒烟。
- 未执行 A1～A12 的人工 UAT、角色权限全矩阵和类生产环境演练。
- 未执行 GitHub CI；最终合并必须以 PR 的 CI 结果为准。

## 5. 已知次要风险

- 应用内版本历史和应用内渠道列表仍为前端分页，接口最多获取 50/100 条；不阻断当前主流程，但数据量增大后需要服务端分页。
- 前端构建存在既有主包大于 500 kB 警告。
- 完整后端套件和 CI 尚未运行，因此本报告不能作为正式发布验收依据。

## 6. 结论

本次服务应用 v2 定向实现验证通过，未发现由本次改动引入的 P0/P1 阻断项。当前状态适合提交 PR 并交由 CI 继续验证；在 CI、quickstart 和人工 UAT 完成前，不宣称全量测试通过或正式发布就绪。
