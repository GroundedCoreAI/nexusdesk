# 推荐问题设计取舍

> 状态：已发布
>
> 本章回答：推荐问题从哪里来、要不要给每条问题配固定答案，以及「推荐」「知识检索」和「Agent 执行」各自负责什么。

## 一句话结论

**不新建独立的 QA 对数据模型，也不让每条推荐问题绑定固定答案**：推荐问题只作为用户表达入口；高频固定知识整理成 FAQ 内容进入知识库；默认由 Agent Runtime 通过 `knowledge_search` 检索并结合业务工具回答；只有少量高置信度、上下文无关的问题，才增加「精确匹配直答」快路径。

## 为什么不是「每条推荐问题配一个 QA 对」

业务目录里的推荐问题通常混在一起，看起来都是「一句话 + 一句话答案」，但实际分三类：

| 问题类型 | 示例 | 更适合的处理方式 |
| --- | --- | --- |
| 静态规则、流程说明 | 如何申请行程发票、怎么联系人工客服 | FAQ 知识 + `knowledge_search` |
| 需要用户上下文 | 如何查询历史行程、车费与预估价不一致 | ReAct + 业务查询工具 |
| 需要执行动作 | 物品遗失找回、投诉司机、取消订单 | ReAct + 对应 Skill/Action |

如果为每条推荐问题建立一个独立 QA 对，会带来五个问题：

1. **答案容易过期。** 活动规则、发票政策、客服渠道变化后，推荐问题配置和 QA 答案都要分别维护。
2. **同一答案会被重复存储。** 多个推荐问题可能最终指向同一份知识。
3. **无法覆盖自然语言变体。** 用户不一定会原样点击推荐问题，自由输入仍然需要检索。
4. **固定答案缺少上下文。** 历史行程、费用争议、物品遗失必须查询用户和订单数据，QA 对无法处理。
5. **增加不必要的管理复杂度。** 需要额外建设 QA 编辑、版本、发布、权限和评估体系。

## 四层职责

| 层 | 职责 |
| --- | --- |
| 猜你想问 | 用户表达入口 |
| FAQ / QA 内容 | 知识层的数据 |
| `knowledge_search` | 检索手段 |
| Agent Runtime | 理解、判断和生成回答 |

这四层不是二选一，而是各司其职：

- **推荐问题**负责「让用户更容易开口」，不负责保存答案；
- **FAQ 内容**负责承载稳定知识，随知识库版本和来源一起管理；
- **`knowledge_search`** 负责召回相关片段，并返回标题、版本和来源；
- **Agent Runtime** 负责结合上下文、工具结果和知识内容组织回答。

## 推荐问题应该绑定什么

推荐问题本身只保留入口信息：

```text
问题文案
可选：intent_key
可选：skill_key
可选：对象或上下文范围
```

而不是：

```text
问题文案 → 固定答案
```

当前服务应用的体验配置里，推荐问题就是一组文本（`suggestion_sets: list[list[str]]`），本来就没有绑定答案；业务目录中的条目则通过 `knowledge`、`query`、`action`、`handoff` 四类入口绑定到具体能力。需要优化的是入口与能力的对应关系，而不是再造一层「问题 + 答案」的数据模型：

- 静态知识题：整理成 FAQ 知识，走 `knowledge_search`；
- 订单、行程查询：绑定具体查询 Skill，由 Agent 判断是否需要调用；
- 取消、投诉、遗失找回：绑定 Action Skill，并保留人工确认；
- 人工客服：直接 handoff，不需要让模型先检索答案。

## FAQ 为什么现在就能承载固定知识

知识模块已经支持 `faq` 分片策略，可以把 Excel 中的「问题列 + 答案列」切分成 FAQ 知识片段：

`backend/src/agent_platform/business_capabilities/knowledge/chunking.py`

因此可以这样组织知识库：

```text
出行客服知识库
├── FAQ：发票规则
├── FAQ：费用争议处理说明
├── FAQ：物品遗失处理流程
├── FAQ：人工客服联系方式
└── 文档：其他业务政策和操作说明
```

Agent 在 ReAct 循环中调用 `knowledge_search`，检索到相关片段后再回答。不需要额外建立 `qa_pairs` 表，也不需要给每条「猜你想问」存一份答案。

## 是否需要「精确匹配后直接回答」

可以为少量高风险或完全固定的问题增加一个可选快路径：

```text
推荐问题
→ 精确/高置信度 FAQ 匹配
→ 命中则直接返回标准答案
→ 未命中则进入 ReAct + knowledge_search/tools
```

但这个快路径应当满足：

- 问题含义不受上下文影响；
- 标准答案唯一且稳定；
- 答案有版本和来源；
- 低于置信度阈值时自动回退 ReAct；
- 不适用于订单、行程、账户等个性化查询。

## 边界条件

- 个性化查询和写操作不走 QA 对，也不走「精确匹配直答」；
- 写操作即使命中 Action Skill，仍要保留人工确认，不能由推荐问题直接触发；
- 人工客服入口直接 handoff，避免让模型「先检索一段客服电话」再回答；
- FAQ 内容变更后应随知识库发布新版本，而不是修改某条推荐问题的答案。

## 对应实现与延伸阅读

- FAQ 分片策略：`backend/src/agent_platform/business_capabilities/knowledge/chunking.py`（`strategy="faq"`，按问题列、答案列逐行切分）；
- 知识检索工具：`backend/src/agent_platform/business_capabilities/knowledge/tools.py`（`knowledge_search` 返回标题、版本、片段和来源）；
- 推荐问题配置：`backend/src/agent_platform/business_capabilities/customer_service/service_apps/models.py`（`suggestion_sets`、`ExperienceEntryKind`）；
- 客户端「猜你想问」：`frontend/src/features/service-apps/experience/CustomerInteractionWorkspace.tsx`。

## 小结

推荐问题不是一张「问题答案表」，而是服务的入口层：它把用户带进场景，真正的答案来自 FAQ 知识、业务查询或 Action Skill，并由 Agent Runtime 结合上下文生成。这样既保留 Agent 的上下文理解能力，也避免把系统退化成一张难以维护的大型 FAQ 表。
