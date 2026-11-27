# NexusDesk Skill 能力库 · Phase 2 开发交接文档

> **接手进度（2026-11-27）**：第 6 节前端结构化 422 已闭环（`frontend/src/features/skills/api.ts` + `skills.spec.ts` 新增用例）；第 10 节步骤 2–6 已执行，结果见 `phase-2-authoring-test-release/06-test-report.md`。HEAD 与脏工作区未变，未 commit。`07-acceptance-report.md` 仍待用户明确验收后创建。
>
> 交接日期：2026-11-27（Asia/Shanghai）
> 仓库：`D:\deepseek-code\nexusdesk-customer-service`
> 分支：`feat/login-responsive-scale`
> HEAD：`fa0c3e5a476a9ebc52a97865cdc0fad246880a4d`
> 结论：Phase 2 核心功能与已暴露缺陷均已实现/修复，**尚有一项跨端契约适配未完成**；正式验收尚未进行。

---

## 1. 一句话结论

Skill 能力库 Phase 2 的「创建 → 编辑 → 测试 → 就绪检查 → 发布 → 版本回滚」闭环、统一业务侧边栏、路由、迁移与测试主体工作已经完成，历史暴露的 P2-IT-09（422 丢失字段明细）、P2-CM-12（弹窗焦点逃逸）、service-apps 4 个前端回归用例均已修复并通过测试。

但**当前还不能宣称"整体完成"**，原因是：

1. 后端已改为返回结构化 422（`detail.code + detail.errors[]`），但 `frontend/src/features/skills/api.ts` 仍只按字符串错误码解析，前端拿不到字段级错误，会在结构化 422 时退化为通用提示。此项需补齐后才能算端到端契约闭环。
2. 正式验收（`07-acceptance-report.md`）尚未开始，需用户明确验收后再写。
3. 覆盖矩阵仍有 PARTIAL / NOT_COVERED 项与若干残余风险（见第 7 节），不应将 64 个 P2 用例全部表述为"已通过"。

---

## 2. 仓库与运行环境

| 项目 | 状态 |
|---|---|
| 分支 | `feat/login-responsive-scale` |
| HEAD | `fa0c3e5a476a9ebc52a97865cdc0fad246880a4d`（未产生新提交） |
| 工作区 | **脏工作区，包含大量既有未提交改动**，禁止整体 commit / reset / revert |
| 后端 | `http://127.0.0.1:8000/api/v1/health` → 200 |
| 前端 | `http://127.0.0.1:5173/` → 200（`npm ci` 后已重启，持久 PTY 会话 `87106`） |
| PostgreSQL | Docker `nexusdesk-customer-service-postgres-1`，healthy |
| 迁移 | 开发库与隔离测试库均为单 head `0076_skill_library` |

**Windows 代理注意**：本机 `127.0.0.1:33210` 本地代理会拦截 PowerShell 的 Web 请求，访问本地服务请使用：

```powershell
curl.exe --noproxy '*' ...
```

---

## 3. 已完成的工作范围

### 3.1 功能闭环

- 全局 Skill 目录（`/skills`）：列表、搜索、分类/状态筛选、空态、错误态、API 真实数据。
- 创建（`/skills/create`）：模板创建、专业创建；AI 生成默认关闭。
- 详情（`/skills/:key`）：概要、定义、测试、发布、版本页签；分析数据保持诚实空态。
- 编辑（`/skills/:key/edit`）：复杂配置、草稿保存、修订冲突处理、脏离开拦截、字段级校验聚焦。
- 测试工作台：按草稿修订版本绑定测试、幂等请求、历史记录、过期结果提示、写操作测试强制拦截。
- 就绪检查与发布：发布弹窗、就绪阻塞、语义化版本、不可变版本记录。
- 回滚：基于历史版本生成更高版本，记录 `release_kind=rollback` 与 `rollback_from`。

### 3.2 架构与集成

- 统一使用共享 `frontend/src/app/ConsoleSidebar.tsx`（228px 业务侧边栏），**不存在 Skill 专属侧边栏**。
- 通用路由：`/skills`、`/skills/create`、`/skills/:key`、`/skills/:key/edit`，控制台侧边栏已补齐开放平台入口。
- 新建全局 Skill 域，**未改动**应用自有的 `service_application_skills` / `service_application_versions`。
- 迁移 `0076_skill_library` 为单 head 增量迁移，新增 `skills`、`skill_test_runs`、`skill_versions` 三张表。
- 安全默认：AI 生成关闭、在线工具测试关闭；写操作测试始终 blocked。

### 3.3 关键文件

| 层 | 路径 |
|---|---|
| 后端领域 | `backend/src/agent_platform/business_capabilities/skill_library/` |
| 后端装配 | `backend/src/agent_platform/applications/application_factory.py` |
| 迁移 | `backend/migrations/versions/0076_skill_library.py` |
| 前端页面 | `frontend/src/features/skills/` |
| 前端侧边栏 | `frontend/src/app/ConsoleSidebar.tsx`、`frontend/src/styles/console-sidebar.css` |
| 路由 | `frontend/src/app/hashRouter.ts`、`frontend/src/app/App.tsx` |
| 后端测试 | `backend/tests/test_skill_library_api_postgres.py`、`backend/tests/test_skill_library_contracts.py` |
| 前端测试 | `frontend/tests/skills.spec.ts`、`frontend/tests/sidebar.spec.ts`、`frontend/tests/hash-routing.spec.ts` |

---

## 4. 缺陷修复记录

### 4.1 P2-IT-09：结构化 422 字段明细（后端已修）

- 问题：`skill_definition_invalid` 的 422 只返回字符串，丢失 `loc/type/msg`；失败的保存虽然原子回滚正确，但前端/调用方无法定位字段。
- 修复：
  - `skill_library/service.py` 引入 `SkillDefinitionInvalidError`，携带安全的结构化 `detail`。
  - `application_factory.py` 的 `DomainError` handler 优先使用异常自带 `detail`，普通 `DomainError` 契约不变。
  - 只暴露 `loc/type/msg`，剔除 `input/ctx`、URL、堆栈和原始异常文本；动态文案走安全白名单。
- 响应示例：

```json
{
  "detail": {
    "code": "skill_definition_invalid",
    "errors": [
      { "loc": ["definition", "type"], "type": "literal_error", "msg": "Input should be 'instruction', 'knowledge', 'query', 'action' or 'handoff'" }
    ]
  }
}
```

- 验证：定向用例通过；Skill 全套 `21 passed`；DB `draft_revision`、`draft_definition`、审计均保持不变；响应不含探针 secret marker。

### 4.2 P2-CM-12：发布/回滚弹窗焦点逃逸（前端已修）

- 问题：Ant Design v6 默认 Modal 焦点陷阱在 Tab 环绕时会短暂落到 `document.body`。
- 修复：
  - 新增 `frontend/src/features/skills/useStrictFocusTrap.ts`，按每次 Tab 重新计算可聚焦元素，首尾环绕时 `preventDefault()` 并直接聚焦。
  - `ReleasePanel.tsx` 仅对发布、回滚两个 Modal 应用该 hook，未改全局 AntD 行为。
- 验证：原严格断言不放宽，`1 passed`；`skills.spec.ts` 全量 `16 passed`；typecheck 通过。

### 4.3 service-apps 回归用例（测试已修，产品行为未改）

只更新了 `frontend/tests/service-apps.spec.ts` 中的 4 个陈旧断言，未修改产品代码：

1. 发布按钮选择器限定到 `.sa-release-header-actions`，消除与"取消发布"的 strict-mode 歧义。
2. 加载态改为 deferred gate，先断言 spinner 再释放，消除时序竞态。
3. 下线/归档文案对齐当前产品：`取消发布` / `确认取消发布`。
4. 发布页断言对齐当前 `DeliveryTab` 结构。

结果：定向 4/4 通过，整 spec `17 passed / 0 failed / 0 skipped`。

---

## 5. 测试与验证结果

### 5.1 后端

| 项 | 命令/范围 | 结果 |
|---|---|---|
| Skill 契约测试 | `tests/test_skill_library_contracts.py` | 7 passed |
| Skill PostgreSQL API | `tests/test_skill_library_api_postgres.py` | 14 passed |
| Skill 合计 | 两文件 | **21 passed** |
| 平台回归 | `test_platform_postgres.py` | 18 passed |
| 访问控制 | `test_access_control.py` | 3 passed |
| 平台设置 | `test_platform_settings.py` | 7 passed |
| Lint | `uv run ruff check src tests` | 通过 |
| 格式化 | 相关 Skill 文件 `ruff format --check` | 通过 |

> 注意：上述三项平台回归是在 `application_factory.py` 最终改动**之前**执行的，交接后建议复跑一次确认无回归。

### 5.2 前端

| 项 | 结果 |
|---|---|
| `npm run typecheck` | 通过（`tsc --noEmit`，exit 0，已复验） |
| `npm run check:i18n` | 通过，4 locale 共 3487 条翻译（已复验） |
| `npm run build` | 通过；存在既有 >500kB 共享 bundle 告警，Skill 页为独立约 109kB chunk |
| `tests/skills.spec.ts` | 16 passed |
| `tests/sidebar.spec.ts` + `tests/hash-routing.spec.ts` | 11 passed |
| `tests/service-apps.spec.ts` | 17 passed |

### 5.3 数据库

- 隔离测试库 `agent_platform_skill_test`：Alembic `0076_skill_library`，测试后 `skills / skill_test_runs / skill_versions` 均为 `0` 行。
- 开发库 `agent_platform`：只读校验，未做降级、drop、restamp。

---

## 6. 唯一未完成的代码项（接手第一优先级）

### 前端消费结构化 422

现状：共享 client 抛出的错误消息为

```ts
`${status} · ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`
```

而 `frontend/src/features/skills/api.ts` 中：

- `skillErrorCode()` 只匹配 `^(?:\d{3} · )?([a-z][a-z0-9_]+)$`，对象形态取不到 `code`。
- `skillErrorMessage()` 原样返回消息，`errorText()` 的 422 分支调用 `validationFieldErrors()`，后者要求 `422 · <JSON 数组>`，对象形态无法解析，最终只剩通用 422 提示。

建议的最小修复（不要改全局 client 契约）：

1. `skillErrorCode()`：当消息为 `422 · {...}` 时解析对象并返回 `code`（字符串）。
2. `skillErrorMessage()`：当 `detail` 为 `{ code, errors: [...] }` 时，把 `errors` 规整为仅含 `loc/type/msg` 的数组，返回 `422 · ${JSON.stringify(errors)}`，从而被 `validationFieldErrors()` 正确消费。
3. 在 `frontend/tests/skills.spec.ts` 增加结构化 422 用例：保存返回 `detail.errors`，断言 `definition.type` 的本地化字段提示出现，且原始 JSON / secret 不被渲染。

验收判据：保存非法定义时，编辑器展示字段级错误而非通用 422，且响应体中的敏感字段不回显。

---

## 7. 遗留风险与覆盖缺口

### 7.1 覆盖矩阵现状（审计时）

| 等级 | UT | IT | CM | 合计 |
|---|---:|---:|---:|---:|
| DIRECT | 5 | 2 | 1 | 8 |
| PARTIAL | 11 | 17 | 13 | 41 |
| NOT_COVERED | 8 | 2 | 0 | 10 |
| ENVIRONMENT/PENDING | 2 | 3 | 0 | 5 |
| 合计 | 26 | 24 | 14 | 64 |

补强（P2-UT-13/14/19/25、P2-IT-16/18/20 等）已显著提升覆盖，但上述审计基线未重新统计，正式报告需按实际结果重算，**不得笼统写"64/64 通过"**。

### 7.2 已知残余风险

1. **Handoff 队列只校验非空**：`dependencies.handoff_queue` 仅判空，不解析队列是否真实存在/启用；缺失队列会被更早的 `required_fields_valid` 拦截，而非 `handoff_queue_unavailable`。
2. **填充表降级未执行**：仅验证了空表 `0075 → 0076 → 0075` 往返；"表中有数据时拒绝降级"的守护仅有源码证据，未实际执行。
3. **前后端证据性质不同**：Playwright Skill 套件全部为 `page.route` mock，不能作为后端持久化/原子性证据；真实持久化证据来自后端 PostgreSQL 测试。
4. **构建告警**：既有共享 bundle >500kB 告警，非本次引入。
5. **Alembic 告警**：约 23 条既有 `path_separator` deprecation warning，非阻塞。
6. **P2-IT-09 前端侧未闭环**（见第 6 节），是当前唯一明确的未完成代码项。

---

## 8. 正式文档状态（需在验收前后更新）

目录：`docs/requirement/skill-capability-library/`

| 文档 | 现状 | 待办 |
|---|---|---|
| `README.md` | 仍写 "Phase 2 implementation in progress" | 改为"实现完成、验证基本完成、待用户验收" |
| `phase-2-authoring-test-release/04-test-plan.md` | 仍写"tests not yet executed" | 更新为已执行，并标注 PASS/PARTIAL/NOT_COVERED |
| `phase-2-authoring-test-release/05-acceptance-plan.md` | 验收计划 | 保持"待验收"，不要提前写通过 |
| `phase-2-authoring-test-release/08-implementation-breakdown.md` | 需同步 | 改为 "Implementation complete; verification executed; acceptance pending." |
| `06-test-report.md` | 尚不存在 | 按真实结果创建，禁止声称全部 64 项通过 |
| `07-acceptance-report.md` | 尚不存在 | **仅在用户明确验收后创建** |

---

## 9. 证据文件索引（均在仓库 `.tmp/`，未提交）

| 文件 | 内容 |
|---|---|
| `.tmp/phase2-backend-evidence.md` | 后端/迁移/DB 基线证据 |
| `.tmp/phase2-frontend-evidence.md` | 前端路由/侧边栏/响应式证据 |
| `.tmp/phase2-coverage-matrix.md` | 64 项 P2 ID 覆盖审计 |
| `.tmp/phase2-backend-hardening.md` | 后端安全/原子性补强 |
| `.tmp/phase2-frontend-hardening.md` | 前端响应式/可访问性补强 |
| `.tmp/phase2-backend-iti09-fix.md` | 结构化 422 修复证据 |
| `.tmp/phase2-frontend-focus-fix.md` | 弹窗焦点陷阱修复证据 |
| `.tmp/phase2-service-apps-regression.md` | service-apps 回归修复证据 |

---

## 10. 接手步骤（建议顺序）

1. **确认现场**：`git status --short`，确认 HEAD 与脏工作区不变；确认 8000/5173/PostgreSQL 仍在运行。
2. **完成第 6 节**：修改 `frontend/src/features/skills/api.ts`，增加结构化 422 Playwright 用例，跑 `tests/skills.spec.ts` 与 `npm run typecheck`。
3. **复跑后端回归**：设置隔离库后跑 Skill 21 项 + `test_platform_postgres.py` / `test_access_control.py` / `test_platform_settings.py`，确认最终 `application_factory.py` 改动无回归。
4. **跑前端完整门槛**：`typecheck`、`check:i18n`、`build`、`skills.spec.ts`、`sidebar+hash-routing`、`service-apps.spec.ts`。
5. **核对隔离库残留**：`skills/skill_test_runs/skill_versions` 应为 `0/0/0`。
6. **更新文档**：README、04、08，新建 `06-test-report.md`（真实结果）；保留 `07-acceptance-report.md` 待用户验收。
7. **不要 commit**：工作区含大量用户既有改动，提交需用户明确指令并单独梳理。

### 隔离库命令

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://agent:agent_dev@127.0.0.1:5432/agent_platform_skill_test'
C:\Users\acehu\.local\bin\uv.exe run pytest tests/test_skill_library_api_postgres.py tests/test_skill_library_contracts.py
C:\Users\acehu\.local\bin\uv.exe run pytest tests/test_platform_postgres.py tests/test_access_control.py tests/test_platform_settings.py
C:\Users\acehu\.local\bin\uv.exe run ruff check src tests
```

---

## 11. 安全与数据约束（必须遵守）

- PostgreSQL 操作只走 Docker / Alembic。
- 开发库 `agent_platform` 只读；禁止 downgrade / drop / restamp。
- 可写测试库仅 `agent_platform_skill_test`。
- 禁止整体 `git reset` / `git checkout -- .` / 批量 revert，避免覆盖用户既有改动。
- `.tmp/` 证据与正式 `docs/` 文档需分开管理，不要把临时证据当作正式报告。
- 用户未明确验收前，不得声称"验收通过"或创建验收报告。
