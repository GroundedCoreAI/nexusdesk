# Agent Execution Orchestrator 上线与回滚手册

本文适用于 Phase 2 的 `react/native/v1` 执行路径。它只切换既有 Runtime Worker 的进程内执行分支，不新增 UI、服务、客户端字段或另一套 ReAct。默认始终是既有 legacy 路径；本手册不是生产性能验收结论。

## 1. 开关与不变量

- 每个 API/Worker 进程在启动时读取 `AGENT_EXECUTION_ORCHESTRATOR_ENABLED`，默认 `false`。Worker 为 `false` 时走 legacy，为 `true` 时只走 Orchestrator。
- 修改环境变量后必须重建容器或由进程管理器滚动重启对应进程。`docker compose restart` 只重启旧容器，不会应用 compose/.env 中的新环境值。
- 这不是请求级热切换，也不是单个 Run 的自动 fallback。on Worker 缺少有效 Orchestrator/注册项或执行失败时按既有错误契约结束，不能静默改走 legacy。
- API 可以保持 off，由 on Worker 领取其提交的 queued Run。开关不参与 runtime-composition fingerprint，因此 off API、on Worker 和混合 Worker 不会因这一项配置产生 `configuration_changed`；其他运行时配置仍须保持一致。
- Repository 仍是唯一终态写者。无需 Alembic downgrade、数据修复、客户端变化或新服务。

## 2. 上线前检查

1. 部署包含本开关的同一版本，先让所有 API 和 Worker 保持 `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false`，完成正常迁移和启动。API 使用现有 healthcheck；`runtime-worker` 没有 healthcheck，必须按第 3、6 节的进程、日志和队列观察判定就绪。不要仅修改 `.env` 后执行 `docker compose restart`。
2. 确认当前固定组合为 `react/native/v1`，并确认除本开关外的模型、Profile、工具和其他 runtime 配置一致。
3. 保存变更前的非敏感基线：各 Worker 实例标识、开关值、`queued/running/terminal` 数量、现有错误率、SSE/终态检查及原始延迟样本。`run_id` 只在有权限的日志/trace 查询中使用。
4. 准备停止条件和回滚负责人。灰度期间不得同时升级 schema、修改客户端协议或添加 Worker 服务。

以下命令均从仓库根目录执行。生产配置值来自 `deploy/production/.env`；基础检查只校验配置和查看状态，不输出连接串或凭据：

```bash
docker compose --env-file deploy/production/.env \
  -f deploy/production/compose.yaml config -q
docker compose --env-file deploy/production/.env \
  -f deploy/production/compose.yaml ps
```

## 3. 小组灰度

### 3.1 只开启选定的 Worker

在 systemd、Kubernetes 或其他进程管理环境中，只给选定的 runtime Worker 实例/Deployment 覆盖 `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true`，然后滚动重建这些实例；不要修改共享的 API 配置或把同一值广播到全部 Worker。保留其余 Worker 为 off，逐个确认新进程已启动，并按 running 状态、日志、既有外部探针（若环境提供）及队列/claim/终态观察判定就绪；不要等待不存在的 Worker healthy 状态。

在已有生产 compose 环境中，可以先运行**一个一次性 canary 容器**。它复用同一个 `runtime-worker` 服务定义、镜像、网络和凭据，不是新服务：

```bash
docker compose --env-file deploy/production/.env \
  -f deploy/production/compose.yaml run --rm --no-deps \
  --name nexusdesk-runtime-orchestrator-canary \
  -e AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true \
  runtime-worker
```

前置条件是 normal migrate 已成功、数据库可用且现有 off `runtime-worker` 正在运行。`--no-deps` 不会再次执行迁移。`-e AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true` 只覆盖这个一次性 `runtime-worker` 容器，不修改 `deploy/production/.env`，也不改变 API 或其他服务。该容器与 off Worker 会按现有队列规则共同领取任务；队列不按路径路由，因此不能用本命令指定某个 Run 必须由 canary 领取。先提交低风险 Run，确认 off API → on Worker 的领取与终态，再决定是否扩大。

停止 canary 时，在运行它的终端发送中断，或执行：

```bash
docker stop nexusdesk-runtime-orchestrator-canary
```

确认该一次性容器已退出，并核对在途任务按既有 Lease/reaper 生命周期收敛。长期灰度应改由进程管理器维护选定 Worker，而不是遗留无人监管的一次性容器。

### 3.2 混合 Worker 的队列与存量行

- **queued**：off/on Worker 均可按现有原子 claim 规则领取。同一 queued 行只能由一个 owner 获得；混合部署不共享执行上下文，也不允许重领同一 owner 的活跃行。
- **running**：继续由原 owner、heartbeat、Lease、取消和 reaper 规则处理。切换或重启开关不会让另一路径接管同一次执行，也不能造成双执行。失租后的恢复仅来自既有 Lease/reaper 语义，不新增自动重试。
- **terminal**：保持 first-commit-wins。完成、取消、reaper 与迟到 finish/append 仍按既有规则竞争；终态绝不因发布或回滚被重写。

扩大灰度前，至少观察一个完整的在途任务收敛窗口，并核对：没有重复 owner/终态、off/on 输出和事件对等、取消/timeout/worker_lost 分类不变、queued 无异常积压、terminal 未变化、fingerprint 未报 `configuration_changed`。满足停止条件时立即进入第 6 节。

## 4. 观测与安全边界

新路径的 Worker 终态日志使用低基数字段：

- `path=orchestrator`
- `tuple=react/native/v1`
- `status=completed|failed|cancelled`
- failed 时固定为 `error=execution_failed`；completed/cancelled 不带 `error`
- 所有终态都有有限、非负的 `duration_ms`

可以按权限用 `run_id` 关联日志/trace，再检查 Run 状态、SSE 和持久化事件。不得把原始 legacy error code、未来未知 Provider code、原始异常/堆栈、prompt/input/history、客户数据、配置或凭据写入日志/trace；metrics 不得使用 `run_id`，只能使用上述低基数 `path/tuple/status/error` 标签。不得伪造 traces、metrics 或生产日志。

`duration_ms` 只是单次 Worker 执行日志，不能证明端到端生产性能。原始性能证据必须按验收方案 05 §4 保存：同一真实等价环境、相同输入与配置，至少 30 个有效 matched pairs，先执行且排除 5 组 matched warm-up pairs，off/on 交替或平衡顺序，分别保存 old/new 端到端时延、paired delta/ratio、Adapter 原始开销、首 token 和错误率。p95 使用 nearest-rank；外部模型/工具时延不得从端到端口径扣除。单个日志、demo/mock/test double 或 canonical diff 均不能用来宣称“生产增幅 ≤5%”；环境不足时性能子指标保持 `pending_env`。

## 5. 正常扩大与验证

每次只扩大一批 Worker，重复第 2～4 节检查，并保留每批的实例、时间、开关值和观测窗口。确认新进程实际生效，而不是仅修改了配置文件。继续验证：

1. off API 提交的 Run 可由 on Worker 完成，混合 Worker 不重复 claim。
2. 存量 queued 可读可领，running 仅按原 owner/Lease 收敛，terminal 前后不变。
3. on 路径失败不会静默 fallback；日志标签和 `duration_ms` 合法，无敏感信息或未来 code。
4. 新旧路径的结果、事件、SSE、取消、timeout、Lease/reaper 和终态规则不变。

## 6. 异常回滚

### 6.1 停止条件

出现任一情况即停止扩大并回滚：重复执行/重复终态、终态被改写、非预期 `configuration_changed`、on 失败静默进入 legacy、敏感信息或未来 code 泄漏、非有限/负数 `duration_ms`、取消/失租分类错误、queued 持续异常积压、SSE/结果对等破坏，或错误率/真实 matched-pairs 延迟超过既定门槛。

### 6.2 操作顺序

1. 停止启动新的 on Worker，并停止一次性 canary。
2. 将所有 Worker 的环境恢复为 `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false`，按批次重建/滚动重启。API 也保持 off；不要依赖请求级切换。
3. compose 管理的长期 `runtime-worker` 使用新环境强制重建，而不是 `restart`：

   ```bash
   docker compose --env-file deploy/production/.env \
     -f deploy/production/compose.yaml up -d --no-deps \
     --force-recreate runtime-worker
   ```

   其他进程管理环境应对每批 Worker 执行等价的滚动重建。若生产 compose 还有由同一共享 `.env` 启动的 Worker，先确认其配置也为 false，再逐批重建，避免一次切换全部进程。
4. 每批先确认目标容器为 running，检查启动/路径日志无异常，并在环境提供时使用既有外部探针；随后通过队列、claim、终态观察确认 Worker 就绪且旧在途任务按原 owner/heartbeat/Lease/reaper 收敛，再处理下一批。`runtime-worker` 没有 Docker healthcheck，running 不等于健康，不得等待不存在的 healthy。API 的既有 healthcheck 只用于 API，不能代替 Worker 判定。off Worker 会继续 claim queued；不会让同一请求自动 fallback 重跑。
5. 核对 terminal 仍为 first-commit-wins、失租只由既有 Lease/reaper 恢复、存量行未修数。回滚完成后，新被 off Worker 领取的 Run 应只出现 legacy 路径。

**验证完成条件**：所有 Worker 实例均为 false 且已换成新进程；一次性 canary 已退出；无重复 owner/终态和异常 queued 积压；在途任务已收敛；terminal 未被修改；后续 Run 符合 legacy 基线。若这些条件不满足，保持停止灰度并按现有 Run/Lease 故障流程处理，不以数据修复掩盖问题。

回滚不执行 Alembic downgrade，不修复/重写运行数据，不要求客户端变更，也不新增服务。T7 的受控演练证据保存在仓库外，正式 T8/T9 结论须由后续实际测试与人工验收独立给出。
