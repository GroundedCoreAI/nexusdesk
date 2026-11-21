# 阶段 4–6 范围限定验收 · pending_env 登记清单

> 状态：登记 / 索引文件，2026-11-21 归档入库（docs-only）。
> **本文件不是原始执行证据，也不构成任何验收通过结论。** 它由 `12-scope-limited-acceptance-record-20261118-phase4-6.md` §4、
> `09-acceptance-execution-runbook.md` §8 与 `10-remote-linux-acceptance-appendix-20261117.md` 的既有记录整理而成，
> 目的是把原仅存在于远程证据包中的 `pending_env` 清单纳入版本控制，解决 `12` §4 引用不可追溯的问题。
> 原始证据包：`20261118T150343Z.tar.gz`，SHA256 `bbc979e7d999a274fb689dbc458367dcca3c61610006c0339207ebe7e9e8050c`
> （见 `12` §5 单一验收记录），位于远程验收主机 `nexusdesk-accept` 的证据目录；本仓库不复制该 tarball。
> 按 `09` §8 与附录 C：`pending_env` 不得写成 pass；取消 `skipif(True)` 或复用 PG 级测试不等于关闭下列项。

## 1. 上下文与口径

`12` 号记录（2026-11-18，目标 SHA `80fac6056682a7835c61dab4678c5772b8689d1f`）判定阶段 4–6
**通过（范围限定 / PASS scope-limited）**：12 个 lane 全部 exit 0，6,103 JUnit 用例 / 0 failures /
0 errors / 62 个声明式 skip。按 2026-11-18 范围修订，下列 `pending_env` 项已**移出阶段验收门禁**，
仅作历史背景与**高风险能力启用前置**；`execution_*` / `codex_*` 开关保持默认关闭，
高风险启用（Runtime Host、生产 Codex 路由、Stage B、不可信多租户）未请求、未授权。

## 2. E 类环境门禁（09 §8）

| ID | 内容 | 阶段 | 当前状态 | 关闭前置条件 |
|---|---|---|---|---|
| E1 | 每 Execution cgroup v2 memory/PID/CPU 硬限（#133） | Phase 4 | `pending_env` | 实现 Linux provider 的 per-Execution cgroup 强制（当前 `probe_cgroup_v2_*` 只读控制器，`LOCAL_IMPLEMENTED` 排除三组能力）；替换 3 个 `skipif(True)` 占位测试；一次性隔离 Linux 主机（cgroup2 unified、memory/pids/cpu 控制器可用、passwordless sudo） |
| E2 | 文件系统 / project quota 总量强制 | Phase 4 | `pending_env` | 实现 provider 级 project quota（当前 `probe_fs_quota()` 返回 `unsupported`）；ext4/xfs + `prjquota` 挂载；测试 EDQUOT/ENOSPC 与幂等清理 |
| E3 | 实时 mount-namespace 实验 | Phase 4 | `pending_env` | 实现 provider 级 mount namespace 或受控 `unshare -m` 演练；当前共享机 `mountns=FAIL` |
| E4 | 确定性 OS PID 复用佐证 | Phase 4 | `pending_env` | 隔离 Linux 主机上的有界演练；决策表测试已存在，真实 OS 实验缺席 |
| E5 | 生产镜像 restart / stop-timeout / rollback | Phase 4 | `pending_env` | 可构建目标 SHA 的生产镜像 + 隔离主机；合成凭据，禁止拷贝真实生产 env |
| E6 | Phase 6 真实双 Worker SIGKILL / 心跳 / 迟到结果 / 混合故障 | Phase 6 | `pending_env` | 新增多进程故障注入测试；现有 `test_lost_worker_*` / `test_execution_r19_*` / `test_execution_t12_*` 为 PG 级，不可替代 |
| E7 | Phase 6 代表性已填充副本迁移 | Phase 6 | `pending_env` | 用户提供脱敏、具代表性的生产副本 dump；记录数据规模与匿名化方法 |
| E8 | Phase 3 C11 性能（#129） | Phase 3 | **已移出范围**（2026-11-18） | 不是阶段门禁，仅为历史注记；无需为阶段验收补测，不得用其它 suite 耗时推算 p95 |
| E9 | Phase 5 Stage A 20 场景 × 3 连续批次（P5-IT-18） | Phase 5 | `pending_env` | 新增批测 harness 并保留全部原始日志；为 Stage B 解锁条件之一，Stage B 仍锁定 |
| E10 | Phase 5 凭据 / 双租户 / 跨租户挂载 | Phase 5 | `pending_env` | 授权凭据与两个隔离可信租户；managed Secret canary、Host-auth 检查、撤销后 admission 关闭 |
| E11 | Phase 6 独立安全 / SRE 审批 | Phase 6 | `pending_env` | 由**独立**批准人签发，绑定目标 SHA、租户范围、批次计划、证据与撤销条件；验收负责人不能自我签发（`09` §8 E11、P6 `05` §独立审批例外、`08` R）。现有 `10-stage-a-cli-credential-lane-security-signoff.md` 仅覆盖 quickstart Stage A 凭据通道，不能替代本项 |

## 3. 其它 pending_env（12 §4 / 11 §6）

| ID | 内容 | 当前状态 | 说明 |
|---|---|---|---|
| D6 | Codex 真二进制 lane | `pending_env` | 无 CLI / 凭据；非阶段门禁 |
| D9 | live Compose off/on/rollback 演练 | `pending_env` | 共享生产机无书面变更审批、缓存镜像落后目标 SHA；开关完备性已由 `d9-switch-456`（976 tests）在目标 SHA 自动化证明，不构成门禁 |
| A-2 | 在线 live Compose off/on/rollback（阶段 0–3） | `pending_env` | 见 `11` §6；DockerHub 不可达、`node:22-alpine` 未缓存 |

## 4. 使用方式与边界

1. **不关闭任何项**：本清单只登记状态与前置条件。关闭需「实现产品能力 → 新增经评审的测试 → 在记录 SHA 与真实环境执行 → 追加证据约束的验收附录」（`09` §8、§10）。
2. **触发条件**：仅在申请高风险能力启用时逐项复核；当前阶段验收结论不依赖本清单。
3. **不可改写**：E8 已按范围修订废止为历史注记；E11 不可由代码、VM 或单一验收负责人产出。任何把 `pending_env` 写成 pass 的编辑都违反 `09` 附录 C 的证据纪律。
4. **证据溯源**：`12` §4 与 §5 给出证据包文件名与 SHA256；如需逐条原始日志，从远程验收主机证据目录取回 `20261118T150343Z.tar.gz` 校验后查阅。
