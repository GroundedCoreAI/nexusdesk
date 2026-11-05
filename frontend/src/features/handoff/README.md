# handoff

该目录包含人工协同工作台。

`HandoffPage` 使用现有后端接口：

- `GET /handoffs` 获取交接队列。
- `POST /handoffs/{id}/transition` 执行接管（`claim`）、结束并恢复 Agent（`resume`）和关闭会话（`close`），每次操作都会传递当前 `revision`。
- `GET /conversations/{conversation_id}` 读取会话来源、客户与业务上下文、最近消息和待确认动作。
- `GET /me` 识别当前操作者，用于“我的处理中”筛选和处理人权限判断。

工作台按全部、等待接管、我的处理中筛选，并支持按交接编号或原因搜索。操作权限继续由 `useAccess` 的 `operator` / `admin` 角色控制；只读角色可以查看队列和上下文，但不能改变交接状态。
