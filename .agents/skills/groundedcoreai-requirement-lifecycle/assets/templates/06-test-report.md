# Phase N · <阶段名> — 测试报告

> 状态：<待实施 / 进行中 / 已完成（结论摘要）>
> 创建：YYYY-MM-DD
> 依据：`04-test-plan.md`（PN-UT-01~xx、PN-IT-01~xx、PN-CM-01~xx）、`02-requirements.md`（FR/AC）
> 执行：<执行者>；日期：YYYY-MM-DD

## 1. 测试范围与环境

**范围**：<与 04 一致，注明修订增补>

| 环境 | 配置 | 用途 |
|---|---|---|
| 本机（<OS/Python 版本>） | <有无 PG/Docker> | ruff；非 postgres 用例 |
| CI（GitHub Actions + postgres:17 service） | `TEST_DATABASE_URL` | 全量套件（含 PG 用例） |
| 模型 | demo/mock（可编程） | 自动化用例 |

**skip 说明**：<哪些用例在何环境按预期 skip、在何环境补足执行；如实写>

## 2. 执行总览

| 项 | 结果 | 证据 |
|---|---|---|
| `uv run ruff check .` | <结果> | 附录 A-1 |
| `uv run pytest -q` | <X passed, Y skipped> | 附录 A-2 |
| CI Backend / Frontend job | <conclusion> | §CI 证据 |

## 3. 单元测试（PN-UT）逐条结果

| 编号 | 用例 | 测试位置 | 执行环境 | 结果 |
|---|---|---|---|---|
| PN-UT-01 | <用例> | `test_xxx.py::test_pn_ut_01_*` | 本机 | 通过 |

（每条用例一行；偏差注明并见残留风险）

## 4. 集成测试（PN-IT）逐条结果

| 编号 | 用例 | 测试位置 | 结果 |
|---|---|---|---|
| PN-IT-01 | <用例> | `test_xxx.py::test_pn_it_01_*` | 通过 |

## 5. 通用核对项（PN-CM）逐条结果

| 编号 | 核对项 | 测试位置 | 执行环境 | 结果 |
|---|---|---|---|---|
| PN-CM-01 | <核对项> | <位置> | <环境> | 通过 |

## 6. 回归范围

- <既有套件执行结果；新增字段空态行为不变的验证>

## 7. 迭代中发现并修复的缺陷

| # | 级别 | 缺陷 | 发现环节 | 修复 | 回归 |
|---|---|---|---|---|---|
| D1 | P1 | <描述> | <CI run / 评审轮> | <提交 sha 与修法> | <新增回归用例；复跑结果> |

## 8. 残留风险

| # | 级别 | 描述 | 处置 |
|---|---|---|---|
| R1 | P2 | <描述与影响面> | <owner/期限/决策建议> |

## 9. CI 证据

- PR：<链接>（head `<sha>`）
- 通过 run：<链接>（conclusion=success）
- 核验方式与边界：<如何核验、哪些计数未能逐行复核——如实写>

## 附录 A 本地执行输出快照（YYYY-MM-DD，工作目录 `backend/`）

A-1 `uv run ruff check .`

```text
<原始输出>
```

A-2 `uv run pytest -q`

```text
<原始输出>
```
