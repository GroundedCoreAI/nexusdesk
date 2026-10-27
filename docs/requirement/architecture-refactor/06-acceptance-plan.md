# 06. 验收计划

## A. 目录验收

- [x] `core_platform/`、`extension_contracts/`、`business_capabilities/`、`applications/` 存在。
- [x] 旧 `modules/`、`apps/`、`integrations/`、`platform/` 不再作为运行时目录存在。
- [x] 所有移动后的 Python 包包含必要的 `__init__.py`。

## B. 命名空间验收

- [x] 运行时代码不再引用旧模块命名空间。
- [x] 运行时代码不再引用旧应用命名空间。
- [x] 运行时代码不再引用旧集成命名空间。
- [x] 运行时代码不再引用旧契约命名空间。
- [x] 文档中的旧路径只出现在迁移说明或历史记录中。

## C. 架构边界验收

- [x] Contract 不依赖业务实现和 Application。
- [x] Core Platform 不依赖 Application 组合根。
- [x] Business Capability 不依赖 Application 路由和启动代码。
- [x] Application 负责组合，不承载平台或领域实现。
- [x] 架构门禁脚本通过。

## D. 代码和测试验收

```powershell
cd backend
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest -q
```

前端：

```powershell
cd frontend
npm run typecheck
npm run check:i18n
npm run build
```

## E. 数据库验收

使用既有 PostgreSQL 实例创建独立测试数据库，执行：

```powershell
python -m alembic upgrade head
python -m pytest -q -m postgres
```

目录重构本身不得产生未记录的数据库变化。

## F. 文档验收

```powershell
rg "agent_platform\.(modules|apps|integrations|contracts|platform)" docs
```

扫描结果只能包含迁移映射和历史说明，不能包含当前运行命令或有效代码路径。
