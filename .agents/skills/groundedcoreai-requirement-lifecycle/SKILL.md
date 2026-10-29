---
name: groundedcoreai-requirement-lifecycle
description: nexusdesk 需求全流程文档驱动规范。当接到任何新需求/新阶段任务（无论是"做个 XX 功能"、一段需求描述、还是 issue/PRD 链接）时使用：需求分析阶段先生成业务目标、需求文档、技术设计、测试方案、验收方案五份规划文档；设计/开发/调试/测试/验收全程对照对应阶段文档执行；测试结束生成测试报告、验收结束生成验收报告。文档套件模板与编号体系参考 docs/requirement/agent-memory/ 各阶段目录。即使用户只说了需求没提文档，只要任务达到"一个阶段/特性"的体量就必须先走本 skill 建文档套件，再动手写代码。
---

# groundedcoreai-requirement-lifecycle

nexusdesk 的需求全流程文档驱动工作方式。核心原则：**文档先行、逐阶段对照执行、每阶段结束留下结论性文档**。
参考实现：`docs/requirement/agent-memory/`（Phase 1~7 的完整范本）。

## 文档套件结构

每个需求主题在 `docs/requirement/<topic>/` 下组织；主题内按阶段建 `phase-N-<slug>/` 目录
（单阶段需求也建 `phase-1-<slug>/`，保持结构一致）。主题根目录放一份 `README.md` 作索引
（背景、总体原则、阶段路线图表、明确不做的边界、Review 指引）。

每个阶段目录下的标准套件（编号即顺序，前缀不得改动）：

| 文件 | 产物阶段 | 内容 | 何时写 |
|---|---|---|---|
| `01-business-goals.md` | 需求分析 | 要解决的问题、业务目标（G1..）、成功指标（基线/目标）、范围边界、风险约束 | 动手前 |
| `02-requirements.md` | 需求分析 | 用户故事（US-n）、功能需求（FR-n）、非功能需求、验收标准（AC-n） | 动手前 |
| `03-technical-design.md` | 需求分析 | 改动总览、数据模型/迁移、核心流程、配置项、测试方案简表、上线与回滚 | 动手前 |
| `04-test-plan.md` | 需求分析 | 测试范围与原则、环境、UT/IT/CM 用例表（含溯源列）、回归范围、缺陷分级与出口准则 | 动手前 |
| `05-acceptance-plan.md` | 需求分析 | 验收组织、环境前置、AC 逐条验收步骤（A1..）、业务指标测量、合规核对（C-n）、通过标准与签字 | 动手前 |
| `08-implementation-breakdown.md` | 设计评审后（可选，大型阶段建议） | 任务拆解表（T-n：文件/依赖/溯源）、文档与现实不一致清单及裁定（R-n） | 开发启动时 |
| `06-test-report.md` | 测试结束 | 逐条用例执行结果（测试位置/环境/结果/证据）、缺陷记录（D-n）、残留风险（R-n）、CI 证据、输出快照附录 | 测试完成后 |
| `07-acceptance-report.md` | 验收结束 | AC 逐条判定与证据、业务指标判定、合规核对、遗留清单（L-n）、结论（通过/有条件通过/不通过）与签字 | 验收完成后 |

模板骨架在 `assets/templates/` 下，写文档时**先读对应模板再写**，保持章节与表格结构一致。

## 工作流程

### 阶段一：需求分析（文档先行）

接到需求后，先不写代码：

1. 确定主题目录：已有主题（如记忆、知识库）则在其下新建 `phase-N-<slug>/`；新主题则建
   `docs/requirement/<topic>/` 并写主题 `README.md` 索引。
2. 按模板依次产出 `01`~`05` 五份规划文档。写作要求：
   - **一切编号可溯源**：业务目标 G-n、用户故事 US-n、功能需求 FR-n、验收标准 AC-n，
     后续测试用例、验收步骤必须用"溯源"列指回这些编号；
   - 技术设计必须落到**具体文件路径与迁移号**，先核查现状代码再写（不写与代码现实矛盾的方案）；
   - 测试方案的用例编号规则：`P<N>-UT-xx`（单元）、`P<N>-IT-xx`（集成）、`P<N>-CM-xx`（通用核对项），
     N 为阶段号；每条用例带"预期"与"溯源"两列；
   - 验收方案的 A1.. 与 AC 一一对应，每个场景写明通过判据；
   - 明确"范围不包含"清单，防止阶段蔓延。
3. 五份文档完成后向用户汇报要点，**等用户确认（或要求直接继续）后再进入开发**。

### 阶段二：设计/开发/调试（对照执行）

1. 大型阶段先补 `08-implementation-breakdown.md`：把 03 拆成任务表（T-n：涉及文件、依赖顺序、溯源），
   并设"文档与现实不一致清单及裁定"（R-n）一节——开发中每发现文档与代码现实冲突，先登记裁定再动手，
   裁定结果回填相关文档。
2. 开发按 T-n 依赖顺序执行；每完成一个任务对照 02 的 FR 与 03 的设计自查。
3. 调试中发现设计需要变更时，**先改 03（注明修订日期与原因），再改代码**——文档与代码不同步是本项目
   测试报告/验收报告的主要缺陷来源。
4. 提交遵循 `groundedcoreai-commit-standard`；分支/PR 流程遵循 `groundedcoreai-dev-workflow`。

### 阶段三：测试（对照 04 执行 → 产出 06）

1. 逐条执行 `04-test-plan.md` 的 UT/IT/CM 用例，**不允许只做"大体跑了下"**——06 报告要求每条用例
   有独立行：测试位置（文件::用例）、执行环境、结果、证据。
2. 出口准则未达成（P0/P1 未关闭、回归非全绿、开关兜底 diff 非零）不得进入验收。
3. 完成即写 `06-test-report.md`：执行总览、逐条结果、缺陷记录（D-n：级别/发现环节/修复提交/回归）、
   残留风险（R-n）、CI 证据（run 链接）、本地执行输出快照附录。如实记录 skip 与环境约束，禁止粉饰。

### 阶段四：验收（对照 05 执行 → 产出 07）

1. 逐条执行 05 的 A1.. 场景与 C-n 合规核对；本环境无法执行的项标 `pending_env`，
   写明所需环境与建议验收人，不得跳过不写。
2. 业务指标能测则实测；需生产数据的标"待生产验证"并给出验证方法。
3. 完成即写 `07-acceptance-report.md`：逐条判定与证据、遗留清单（L-n：级别/owner/期限）、
   结论（通过 / 有条件通过 / 不通过）与签字表。遗留项必须有 owner 与期限建议。

## 通用规则

- **双语**：`docs/` 下新增/修改文档必须中英对照（`xxx.md` + `xxx.en.md`）同一提交，这是仓库硬约定。
- **状态头**：每份文档开头用引用块标注：状态、创建日期、依据（上游文档及编号）。
- **如实记录**：测试/验收报告的价值在于可信。skip、环境限制、未能核验的计数都要写明边界，
  不许把"没跑"写成"通过"。
- **后端/前端/脚本改动**仍须遵守对应的 `groundedcoreai-python-backend-standards` /
  `groundedcoreai-typescript-frontend-standards` / `groundedcoreai-shell-infra-standards`，
  本 skill 只规定文档流程，不替代编码规范。
- 完成前自检：后端 `cd backend && uv run ruff check src tests && uv run pytest`；
  前端 `cd frontend && npm run typecheck && npm run check:i18n && npm run build`。

## 模板索引

写哪份文档前，先读对应模板：

- `assets/templates/01-business-goals.md` — 业务目标
- `assets/templates/02-requirements.md` — 需求文档
- `assets/templates/03-technical-design.md` — 技术设计
- `assets/templates/04-test-plan.md` — 测试方案
- `assets/templates/05-acceptance-plan.md` — 验收方案
- `assets/templates/06-test-report.md` — 测试报告
- `assets/templates/07-acceptance-report.md` — 验收报告
- `assets/templates/08-implementation-breakdown.md` — 实施拆解（可选）
- `assets/templates/topic-README.md` — 主题索引 README

需要完整实例参考时读 `docs/requirement/agent-memory/phase-1-conversation-summary/`（最小完整套件）
与 `phase-3-event-memory-search/08-implementation-breakdown.md`（拆解与裁定范本）。
