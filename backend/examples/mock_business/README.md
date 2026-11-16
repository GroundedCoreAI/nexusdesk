# Mock business API

服务应用示例使用的外部业务系统。应用连接可以指向这个 HTTP 服务，应用技能再声明参数、结果映射与安全规则。这个服务覆盖购物、游戏、创作者、出行、社区五类演示场景，共 25 个查询/受理接口。

## 快速启动

容器（推荐，独立于平台镜像）：

```bash
docker compose up -d mock-business       # 默认随栈启动，这里只是单独拉起
curl http://127.0.0.1:8010/health
```

本地 Python：

```bash
cd backend
uv run uvicorn examples.mock_business:app --host 127.0.0.1 --port 8010
```

网络无法直连 Docker Hub / PyPI 时，构建参数可以换镜像源：

```bash
docker build \
  --build-arg PYTHON_IMAGE=<mirror>/library/python:3.12-slim-bookworm \
  --build-arg PIP_INDEX_URL=https://<mirror>/simple \
  -t nexusdesk/mock-business-api:1.0.0 .
```

## 接到服务应用

四个 `example-*` 示例应用安装时已预接好本服务的连接（查询/受理技能开箱即用）。连接服务地址按部署形态自动取值，可用环境变量覆盖：

| 环境变量 | 默认值 |
|---|---|
| `AGENT_EXAMPLE_MOCK_BASE_URL` | `http://127.0.0.1:8010`（容器化后端填 `http://mock-business:8010`） |

手动接入其他应用：

1. 在「服务应用」中复制一个示例应用。
2. 在「应用连接」中新建 HTTP 连接，服务地址填下表中的地址。
3. 在「应用技能」中为连接配置参数、请求映射、结果映射和安全规则。
4. 从应用调试页预览一次，再发布并绑定客户渠道。

`--base-url` 要按调用方视角填：

| 后端跑在哪 | 应用连接服务地址 |
|---|---|
| 宿主机（`uvicorn ... --port 8001`） | `http://127.0.0.1:8010` |
| 容器里 | `http://mock-business:8010` |

## 两个刻意的设计

**1. `operationId` 就是网关工具名。** `shopping_order_status` 这类名字本来就符合工具网关的命名规则，导入后不需要改名，也不会出现「填了个点号名，存不进去」的情况。

**2. 只支持固定路径 + query 参数。** 工具网关不会对 `relative_path` 做路径模板替换，导入器也会跳过含 `{` 的路径。所以查询一律是 `GET /orders?order_no=...`，写入是 `POST` + JSON 请求体（字段声明成 Pydantic 模型，`additionalProperties: false` 才能通过工具的 schema 校验）。

## 响应约定

```json
{"code": 0, "message": "ok", "data": {"order_no": "...", "status": "已发货"}}
{"code": 0, "message": "ok", "data": {"items": [], "total": 0}}
{"code": 40401, "message": "订单不存在: ...", "data": null}
```

执行器的 `result_root` 填 `data`（单对象）或 `data.items`（列表）。404 会被桥接层判为 `missing`，403 判为 `denied`。

## 故障与鉴权模拟

```bash
# 让接下来 2 次业务请求返回 500，用来验证 on_error 降级
curl -X POST "http://127.0.0.1:8010/_admin/fault?mode=500&count=2"

# 单次调试（curl 用，工具的 schema 不允许额外参数）
curl "http://127.0.0.1:8010/orders?order_no=PO20261110001&__fault=403"

# 恢复演示数据与故障状态
curl -X POST http://127.0.0.1:8010/_admin/reset
```

| 环境变量 | 作用 |
|---|---|
| `MOCK_AUTH_TOKEN` | 设了才校验 `Authorization: Bearer`，用于验证凭证注入（缺失 401，错误 403） |
| `MOCK_LATENCY_MS` | 每个请求固定延迟，模拟慢上游 |
| `MOCK_TIMEOUT_SECONDS` | `__fault=timeout` 的挂起时长，默认 35 |

## 演示数据

固定夹具在 `fixtures.py`，常用 ID：

| 对象 | ID |
|---|---|
| 购买订单 | `PO20261110001`（已发货）、`PO20261110002`（待付款） |
| 物流运单 | `SF7788990011` |
| 售后工单 | `AS20261110001` |
| 游戏角色 | `ROLE-1001` |
| 充值订单 | `RC20261110001`（已到账）、`RC20261110002`（未到账） |
| 处罚记录 | `SN20261110001` |
| 创作者 | `CR-2001` |
| 作品 | `WK20261110001`（审核不通过） |
| 审核记录 | `RV20261110001` |
| 行程 / 计价 | `TR20261110001` |
| 会员 / 社区账号 | `ACC-3001` |
| 社区内容 | `CT20261110001` |

不存在的 ID 统一返回 404，用来看「上游查不到」时的表现。
