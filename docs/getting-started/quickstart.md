# 快速开始

本页带你从零启动 NexusDesk 体验环境，并确认 Agent 真的能工作。全程约 10 分钟。

## 准备工作

| 项 | 要求 |
|---|---|
| Docker | 20.10 及以上 |
| Docker Compose | v2（`docker compose` 子命令） |
| Docker Desktop | 请选择 **Linux 容器模式** |
| 网络 | 首次启动需要联网拉取镜像或编译前端 |

## 方式一：本地构建启动

```bash
# Linux / macOS
sh nexusdesk quickstart
```

```powershell
# Windows PowerShell
.\nexusdesk.ps1 quickstart
```

首次运行会编译前端并构建镜像，耗时较长；之后的启动会复用缓存。

## 方式二：使用已发布镜像

```bash
NEXUSDESK_IMAGE_REGISTRY=docker.io/groundedcore/ NEXUSDESK_VERSION=latest \
  docker compose -f deploy/quickstart/compose.yaml up -d
```

这一方式跳过本地构建，适合只想快速看效果的情况。

## 验证启动结果

打开 `https://localhost:8080`。

体验模式使用自签证书，浏览器会提示证书不受信任，继续访问即可。证书配置与局域网访问见[部署手册](https://github.com/GroundedCoreAI/nexusdesk/blob/integration/deploy/README.md)。

登录账号 `admin` / `nexusdesk`（仅用于本地体验）。

## 跑通第一个会话

进入预置的 `sample-support` 会话，依次试两句话：

1. 输入 **「发货需要多久？」** —— Agent 会检索知识库并给出带依据的回答。
2. 输入 **「帮我创建工单」** —— Agent 会拟定工单，等待你确认后才会真正创建。

这两步分别验证了知识检索链路与工具调用 + 人工确认链路。

## 体验行业案例

体验环境预置了 9 个行业案例：9 个知识库、18 个 Agent 草稿和 36 篇文档。

- 所有资源名带 `[案例]` 前缀；
- 在 Agent 列表用「**范围 → 仅看案例**」筛选；
- 详细说明见[行业案例](../guides/industry-examples.md)。

## 常见问题

**端口被占用**：`8080` 冲突时先停掉占用进程，或在 compose 文件里改端口映射。

**镜像拉取失败**：检查 `NEXUSDESK_IMAGE_REGISTRY` 是否带结尾斜杠，以及网络是否可访问镜像仓库。

**页面一直转圈**：容器里前端还在编译，用 `docker compose -f deploy/quickstart/compose.yaml logs -f web` 观察进度。

## 安全提醒

体验模式使用**模拟模型**，不代表真实回答质量；默认账号只用于本地，不构成生产认证边界。请保持默认 `127.0.0.1` 绑定；如需对外访问，用安全组或防火墙限制可信 IP。

## 下一步

- 部署到生产：[中间件说明](../operations/middleware.md)、[数据库迁移](../operations/database-migrations.md)
- 了解平台功能：[平台使用](../guides/platform.md)
- 理解运行机制：[Agent Runtime](../architecture/runtime.md)
